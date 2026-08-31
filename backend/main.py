"""FastAPI entrypoint: lifespan-managed Hub + WebSocket + static frontend."""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import signal
import subprocess
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

from . import autostart
from .config import AppConfig, load_config
from .hub import Hub
from .modules.base import get_registry
from .notes import MAX_BODY_LEN, MAX_TITLE_LEN, NotesStore, public_view
from .tray import SystemTray

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
LOCAL_CONFIG = ROOT / "config.local.yaml"
FRONTEND_DIR = ROOT / "frontend"


# .desktop Exec field codes (https://specifications.freedesktop.org/...) —
# stripped before turning Exec into an argv list.
_DESKTOP_FIELD_CODES = re.compile(r"%[fFuUdDnNickvm]")


def _parse_desktop(path: Path) -> dict[str, Any] | None:
    """Parse a .desktop file into {name, exec(argv), icon}, or None to skip."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    in_entry = False
    data: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip()
    if data.get("Type") != "Application":
        return None
    if data.get("NoDisplay", "").lower() == "true" or data.get("Hidden", "").lower() == "true":
        return None
    if data.get("Terminal", "").lower() == "true":
        return None  # needs a terminal we can't provide on the kiosk
    name = data.get("Name")
    exec_str = data.get("Exec")
    if not name or not exec_str:
        return None
    cleaned = _DESKTOP_FIELD_CODES.sub("", exec_str).strip()
    try:
        argv = shlex.split(cleaned)
    except ValueError:
        return None
    if not argv:
        return None
    return {"name": name, "exec": argv, "icon": data.get("Icon", "")}


_ICON_NAME_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
_icon_index_cache: dict[str, str] | None = None


def build_icon_index() -> dict[str, str]:
    """Map icon *name* (file stem) → best file path across XDG icon themes.

    Cached after the first build (scanning the theme dirs is the slow part).
    Used to resolve a .desktop ``Icon=`` name to an actual image we can serve.
    """
    global _icon_index_cache
    if _icon_index_cache is not None:
        return _icon_index_cache

    home = Path.home()
    xdg_data_home = os.environ.get("XDG_DATA_HOME") or str(home / ".local/share")
    roots = [
        Path(xdg_data_home) / "icons",
        Path("/usr/local/share/icons"),
        Path("/usr/share/icons"),
    ]
    best: dict[str, tuple[int, str]] = {}

    def consider(p: Path) -> None:
        size_dir = p.parent.parent.name  # <theme>/<size>/apps/<name>.<ext>
        if size_dir == "scalable":
            size = 256 if p.suffix == ".svg" else 0
        else:
            m = re.match(r"(\d+)", size_dir)
            size = int(m.group(1)) if m else 0
        ext_pref = {".png": 2, ".svg": 2, ".xpm": 0}.get(p.suffix.lower(), 1)
        score = ext_pref * 1000 - abs(size - 64)  # prefer ~64px raster/svg over xpm
        cur = best.get(p.stem)
        if cur is None or score > cur[0]:
            best[p.stem] = (score, str(p))

    for root in roots:
        if not root.is_dir():
            continue
        for ext in ("png", "svg", "xpm"):
            for p in root.glob(f"*/*/apps/*.{ext}"):
                consider(p)
    index = {k: v[1] for k, v in best.items()}
    # Flat pixmaps as a fallback for names not found in any theme.
    pixmaps = Path("/usr/share/pixmaps")
    if pixmaps.is_dir():
        for ext in ("png", "svg", "xpm"):
            for p in pixmaps.glob(f"*.{ext}"):
                index.setdefault(p.stem, str(p))

    _icon_index_cache = index
    return index


def _resolve_icon_name(icon_field: str, index: dict[str, str]) -> str:
    """Return a servable icon name for a .desktop Icon value, or ""."""
    if not icon_field:
        return ""
    if icon_field.startswith("/"):
        p = Path(icon_field)
        if p.is_file():
            index[p.stem] = str(p)  # register so the icon endpoint can serve it
            return p.stem
        return ""
    return icon_field if icon_field in index else ""


def scan_desktop_apps() -> list[dict[str, Any]]:
    """Discover launchable desktop applications from the XDG data dirs."""
    home = Path.home()
    xdg_data_home = os.environ.get("XDG_DATA_HOME") or str(home / ".local/share")
    xdg_data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    bases = [xdg_data_home, *xdg_data_dirs.split(":")]
    dirs = [Path(b) / "applications" for b in bases if b]
    dirs.append(Path("/var/lib/flatpak/exports/share/applications"))
    dirs.append(Path(xdg_data_home) / "flatpak/exports/share/applications")

    seen_files: set[str] = set()
    apps: dict[str, dict[str, Any]] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.desktop")):
            if f.name in seen_files:  # earlier dirs win (user overrides system)
                continue
            seen_files.add(f.name)
            entry = _parse_desktop(f)
            if entry:
                apps.setdefault(entry["name"].lower(), entry)

    index = build_icon_index()
    for entry in apps.values():
        entry["icon"] = _resolve_icon_name(entry.get("icon", ""), index)
    return sorted(apps.values(), key=lambda a: a["name"].lower())


def app_version() -> str:
    """Single source of truth for the app version — the installed package
    metadata (i.e. pyproject's ``version``), falling back to the module
    constant when running from a non-installed checkout."""
    try:
        return _pkg_version("edge-dashboard")
    except PackageNotFoundError:
        from . import __version__

        return __version__


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
# Placeholder sent to the browser in place of a stored secret's real value, and
# recognised on the way back in so an unchanged field keeps its stored value.
_SECRET_MASK = "***"


def _module_schemas() -> dict[str, list[dict[str, Any]]]:
    """Editable-field schema per registered module, for the Settings UI.

    Empty schemas are omitted; the module still shows its enabled/interval row.
    """
    registry = get_registry()
    if not registry:  # tests may hit this before the Hub ran discovery
        Hub.discover()
        registry = get_registry()
    out: dict[str, list[dict[str, Any]]] = {}
    for name, cls in registry.items():
        schema = getattr(cls, "settings_schema", None) or []
        if schema:
            out[name] = [f.model_dump() for f in schema]
    return out


def _secret_paths(module_name: str) -> list[tuple[str, ...]]:
    """Dotted key paths of a module's secret fields, from its schema."""
    cls = get_registry().get(module_name)
    if cls is None:
        return []
    return [
        tuple(f.key.split("."))
        for f in (getattr(cls, "settings_schema", None) or [])
        if f.secret
    ]


def _walk_to_parent(d: dict[str, Any], path: tuple[str, ...]) -> tuple[dict[str, Any] | None, str]:
    """Descend `path[:-1]` into `d`; return (parent_dict, last_key) or (None, _)."""
    cur: Any = d
    for p in path[:-1]:
        cur = cur.get(p) if isinstance(cur, dict) else None
        if not isinstance(cur, dict):
            return None, ""
    return (cur, path[-1]) if isinstance(cur, dict) else (None, "")


def _mask_secrets(dumped: dict[str, Any], module_name: str) -> None:
    """Replace non-empty secret values with the mask sentinel, in place."""
    for path in _secret_paths(module_name):
        parent, last = _walk_to_parent(dumped, path)
        if parent is not None and parent.get(last):
            parent[last] = _SECRET_MASK


def _strip_unchanged_secrets(body: dict[str, Any]) -> None:
    """Drop incoming secret fields still at the mask sentinel, in place.

    A masked value means "the user didn't touch this" — removing it from the
    patch lets the deep-merge keep the currently-stored secret instead of
    overwriting it with literal ``***``.
    """
    modules = body.get("modules")
    if not isinstance(modules, dict):
        return
    for name, mc in modules.items():
        if not isinstance(mc, dict):
            continue
        for path in _secret_paths(name):
            parent, last = _walk_to_parent(mc, path)
            if parent is not None and parent.get(last) == _SECRET_MASK:
                del parent[last]


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
        # Mask secret fields (API keys, OAuth secrets) declared in each module's
        # settings schema — even on localhost, treating /api/settings as a
        # boundary keeps a future host: 0.0.0.0 flip from leaking tokens.
        _mask_secrets(dumped, name)
        modules[name] = dumped
    return {
        "default_theme": cfg.default_theme,
        "default_language": cfg.default_language,
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


class AutostartPayload(BaseModel):
    enabled: bool


# `static variants = ["compact", "wide"]` in a widget's JS file. Read rather
# than duplicated in a table here: the list belongs next to the code that acts
# on it, and a table would be wrong the first time someone forgets it.
_WIDGET_VARIANTS_RE = re.compile(r"static\s+variants\s*=\s*\[([^\]]*)\]")
_JS_STRING_RE = re.compile(r"""["']([^"']+)["']""")


def _widget_variants(path: Path) -> list[str]:
    """Variant names a widget JS file declares, or [] if it declares none.

    Deliberately a regex and not a JS parser: the declaration is one literal
    line of one known shape, and the alternative — a manifest file per widget,
    or a list maintained in Python — is another thing to keep in sync. A
    widget that writes it differently simply offers no variants, which is
    exactly what a widget without the line does.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    match = _WIDGET_VARIANTS_RE.search(text)
    if not match:
        return []
    return _JS_STRING_RE.findall(match.group(1))


def _write_local_config(path: Path, data: dict[str, Any]) -> None:
    """Write the local config, atomically, keeping the previous version.

    `write_text` truncates first and then writes: a crash, a full disk or a
    power cut in between leaves a half-written or empty config, and this file
    is the only place the settings live. Staging to a temporary file in the
    same directory and renaming it is atomic on POSIX, so a reader sees either
    the old file or the new one.

    The `.bak` copy is the second half of that: it survives a *valid* but
    unwanted write, which no amount of atomicity protects against.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        deepcopy(data), default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    if path.is_file():
        # Copied, not renamed: a rename would briefly leave no config at all.
        with contextlib.suppress(OSError):
            path.with_suffix(path.suffix + ".bak").write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8"
            )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _quit_dashboard() -> None:
    """Tray → Quit: take the kiosk down, then ourselves.

    Leaving the kiosk running would park it on its waiting screen forever,
    which reads as a crash rather than as "you switched it off". SIGINT is
    what the unit sends too (`KillSignal=SIGINT`), so uvicorn shuts down the
    same way it would on `systemctl stop` — cleanly, and with an exit code
    that keeps `Restart=on-failure` from bringing it straight back.
    """
    logger.info("quit requested from the tray")
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["systemctl", "--user", "stop", "edge-kiosk.service"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    os.kill(os.getpid(), signal.SIGINT)


def create_app(config_path: str | Path | None = None) -> FastAPI:
    cfg_path = resolve_config_path(config_path)
    cfg = load_config(cfg_path)
    _setup_logging(cfg)
    logger.info(f"loaded config from {cfg_path}")

    hub = Hub(cfg)

    # The tray icon is opt-in through the environment rather than the config,
    # because it must not appear when the app is merely constructed: the test
    # suite builds `create_app()` dozens of times, and on a developer machine
    # with a session bus every one of them would register an icon in the
    # panel. `main()` sets the variable, so the service gets a tray and
    # nothing else does. `EDGE_TRAY=0` in the unit turns it off again.
    tray = SystemTray(
        url=f"http://{cfg.server.host}:{cfg.server.port}",
        language=cfg.default_language,
        on_quit=_quit_dashboard,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await hub.start()
        if os.environ.get("EDGE_TRAY", "0") == "1":
            await tray.start()
        try:
            yield
        finally:
            await tray.stop()
            await hub.stop()

    app = FastAPI(title="Edge Dashboard", version=app_version(), lifespan=lifespan)
    app.state.config_path = cfg_path
    app.state.config = cfg
    app.state.hub = hub
    app.state.tray = tray

    # ------------------------------------------------------------- CORS
    #
    # The kiosk is served from this very origin and needs nothing here. The
    # settings window is a separate application: inside its Tauri frame the
    # page lives under `tauri://localhost` (Linux/WebKitGTK also uses
    # `http://tauri.localhost`), so every call to the backend is cross-origin
    # and the webview blocks it unless we say otherwise — silently, which
    # looks exactly like a dead backend from the outside.
    #
    # Nothing is opened up by this: the server binds 127.0.0.1, so no one
    # outside the machine can reach it in the first place.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=(
            r"^(https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"
            r"|https?://tauri\.localhost"
            r"|tauri://localhost)$"
        ),
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    # `tauri.localhost` is the settings window, not a remote site: Tauri serves
    # the bundled UI from that host inside its own frame.
    _ALLOWED_HOSTS = {cfg.server.host, "127.0.0.1", "localhost", "tauri.localhost"}
    _LOOPBACK_ONLY = cfg.server.host in {"127.0.0.1", "localhost", "::1"}

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
        # A different port on the same host is a different application. That
        # matters when the server is reachable from outside — someone else's
        # service on this machine could then relay a request. While we are
        # bound to loopback only, every such origin is by definition a program
        # the user runs themselves, and requiring an exact port match would
        # lock out the settings window's own dev server (Vite on 5173) with no
        # security gained.
        if not _LOOPBACK_ONLY and request_host and ":" in request_host:
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
                "version": app_version(),
                "default_theme": cfg_now.default_theme,
                "pages": [p.model_dump() for p in cfg_now.pages],
                "modules": sorted(hub_now.modules.keys()),
            },
            headers=_NO_STORE,
        )

    @app.get("/api/snapshot")
    async def get_snapshot() -> JSONResponse:
        return JSONResponse(current_hub().snapshot(), headers=_NO_STORE)

    @app.get("/api/apps")
    async def get_apps() -> JSONResponse:
        """Installed desktop applications, for the 'launch program' button flow."""
        import anyio

        apps = await anyio.to_thread.run_sync(scan_desktop_apps)
        return JSONResponse({"apps": apps}, headers=_NO_STORE)

    @app.get("/api/apps/icon/{name}")
    async def get_app_icon(name: str) -> Response:
        """Serve a resolved application icon by name (index-restricted)."""
        if not _ICON_NAME_RE.match(name):
            raise HTTPException(status_code=404, detail="bad icon name")
        path = build_icon_index().get(name)
        if not path:
            raise HTTPException(status_code=404, detail="unknown icon")
        p = Path(path)
        if not p.is_file():
            raise HTTPException(status_code=404, detail="icon missing")
        mime = {
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".xpm": "image/x-xpixmap",
        }.get(p.suffix.lower(), "application/octet-stream")
        return FileResponse(p, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})

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

        `variants` carries the display variants each widget declares, so the
        editor can offer a list instead of a free-text field. Only widgets
        that declare any appear in it; an empty map is the normal case for a
        widget with a single look.
        """
        widgets_dir = FRONTEND_DIR / "js" / "widgets"
        if not widgets_dir.is_dir():
            return JSONResponse({"widgets": [], "variants": {}})
        files = sorted(
            (p for p in widgets_dir.glob("*.js") if not p.stem.startswith("_")),
            key=lambda p: p.stem,
        )
        variants = {}
        for path in files:
            declared = _widget_variants(path)
            if declared:
                variants[path.stem] = declared
        return JSONResponse({"widgets": [p.stem for p in files], "variants": variants})

    @app.get("/api/health")
    async def health() -> JSONResponse:
        """Liveness probe for the settings window's connection banner."""
        return JSONResponse(
            {"ok": True, "version": app_version(), "clients": current_hub().client_count},
            headers=_NO_STORE,
        )

    # Deliberately synchronous: `systemctl` is a subprocess. In an `async`
    # route it would block the event loop and with it the WebSocket the kiosk
    # feeds on, so FastAPI is left to run these in its threadpool.

    @app.get("/api/autostart")
    def get_autostart() -> JSONResponse:
        """Whether the dashboard starts itself at login."""
        return JSONResponse(autostart.status().as_dict(), headers=_NO_STORE)

    @app.post("/api/autostart")
    def set_autostart(payload: AutostartPayload) -> JSONResponse:
        """Body: `{enabled: bool}` — switches both user units together."""
        try:
            state = autostart.set_enabled(payload.enabled)
        except autostart.AutostartUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (autostart.AutostartError, OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(
                status_code=500, detail=f"autostart could not be switched: {exc}"
            ) from exc
        return JSONResponse(state.as_dict(), headers=_NO_STORE)

    @app.get("/api/settings")
    async def get_settings() -> JSONResponse:
        """Editable subset of the config (modules + default_theme + pages)."""
        return JSONResponse(_settings_view(current_cfg()), headers=_NO_STORE)

    @app.get("/api/modules/schema")
    async def get_modules_schema() -> JSONResponse:
        """Per-module editable-field schema that drives the Settings UI.

        Static for a given build, so the frontend fetches it once. Values live
        in ``/api/settings``; this only describes how to render the inputs.
        """
        return JSONResponse({"modules": _module_schemas()})

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

        # Secret fields left at the mask sentinel mean "unchanged" — drop them
        # so the deep-merge keeps the stored secret instead of writing "***".
        _strip_unchanged_secrets(body)

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
            _write_local_config(target, merged)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to write {target}: {exc}")

        # Hot-reload the hub so the change takes effect immediately.
        await current_hub().reload(new_cfg)
        app.state.config = new_cfg
        app.state.config_path = target
        logger.info(f"settings updated; persisted to {target}")
        view = _settings_view(new_cfg)
        # The editor is its own window now, so the change has to travel to the
        # kiosk on its own. Without this frame the display keeps rendering the
        # old theme and the old page layout until someone reloads it.
        await current_hub().publish("settings", settings=view)
        return JSONResponse({"ok": True, "settings": view}, headers=_NO_STORE)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # WebSockets bypass the http middleware *and* CORS, so re-apply the
        # origin check by hand. Cross-Site WebSocket Hijacking would otherwise
        # let a malicious tab subscribe to the data stream from the same
        # browser profile. The settings window passes this as `tauri.localhost`
        # (see _ALLOWED_HOSTS) — it needs the socket to know whether the
        # backend is alive and to hear about settings saved elsewhere.
        origin = ws.headers.get("origin")
        host = ws.headers.get("host")
        if not _origin_host_matches(origin, host):
            logger.warning(f"rejected ws connection from origin={origin!r}")
            await ws.close(code=1008)
            return
        await ws.accept()
        hub_now = current_hub()
        await hub_now.connect(ws)
        tray.update(clients=hub_now.client_count)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await hub_now.disconnect(ws)
            tray.update(clients=hub_now.client_count)

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
                "columns": int(dumped.get("columns", 4)),
                "rows": int(dumped.get("rows", 3)),
            },
            headers=_NO_STORE,
        )

    @app.post("/api/quick_actions/config")
    async def post_quick_actions_config(request: Request) -> JSONResponse:
        """Replace the quick_actions config (actions list + timeout)."""
        from .modules.quick_actions import QuickAction, _walk

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
            # Ids must be unique across the whole tree (folders included), since
            # run-by-id resolves against a flat index.
            for node in _walk([qa]):
                if node.id in seen_ids:
                    raise HTTPException(400, f"duplicate action id: {node.id!r}")
                seen_ids.add(node.id)
            validated_actions.append(qa.model_dump(by_alias=True, exclude_defaults=True))

        patch: dict[str, Any] = {"actions": validated_actions}
        if "timeout_seconds" in body:
            try:
                patch["timeout_seconds"] = float(body["timeout_seconds"])
            except (TypeError, ValueError):
                raise HTTPException(400, "timeout_seconds must be a number")
        for key in ("columns", "rows"):
            if key in body:
                try:
                    patch[key] = min(max(int(body[key]), 1), 8)
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{key} must be an integer")

        current_dict = current_cfg().model_dump()
        merged = _deep_merge(current_dict, {"modules": {"quick_actions": patch}})
        try:
            new_cfg = AppConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(400, f"validation failed: {_summarize_validation_error(exc)}")

        target = LOCAL_CONFIG
        try:
            _write_local_config(target, merged)
        except OSError as exc:
            raise HTTPException(500, f"failed to write {target}: {exc}")

        await current_hub().reload(new_cfg)
        app.state.config = new_cfg
        app.state.config_path = target
        logger.info(f"quick_actions config updated; persisted to {target}")
        await current_hub().publish("settings", settings=_settings_view(new_cfg))
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

    # Only the real server gets a tray icon; see the comment in create_app.
    # `setdefault` so `EDGE_TRAY=0` in the unit still wins.
    os.environ.setdefault("EDGE_TRAY", "1")

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
