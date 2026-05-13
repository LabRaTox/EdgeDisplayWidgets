"""FastAPI entrypoint: lifespan-managed Hub + WebSocket + static frontend."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .config import AppConfig, load_config
from .hub import Hub
from .notes import MAX_BODY_LEN, MAX_TITLE_LEN, NotesStore, public_view

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
LOCAL_CONFIG = ROOT / "config.local.yaml"
FRONTEND_DIR = ROOT / "frontend"


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    """Pick the config file to load, preferring config.local.yaml when present.

    Resolution order:
      1. Explicit `config_path` argument (e.g., from tests)
      2. ``$EDGE_CONFIG`` env var
      3. ``config.local.yaml`` in the project root, if it exists
      4. ``config.yaml`` (the documented template)
    """
    if explicit:
        return Path(explicit)
    env = os.environ.get("EDGE_CONFIG")
    if env:
        return Path(env)
    if LOCAL_CONFIG.is_file():
        return LOCAL_CONFIG
    return DEFAULT_CONFIG


def _setup_logging(cfg: AppConfig) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=cfg.logging.level,
        serialize=cfg.logging.as_json,
        backtrace=False,
        diagnose=False,
    )


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `updates` into `base`. Lists/scalars are replaced."""
    out = dict(base)
    for key, value in updates.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


_QA_PUBLIC_FIELDS = {"id", "label", "icon", "kind", "confirm"}
# Smart-light providers carry API keys / OAuth secrets we must never expose.
_SMART_LIGHT_SECRET_KEYS = {"api_key", "secret", "client_id", "uid"}


def _summarize_validation_error(exc: Exception) -> str:
    """Format a Pydantic ValidationError without echoing input values back.

    Pydantic v2 includes the offending ``input_value`` in its default string
    representation, which leaks secrets (e.g. an HTTP Action's
    ``Authorization`` header) into logs and HTTP-400 responses. We re-format
    using ``errors()`` and explicitly drop input/URL noise.
    """
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return type(exc).__name__
    parts = []
    for err in exc.errors(include_url=False, include_input=False, include_context=False):
        loc = ".".join(str(p) for p in err.get("loc") or [])
        msg = err.get("msg") or err.get("type", "invalid")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "validation failed"


def _settings_view(cfg: AppConfig) -> dict[str, Any]:
    """Subset of the config that the Settings UI exposes for editing.

    Sensitive fields from `quick_actions` (commands, URLs, auth headers) and
    `smart_lights` (API keys, OAuth client secrets) are scrubbed before
    being exposed — even though the dashboard binds to localhost by default,
    treating `/api/settings` as a security boundary keeps a future
    `host: 0.0.0.0` flip from leaking tokens.
    """
    modules: dict[str, Any] = {}
    for name, mc in cfg.modules.items():
        dumped = mc.model_dump()
        if name == "quick_actions" and isinstance(dumped.get("actions"), list):
            dumped["actions"] = [
                {k: v for k, v in a.items() if k in _QA_PUBLIC_FIELDS}
                for a in dumped["actions"] if isinstance(a, dict)
            ]
        if name == "smart_lights":
            for provider_key in ("govee", "tuya"):
                pcfg = dumped.get(provider_key)
                if isinstance(pcfg, dict):
                    dumped[provider_key] = {
                        k: ("***" if k in _SMART_LIGHT_SECRET_KEYS and v else v)
                        for k, v in pcfg.items()
                    }
        modules[name] = dumped
    return {
        "default_theme": cfg.default_theme,
        "modules": modules,
        "pages": [p.model_dump() for p in cfg.pages],
    }


# Anything that reflects mutable runtime state must skip the browser cache,
# otherwise a refresh after Save can show stale data.
_NO_STORE = {"Cache-Control": "no-store"}


class _RevalidatingStaticFiles(StaticFiles):
    """StaticFiles that forces the browser to revalidate every request.

    Without an explicit Cache-Control header Chromium applies "heuristic
    freshness" (based on Last-Modified) and reuses cached JS modules even
    across browser restarts — so a redeploy of the dashboard can show stale
    widget code on the kiosk. `no-cache` keeps the cache, but the browser must
    revalidate every request; with the ETag we already emit, that's a cheap
    304 when nothing has changed.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


def create_app(config_path: str | Path | None = None) -> FastAPI:
    cfg_path = resolve_config_path(config_path)
    cfg = load_config(cfg_path)
    _setup_logging(cfg)
    logger.info(f"loaded config from {cfg_path}")

    hub = Hub(cfg)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await hub.start()
        try:
            yield
        finally:
            await hub.stop()

    app = FastAPI(title="Edge Dashboard", version="0.1.0", lifespan=lifespan)
    app.state.config_path = cfg_path
    app.state.config = cfg
    app.state.hub = hub

    # ------------------------------------------------------ Origin check
    #
    # The dashboard is single-user and bound to localhost by default. That
    # blocks remote attackers, but a malicious tab in the *same* browser can
    # still issue a "simple request" POST to /api/quick_actions/.../run
    # (CSRF). Without a CORS preflight the browser hides the response, but
    # the action has already executed.
    #
    # Defense: state-changing requests must carry an Origin/Referer that
    # matches the server's own host. Modern browsers always send Origin for
    # cross-origin POST/PUT/DELETE; same-origin POSTs in fetch() also send
    # it. Tools like curl can still hit the API since they omit Origin.
    _ALLOWED_HOSTS = {cfg.server.host, "127.0.0.1", "localhost"}

    def _origin_host_matches(origin: str | None, request_host: str | None) -> bool:
        if not origin:
            return True  # same-origin form/HTML nav, or non-browser client
        try:
            from urllib.parse import urlparse

            parsed = urlparse(origin)
        except Exception:
            return False
        if not parsed.hostname:
            return False
        if parsed.hostname not in _ALLOWED_HOSTS:
            return False
        # When we know the request's own Host header, also enforce port match
        # to avoid a same-host-different-port relay.
        if request_host and ":" in request_host:
            host_port = request_host.rsplit(":", 1)[-1]
            if parsed.port and str(parsed.port) != host_port:
                return False
        return True

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        if not _origin_host_matches(origin, host):
            logger.warning(
                f"rejected {request.method} {request.url.path} from origin={origin!r}"
            )
            return JSONResponse(
                {"error": "cross-origin request rejected"},
                status_code=403,
                headers=_NO_STORE,
            )
        return await call_next(request)

    # Helper accessors so route handlers always see fresh state after hot-reload.
    def current_cfg() -> AppConfig:
        return app.state.config

    def current_hub() -> Hub:
        return app.state.hub

    @app.get("/api/config")
    async def get_config() -> JSONResponse:
        """Frontend fetches pages, theme, and active modules at boot."""
        cfg_now = current_cfg()
        hub_now = current_hub()
        return JSONResponse(
            {
                "default_theme": cfg_now.default_theme,
                "pages": [p.model_dump() for p in cfg_now.pages],
                "modules": sorted(hub_now.modules.keys()),
            },
            headers=_NO_STORE,
        )

    @app.get("/api/snapshot")
    async def get_snapshot() -> JSONResponse:
        return JSONResponse(current_hub().snapshot(), headers=_NO_STORE)

    @app.post("/api/media/{action}")
    async def media_action(action: str, request: Request) -> JSONResponse:
        media = current_hub().modules.get("media")
        if media is None or not hasattr(media, "action"):
            return JSONResponse(
                {"ok": False, "reason": "media module not active"},
                status_code=503,
            )
        kwargs: dict[str, object] = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                body = await request.json()
                if isinstance(body, dict):
                    kwargs = body
            except Exception:
                pass
        ok = await media.action(action, **kwargs)
        return JSONResponse({"ok": ok}, status_code=200 if ok else 400)

    @app.get("/api/media/art/{token}")
    async def media_art(token: str) -> Response:
        media = current_hub().modules.get("media")
        if media is None or not hasattr(media, "get_art"):
            raise HTTPException(status_code=404, detail="media module not active")
        item = media.get_art(token)
        if item is None:
            raise HTTPException(status_code=404, detail="art not cached")
        data, mime = item
        return Response(
            content=data,
            media_type=mime,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/themes")
    async def get_themes() -> JSONResponse:
        themes_dir = FRONTEND_DIR / "css" / "themes"
        cfg_now = current_cfg()
        if not themes_dir.is_dir():
            return JSONResponse({"themes": [], "default": cfg_now.default_theme})
        names = sorted(p.stem for p in themes_dir.glob("*.css") if not p.stem.startswith("_"))
        return JSONResponse({"themes": names, "default": cfg_now.default_theme})

    @app.get("/api/widgets")
    async def get_widgets() -> JSONResponse:
        """List widget JS files discovered in frontend/js/widgets/.

        Used by the Layout-Editor to populate the 'add widget' picker. Drop
        a new ``<name>.js`` and it appears here.
        """
        widgets_dir = FRONTEND_DIR / "js" / "widgets"
        if not widgets_dir.is_dir():
            return JSONResponse({"widgets": []})
        names = sorted(p.stem for p in widgets_dir.glob("*.js") if not p.stem.startswith("_"))
        return JSONResponse({"widgets": names})

    @app.get("/api/settings")
    async def get_settings() -> JSONResponse:
        """Editable subset of the config (modules + default_theme + pages)."""
        return JSONResponse(_settings_view(current_cfg()), headers=_NO_STORE)

    @app.post("/api/settings")
    async def post_settings(request: Request) -> JSONResponse:
        """Apply settings changes, persist to config.local.yaml, hot-reload the hub.

        The body should be a partial settings object (same shape as
        ``GET /api/settings``); unspecified keys keep their current values.
        Validation runs through the full Pydantic schema before anything is
        written.
        """
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="expected an object")

        # Build the fully-merged config dict.
        current_dict = current_cfg().model_dump()
        merged = _deep_merge(current_dict, body)
        try:
            new_cfg = AppConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"validation failed: {_summarize_validation_error(exc)}")

        # Persist to config.local.yaml so the change survives restarts.
        target = LOCAL_CONFIG
        try:
            target.write_text(
                yaml.safe_dump(
                    deepcopy(merged),
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to write {target}: {exc}")

        # Hot-reload the hub so the change takes effect immediately.
        await current_hub().reload(new_cfg)
        app.state.config = new_cfg
        app.state.config_path = target
        logger.info(f"settings updated; persisted to {target}")
        return JSONResponse(
            {"ok": True, "settings": _settings_view(new_cfg)},
            headers=_NO_STORE,
        )

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # WebSockets bypass the http middleware, so re-apply the origin check.
        # Cross-Site WebSocket Hijacking would otherwise let a malicious tab
        # subscribe to the data stream from the same browser profile.
        origin = ws.headers.get("origin")
        host = ws.headers.get("host")
        if not _origin_host_matches(origin, host):
            logger.warning(f"rejected ws connection from origin={origin!r}")
            await ws.close(code=1008)
            return
        await ws.accept()
        hub_now = current_hub()
        await hub_now.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await hub_now.disconnect(ws)

    @app.post("/api/smart_lights/{device_id}/control")
    async def control_smart_light(device_id: str, request: Request) -> JSONResponse:
        """Control a single smart light. Body: `{action: "on"|"off"|"brightness", value?: int}`."""
        mod = current_hub().modules.get("smart_lights")
        if mod is None or not hasattr(mod, "control"):
            raise HTTPException(503, "smart_lights module not active")
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(400, f"invalid JSON: {exc}")
        if not isinstance(body, dict):
            raise HTTPException(400, "expected an object")
        action = str(body.get("action", ""))
        value = body.get("value")
        result = await mod.control(device_id, action, value)
        status = 200 if result.get("ok") else 400
        return JSONResponse(result, status_code=status, headers=_NO_STORE)

    @app.get("/api/quick_actions/config")
    async def get_quick_actions_config() -> JSONResponse:
        """Full quick_actions config — includes commands, URLs, headers, etc.

        Distinct from /api/settings (which scrubs these for safety): the
        editor GUI needs the unscrubbed values to round-trip without data
        loss. Treat this endpoint as the same privilege level as the
        config file on disk.
        """
        from .modules.quick_actions import QuickAction

        mc = current_cfg().modules.get("quick_actions")
        dumped = mc.model_dump() if mc is not None else {}
        raw_actions = dumped.get("actions") or []
        actions_out: list[dict[str, Any]] = []
        for raw in raw_actions:
            if not isinstance(raw, dict):
                continue
            try:
                # Re-validate so we emit canonical shapes (e.g. json alias).
                qa = QuickAction.model_validate(raw)
                actions_out.append(qa.model_dump(by_alias=True, exclude_defaults=True))
            except Exception:
                # Surface the raw form so a malformed entry can still be
                # fixed in the editor instead of being silently dropped.
                actions_out.append(raw)
        return JSONResponse(
            {
                "actions": actions_out,
                "timeout_seconds": float(dumped.get("timeout_seconds", 30.0)),
                "enabled": bool(dumped.get("enabled", True)),
            },
            headers=_NO_STORE,
        )

    @app.post("/api/quick_actions/config")
    async def post_quick_actions_config(request: Request) -> JSONResponse:
        """Replace the quick_actions config (actions list + timeout)."""
        from .modules.quick_actions import QuickAction

        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(400, f"invalid JSON: {exc}")
        if not isinstance(body, dict):
            raise HTTPException(400, "expected an object")
        actions = body.get("actions")
        if not isinstance(actions, list):
            raise HTTPException(400, "expected `actions` list")

        seen_ids: set[str] = set()
        validated_actions: list[dict[str, Any]] = []
        for i, a in enumerate(actions):
            if not isinstance(a, dict):
                raise HTTPException(400, f"action #{i + 1}: expected an object")
            try:
                qa = QuickAction.model_validate(a)
            except Exception as exc:
                raise HTTPException(400, f"action #{i + 1}: {_summarize_validation_error(exc)}")
            if qa.id in seen_ids:
                raise HTTPException(400, f"duplicate action id: {qa.id!r}")
            seen_ids.add(qa.id)
            validated_actions.append(qa.model_dump(by_alias=True, exclude_defaults=True))

        patch: dict[str, Any] = {"actions": validated_actions}
        if "timeout_seconds" in body:
            try:
                patch["timeout_seconds"] = float(body["timeout_seconds"])
            except (TypeError, ValueError):
                raise HTTPException(400, "timeout_seconds must be a number")

        current_dict = current_cfg().model_dump()
        merged = _deep_merge(current_dict, {"modules": {"quick_actions": patch}})
        try:
            new_cfg = AppConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(400, f"validation failed: {_summarize_validation_error(exc)}")

        target = LOCAL_CONFIG
        try:
            target.write_text(
                yaml.safe_dump(
                    deepcopy(merged),
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise HTTPException(500, f"failed to write {target}: {exc}")

        await current_hub().reload(new_cfg)
        app.state.config = new_cfg
        app.state.config_path = target
        logger.info(f"quick_actions config updated; persisted to {target}")
        return JSONResponse({"ok": True, "count": len(validated_actions)}, headers=_NO_STORE)

    @app.post("/api/quick_actions/{action_id}/run")
    async def run_quick_action(action_id: str) -> JSONResponse:
        """Look up the action by id in the configured allowlist and execute.

        The frontend never sends commands or URLs — only the opaque id. The
        actual command / URL / headers stay server-side in the config.
        """
        mod = current_hub().modules.get("quick_actions")
        if mod is None or not hasattr(mod, "run"):
            raise HTTPException(503, "quick_actions module not active")
        result = await mod.run(action_id)
        status = 200 if result.get("ok") else 400
        return JSONResponse(result, status_code=status, headers=_NO_STORE)

    notes_store = NotesStore()

    @app.get("/api/notes")
    async def get_notes() -> JSONResponse:
        return JSONResponse(public_view(notes_store.list()), headers=_NO_STORE)

    @app.post("/api/notes")
    async def post_note(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="expected an object")
        title = str(body.get("title", ""))[:MAX_TITLE_LEN]
        text = str(body.get("body", ""))[:MAX_BODY_LEN]
        note_id = body.get("id")
        note_id = str(note_id) if note_id else None
        try:
            note = notes_store.upsert(title=title, body=text, note_id=note_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return JSONResponse(note.model_dump(), headers=_NO_STORE)

    @app.delete("/api/notes/{note_id}")
    async def delete_note(note_id: str) -> JSONResponse:
        if not notes_store.delete(note_id):
            raise HTTPException(status_code=404, detail="note not found")
        return JSONResponse({"ok": True}, headers=_NO_STORE)

    if FRONTEND_DIR.is_dir():
        app.mount("/", _RevalidatingStaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    else:
        logger.warning(
            f"frontend directory not found at {FRONTEND_DIR} — static mount skipped"
        )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    cfg: AppConfig = app.state.config
    uvicorn.run(
        "backend.main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
