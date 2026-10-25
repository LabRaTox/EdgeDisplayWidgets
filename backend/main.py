"""FastAPI entrypoint: lifespan-managed Hub, WebSocket and the REST API."""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
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

from . import autostart, plugin_layout, plugins, store
from .config import AppConfig, ModuleConfig, load_config
from .hub import Hub
from .joplin import JoplinError
from .modules.base import SettingField, get_registry
from .notes import MAX_BODY_LEN, MAX_TITLE_LEN, NotesStore, public_view
from .tray import SystemTray

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
LOCAL_CONFIG = ROOT / "config.local.yaml"
FRONTEND_DIR = ROOT / "frontend"
#: One manifest per widget; the file being here is the registration.
WIDGETS_DIR = ROOT / "widgets"


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
    """StaticFiles that forces the client to revalidate every request.

    Without an explicit Cache-Control header Chromium applies "heuristic
    freshness" (based on Last-Modified) and reuses cached files across
    restarts, so a replaced asset can keep serving its old version. `no-cache`
    keeps the cache but requires a revalidation each time; with the ETag we
    already emit that is a cheap 304 when nothing has changed.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


class AutostartPayload(BaseModel):
    enabled: bool


class InstallPayload(BaseModel):
    slug: str
    version: str = ""


class DevicePollPayload(BaseModel):
    device_code: str


class RatingPayload(BaseModel):
    value: int
    comment: str = ""


class SubmitPayload(BaseModel):
    #: A folder on this machine holding the widget's manifest.json.
    path: str


#: Images a plugin may show: its icon and its screenshots.
_IMAGE_SUFFIXES = {".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif"}

#: Headers for a plugin's images. An SVG is a document when opened on its
#: own, and it would run on this origin, which the origin guard trusts; the
#: sandbox keeps any script in it from running. An <img> is not affected.
_IMAGE_HEADERS = {"Cache-Control": "public, max-age=86400",
                  "Content-Security-Policy": "sandbox"}

#: What the store accepts as a version number.
_VERSION = re.compile(r"\d+(\.\d+){0,3}([.-][0-9a-zA-Z]+)?")



def _widget_manifest(path: Path) -> dict[str, Any]:
    """One widget's manifest, or an empty one when it cannot be read.

    A widget is registered by having a file here at all; what it declares
    inside is optional. `variants` and `options` are handed to the layout
    editor. `modules` is not: it records which backend modules the widget
    consumes, which the kiosk decides for itself in the view's `moduleNames`.
    It is here so the two can be checked against each other and against the
    table in the README, which tests/test_docs_match_code.py does.

    A malformed manifest is a warning and not a failure: one bad file costs
    that widget its variants and options, and it still appears in the picker,
    rather than taking the whole picker down with it.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"ignoring {path.name}: {exc}")
        return {}
    if not isinstance(data, dict):
        logger.warning(f"ignoring {path.name}: expected an object")
        return {}
    return data


def _manifest_options(path: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """The `options` block of a manifest, validated against SettingField.

    Validated here rather than trusted, because the editor renders one input
    per field and a type it does not know renders as nothing at all.
    """
    fields = manifest.get("options")
    if not fields:
        return []
    if not isinstance(fields, list):
        logger.warning(f"ignoring options in {path.name}: expected a list of fields")
        return []
    try:
        return [SettingField.model_validate(f).model_dump() for f in fields]
    except Exception as exc:
        logger.warning(f"ignoring options in {path.name}: {_summarize_validation_error(exc)}")
        return []


def _module_choices(hub: Any, module: str) -> tuple[list[str], list[str]]:
    """The choices a module offers in its last answer, under `choices`.

    For widgets whose list of values only the module knows, such as the
    providers an AI-usage module currently reports. Each entry is
    `{"value": …, "label": …}`. The list starts with an empty entry, so the
    field can be cleared, the same as the sensor list.
    """
    frame = hub.snapshot().get(module) or {}
    data = frame.get("data") or {}
    values, labels = [""], [""]
    for entry in data.get("choices") or []:
        if isinstance(entry, dict) and entry.get("value"):
            values.append(str(entry["value"]))
            labels.append(str(entry.get("label") or entry["value"]))
    return values, labels


def _sensor_choices(hub: Any) -> tuple[list[str], list[str]]:
    """The sensor ids currently reported, and a readable name for each.

    An id (`k10temp@0000:00:18.3:1`) names the chip and the address it sits at,
    so it points at the same reading after a reboot and can never resolve to a
    different sensor. Readable it is not, hence the second list.

    An empty first entry lets a field be cleared, which is how the second
    sensor is left unset.
    """
    frame = hub.snapshot().get("sensors") or {}
    data = frame.get("data") or {}
    if data.get("available") is not True:
        return [""], [""]
    ids, labels = [""], [""]
    for reading in data.get("readings") or []:
        chip = str(reading.get("display_chip") or reading.get("chip") or "")
        label = str(reading.get("display_label") or reading.get("label") or "")
        ids.append(str(reading.get("id", "")))
        labels.append(f"{chip} {label}".strip() or str(reading.get("id", "")))
    return ids, labels


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


def _add_new_modules(cfg: AppConfig, cfg_path: Path) -> AppConfig:
    """Modules the template knows and the loaded config does not mention.

    `config.local.yaml` replaces the template rather than extending it, so a
    module added in a later version would never run for anyone who saved
    settings before. Its block is taken from the template instead, with the
    template's defaults. A module the local file mentions at all, even as
    `enabled: false`, stays as it is there; the next save writes the taken
    blocks into the local file like any other.
    """
    # Only for the local file: an explicit config ($EDGE_CONFIG, the tests)
    # means exactly what it says, and the template needs no filling in.
    if cfg_path.resolve() != LOCAL_CONFIG.resolve() or not DEFAULT_CONFIG.is_file():
        return cfg
    try:
        template = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(f"could not read {DEFAULT_CONFIG.name} for new modules: {exc}")
        return cfg
    added = []
    for name, block in (template.get("modules") or {}).items():
        if name in cfg.modules or not isinstance(block, dict):
            continue
        try:
            cfg.modules[name] = ModuleConfig.model_validate(block)
        except Exception as exc:
            logger.warning(f"template block for module '{name}' is invalid: {exc}")
            continue
        added.append(name)
    if added:
        logger.info(f"modules from the template, not yet in {cfg_path.name}: {sorted(added)}")
    return cfg


def create_app(config_path: str | Path | None = None) -> FastAPI:
    cfg_path = resolve_config_path(config_path)
    cfg = _add_new_modules(load_config(cfg_path), Path(cfg_path))
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

    def _builtin_themes() -> list[str]:
        themes_dir = FRONTEND_DIR / "css" / "themes"
        if not themes_dir.is_dir():
            return []
        return sorted(p.stem for p in themes_dir.glob("*.css") if not p.stem.startswith("_"))

    @app.get("/api/themes")
    async def get_themes() -> JSONResponse:
        """The built-in themes and the installed ones, in that order.

        `meta` names each one and says where it comes from, so the design
        page and the plugin page can label an installed theme by its
        manifest rather than by its id.
        """
        cfg_now = current_cfg()
        builtin = _builtin_themes()
        meta: dict[str, dict[str, Any]] = {
            name: {"name": name, "summary": "", "builtin": True, "version": app_version(),
                   "author": "Edge Dash", "license": "MIT", "description": "", "changelog": "",
                   "support": "", "screenshots": 0, "icon_url": ""}
            for name in builtin
        }
        installed_names = []
        for plugin in plugin_layout.installed("theme"):
            if plugin.id in meta:
                continue
            installed_names.append(plugin.id)
            meta[plugin.id] = {
                "name": plugin.manifest.get("name") or plugin.id,
                "summary": plugin.manifest.get("summary") or plugin.manifest.get("description") or "",
                "builtin": False,
                "version": plugin.version,
                "author": plugin.install.get("author", ""),
                "license": plugin.manifest.get("license") or "",
                "source": plugin.install.get("source", "store"),
                "description": plugin.manifest.get("description") or "",
                "changelog": plugin.manifest.get("changelog") or "",
                "support": plugin.manifest.get("support") or "",
                "screenshots": len(plugin.manifest.get("screenshots") or []),
                "icon_url": f"/api/plugins/{plugin.id}/icon?v={plugin.version}"
                            if plugin_layout.inside(plugin.path, plugin.manifest.get("icon")) else "",
            }
        return JSONResponse({"themes": builtin + installed_names, "default": cfg_now.default_theme,
                             "meta": meta}, headers=_NO_STORE)

    @app.get("/css/themes/{name}.css")
    async def get_theme_css(name: str) -> Response:
        """One theme's stylesheet, for the previews in the settings window.

        Built-in themes come from `frontend/css/themes/`, installed ones from
        their folder. The name is checked first: it ends up in a path.
        """
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", name):
            raise HTTPException(status_code=404, detail="unknown theme")
        path = FRONTEND_DIR / "css" / "themes" / f"{name}.css"
        if not path.is_file():
            plugin = plugin_layout.load(name)
            css = plugin.css_file if plugin is not None else None
            if css is None:
                raise HTTPException(status_code=404, detail="unknown theme")
            path = css
        return FileResponse(path, media_type="text/css", headers={"Cache-Control": "no-cache"})

    @app.get("/api/widgets")
    async def get_widgets() -> JSONResponse:
        """List the widgets declared in widgets/.

        Used by the Layout-Editor to populate the 'add widget' picker. Drop
        a new ``<name>.json`` and it appears here.

        `variants` carries the display variants each widget declares, so the
        editor can offer a list instead of a free-text field, and `options`
        its editable settings. Only widgets that declare either appear in the
        respective map; both being empty is the normal case.
        """
        files = sorted(
            (p for p in WIDGETS_DIR.glob("*.json") if not p.stem.startswith("_")),
            key=lambda p: p.stem,
        ) if WIDGETS_DIR.is_dir() else []
        manifests = [(p.stem, p, _widget_manifest(p)) for p in files]
        # Installed widgets come after the built-in ones. An id that both
        # have cannot happen through the store, which reserves the built-in
        # names; a folder copied in by hand loses to the built-in.
        builtin = {wid for wid, _, _ in manifests}
        installed_plugins: dict[str, plugin_layout.Plugin] = {}
        for plugin in plugin_layout.installed("widget"):
            if plugin.id in builtin or plugin.id.replace("-", "_") in builtin:
                continue
            installed_plugins[plugin.id] = plugin
            manifests.append((plugin.id, plugin.path / "manifest.json", plugin.manifest))
        installed_ids = list(installed_plugins)

        variants: dict[str, list[str]] = {}
        options: dict[str, list[dict[str, Any]]] = {}
        meta: dict[str, dict[str, Any]] = {}
        for wid, path, manifest in manifests:
            meta[wid] = _widget_meta(wid, manifest, installed_plugins.get(wid))
            if manifest.get("variants"):
                variants[wid] = manifest["variants"]
            fields = _manifest_options(path, manifest)
            if fields:
                options[wid] = fields

        # The choices a field defers to the server are filled in here, so the
        # editor never has to know where a list like this comes from.
        ids, labels = _sensor_choices(current_hub())
        for fields in options.values():
            for field in fields:
                source = field.get("options_source")
                if source == "sensors":
                    field["options"] = ids
                    field["option_labels"] = labels
                elif source:
                    values, names = _module_choices(current_hub(), source)
                    field["options"] = values
                    field["option_labels"] = names

        return JSONResponse({"widgets": [wid for wid, _, _ in manifests],
                             "installed": installed_ids, "meta": meta,
                             "variants": variants, "options": options})

    def _widget_meta(wid: str, manifest: dict[str, Any],
                     plugin: plugin_layout.Plugin | None) -> dict[str, Any]:
        """What the widget page shows on a card, the same for both kinds.

        `name` and `summary` stay as the manifest has them, one string or one
        per language; the window picks its language. `symbol` is a Tabler
        name (`ti:cpu`), `icon` an image in an installed widget's folder.
        `plugin` is the installed widget, None for a built-in one.
        """
        builtin = plugin is None
        modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
        entry: dict[str, Any] = {
            "name": manifest.get("name") or wid,
            "summary": manifest.get("summary") or manifest.get("description") or "",
            "category": str(manifest.get("category") or "other"),
            "accent": manifest.get("accent") if isinstance(manifest.get("accent"), str) else "",
            "symbol": manifest.get("symbol") if isinstance(manifest.get("symbol"), str) else "",
            "modules": [m for m in modules if isinstance(m, str)],
            "builtin": builtin,
            "version": app_version() if builtin else str(manifest.get("version", "")),
            "license": manifest.get("license") or ("MIT" if builtin else ""),
            "description": manifest.get("description") or manifest.get("summary") or "",
            "changelog": manifest.get("changelog") or "",
            "support": manifest.get("support") if isinstance(manifest.get("support"), str) else "",
            "author": manifest.get("author") or ("Edge Dash" if builtin else ""),
            "screenshots": 0,
            "icon_url": "",
        }
        if plugin is not None:
            entry["author"] = plugin.install.get("author") or entry["author"]
            entry["source"] = plugin.install.get("source", "store")
            shots = manifest.get("screenshots")
            entry["screenshots"] = len(shots) if isinstance(shots, list) else 0
            entry["warnings"] = plugin.install.get("warnings", [])
            if plugin_layout.inside(plugin.path, manifest.get("icon")) is not None:
                entry["icon_url"] = f"/api/plugins/{wid}/icon?v={plugin.version}"
        return entry

    @app.get("/locales/{code}.json")
    async def get_locale(code: str) -> JSONResponse:
        """The dashboard's texts for one language, with those of installed widgets.

        The settings window labels module fields and widget options from
        these keys. A widget's own file can only add keys in its own space,
        see `plugin_layout.Plugin.locale`.
        """
        if not re.fullmatch(r"[a-z]{2}", code):
            raise HTTPException(status_code=404, detail="unknown language")
        path = FRONTEND_DIR / "locales" / f"{code}.json"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="unknown language")
        try:
            strings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=f"{path.name}: {exc}") from exc
        merged = {**plugin_layout.locale(code), **strings}
        return JSONResponse(merged, headers=_NO_STORE)

    # ----------------------------------------------------------- the store
    #
    # The settings window talks to the store through these routes rather than
    # directly: the backend holds the token, does the unpacking and has to
    # load the new module anyway. Paths carry ids and versions into URLs on
    # the store, so both are checked against the store's own rules first.

    def _check_id(slug: str) -> str:
        if not plugin_layout.SAFE_ID.match(slug):
            raise HTTPException(status_code=422, detail=f"invalid id {slug!r}")
        return slug

    def _check_version(version: str) -> str:
        if not _VERSION.fullmatch(version) or len(version) > 32:
            raise HTTPException(status_code=422, detail=f"invalid version {version!r}")
        return version

    def _store_failed(exc: store.StoreError) -> HTTPException:
        # The store's 4xx answers are meant for the user and keep their code;
        # everything else is the store being away, which is a 502 here.
        code = exc.status if exc.status and 400 <= exc.status < 500 else 502
        return HTTPException(status_code=code, detail=str(exc))

    def _installed_view(plugin: plugin_layout.Plugin) -> dict[str, Any]:
        return {
            "id": plugin.id,
            "type": plugin.type,
            "version": plugin.version,
            "name": plugin.manifest.get("name") or plugin.id,
            "summary": plugin.manifest.get("summary") or plugin.manifest.get("description") or "",
            "modules": plugin.modules,
            "author": plugin.install.get("author", ""),
            "warnings": plugin.install.get("warnings", []),
            "installed_at": plugin.install.get("installed_at"),
        }

    async def _after_plugin_change(names: list[str]) -> None:
        """Switch on new modules, or at least reload, and tell the kiosk."""
        configured = current_cfg().modules
        switch_on = {n: {"enabled": True} for n in names if n not in configured}
        if switch_on:
            await apply_settings({"modules": switch_on})
        else:
            # A new view or new texts still have to reach the kiosk.
            await current_hub().reload(current_cfg())
            await current_hub().publish("settings", settings=_settings_view(current_cfg()))

    def _install_local(data: bytes) -> tuple[plugin_layout.Plugin, list[str]]:
        """Install an archive from this machine: no store, so no checksum to
        compare with. The unpacking rules are the same as for the store."""
        try:
            plugin = plugins.install_archive(
                data,
                sha256=hashlib.sha256(data).hexdigest(),
                expected_id="",
                app_version=app_version(),
                meta={"source": "local"},
            )
            return plugin, plugins.load_module(plugin)
        except plugins.PluginError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception(f"local widget installed, its module failed: {exc}")
            raise HTTPException(status_code=422,
                                detail=f"installed, but its module failed to load: {exc}") from exc

    @app.post("/api/plugins/upload")
    async def install_upload(request: Request) -> JSONResponse:
        """Install a widget from a zip the window sends as the request body."""
        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="no archive in the request")
        if len(data) > plugins.MAX_ARCHIVE_BYTES:
            raise HTTPException(status_code=413, detail="archive is larger than 64 MB")
        plugin, names = _install_local(data)
        await _after_plugin_change(names)
        return JSONResponse({"ok": True, "plugin": _installed_view(plugin), "modules": names},
                            headers=_NO_STORE)

    @app.post("/api/plugins/folder")
    async def install_folder(payload: SubmitPayload) -> JSONResponse:
        """Install a widget from a folder on this machine, packed the way the
        store would get it. Meant for trying a widget before submitting it."""
        try:
            data = store.pack(Path(payload.path))
        except store.StoreError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=f"cannot read {payload.path}: {exc}") from exc
        plugin, names = _install_local(data)
        await _after_plugin_change(names)
        return JSONResponse({"ok": True, "plugin": _installed_view(plugin), "modules": names},
                            headers=_NO_STORE)

    @app.post("/api/plugins/rescan")
    async def rescan_plugins() -> JSONResponse:
        """Look at the plugins folder again: load what is new, drop what left."""
        present = {p.id for p in plugin_layout.installed()}
        for gone in set(plugins._LOADED) - present:
            plugins.unload_module(gone)
        names: list[str] = []
        new: list[str] = []
        for plugin in plugin_layout.installed():
            if plugin.id in plugins._LOADED:
                continue
            new.append(plugin.id)
            try:
                names += plugins.load_module(plugin)
            except Exception as exc:
                logger.exception(f"failed to load widget '{plugin.id}': {exc}")
        await _after_plugin_change(names)
        return JSONResponse({"ok": True, "new": new}, headers=_NO_STORE)

    def _plugin_image(plugin_id: str, relative: object) -> Response:
        """An image the manifest names, from inside the plugin's folder."""
        plugin = plugin_layout.load(_check_id(plugin_id))
        path = plugin_layout.inside(plugin.path, relative) if plugin else None
        if path is None or path.suffix.lower() not in _IMAGE_SUFFIXES:
            raise HTTPException(status_code=404, detail="no such image")
        return FileResponse(path, headers=_IMAGE_HEADERS)

    @app.get("/api/plugins/{plugin_id}/icon")
    async def plugin_icon(plugin_id: str) -> Response:
        plugin = plugin_layout.load(_check_id(plugin_id))
        return _plugin_image(plugin_id, plugin.manifest.get("icon") if plugin else None)

    @app.get("/api/plugins/{plugin_id}/screenshot/{index}")
    async def plugin_screenshot(plugin_id: str, index: int) -> Response:
        """A screenshot by its position in the manifest, not by its path:
        the window never names a file inside a plugin's folder."""
        plugin = plugin_layout.load(_check_id(plugin_id))
        shots = plugin.manifest.get("screenshots") if plugin else None
        if not isinstance(shots, list) or not 0 <= index < len(shots):
            raise HTTPException(status_code=404, detail="no such screenshot")
        return _plugin_image(plugin_id, shots[index])

    async def _store_image(slug: str, version: str, pick) -> Response:
        try:
            detail = await store.plugin(_check_id(slug))
        except store.StoreError as exc:
            raise _store_failed(exc) from exc
        versions = detail.get("versions") or [detail.get("latest") or {}]
        entry = next((v for v in versions if v.get("version") == _check_version(version)), None)
        url = pick(entry) if entry else None
        if not url:
            raise HTTPException(status_code=404, detail="no such image")
        try:
            data, kind = await store.image(url)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc
        return Response(data, media_type=kind, headers=_IMAGE_HEADERS)

    @app.get("/api/store/plugins/{slug}/{version}/icon")
    async def store_icon(slug: str, version: str) -> Response:
        return await _store_image(slug, version, lambda v: v.get("icon_url"))

    @app.get("/api/store/plugins/{slug}/{version}/screenshot/{index}")
    async def store_screenshot(slug: str, version: str, index: int) -> Response:
        def pick(v: dict[str, Any]) -> str | None:
            shots = v.get("screenshot_urls") or []
            return shots[index] if 0 <= index < len(shots) else None
        return await _store_image(slug, version, pick)

    @app.get("/api/plugins")
    async def get_installed() -> JSONResponse:
        """Every widget installed from the store."""
        return JSONResponse({"plugins": [_installed_view(p) for p in plugin_layout.installed()]},
                            headers=_NO_STORE)

    @app.get("/api/store/catalog")
    async def store_catalog(q: str = "") -> JSONResponse:
        """The store's widgets, each with what is installed here."""
        try:
            answer = await store.catalog(q[:100])
        except store.StoreError as exc:
            raise _store_failed(exc) from exc
        here = {p.id: p.version for p in plugin_layout.installed()}
        running = app_version()
        for entry in answer.get("plugins", []):
            latest = entry.get("latest") or {}
            current = here.get(entry.get("slug", ""))
            needed = latest.get("min_app_version") or ""
            entry["installed_version"] = current
            entry["update"] = bool(current and plugins.newer(latest.get("version", ""), current))
            entry["compatible"] = not needed or not plugins.newer(needed, running)
        return JSONResponse(answer, headers=_NO_STORE)

    @app.get("/api/store/plugins/{slug}")
    async def store_plugin(slug: str) -> JSONResponse:
        try:
            return JSONResponse(await store.plugin(_check_id(slug)), headers=_NO_STORE)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc

    @app.post("/api/store/install")
    async def store_install(payload: InstallPayload) -> JSONResponse:
        """Install or update one widget: download, verify, unpack, load.

        Without `version` the newest released one. Its modules are switched
        on in the config if they are not there yet, so the widget shows data
        as soon as it is placed. Placing it stays with the layout editor.
        """
        slug = _check_id(payload.slug)
        try:
            detail = await store.plugin(slug)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc
        versions = detail.get("versions") or [detail.get("latest") or {}]
        wanted = payload.version or (detail.get("latest") or {}).get("version")
        chosen = next((v for v in versions if v.get("version") == wanted), None)
        if chosen is None or chosen.get("state", "approved") != "approved":
            raise HTTPException(status_code=404, detail=f"'{slug}' {wanted} is not available")

        try:
            data = await store.download(str(chosen.get("download_url", "")))
            plugin = plugins.install_archive(
                data,
                sha256=str(chosen.get("sha256", "")),
                expected_id=slug,
                app_version=app_version(),
                meta={"author": detail.get("author", ""), "warnings": chosen.get("warnings", [])},
            )
            names = plugins.load_module(plugin)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc
        except plugins.PluginError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            # The files are in place but the module would not import. Leave
            # them, so the author's error is in the log and a fixed version
            # can replace them, but say so.
            logger.exception(f"widget '{slug}' installed, its module failed: {exc}")
            raise HTTPException(status_code=422,
                                detail=f"installed, but its module failed to load: {exc}") from exc

        await _after_plugin_change(names)
        return JSONResponse({"ok": True, "plugin": _installed_view(plugin), "modules": names},
                            headers=_NO_STORE)

    @app.delete("/api/plugins/{plugin_id}")
    async def remove_plugin(plugin_id: str) -> JSONResponse:
        """Remove an installed widget.

        Its module blocks and placements stay in the config: installing it
        again finds its settings where they were, and a placed tile says that
        the widget is missing instead of disappearing without a word.
        """
        try:
            plugins.uninstall(_check_id(plugin_id))
        except plugins.PluginError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if current_cfg().default_theme == plugin_id:
            # The display would otherwise fall back to bare defaults, which
            # looks broken rather than chosen.
            await apply_settings({"default_theme": "clean"})
            return JSONResponse({"ok": True, "theme": "clean"}, headers=_NO_STORE)
        await current_hub().reload(current_cfg())
        await current_hub().publish("settings", settings=_settings_view(current_cfg()))
        return JSONResponse({"ok": True}, headers=_NO_STORE)

    @app.get("/api/store/plugins/{slug}/rating")
    async def store_rating(slug: str) -> JSONResponse:
        try:
            return JSONResponse(await store.rating(_check_id(slug)), headers=_NO_STORE)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc

    @app.put("/api/store/plugins/{slug}/rating")
    async def store_rate(slug: str, payload: RatingPayload) -> JSONResponse:
        try:
            answer = await store.rate(_check_id(slug), payload.value, payload.comment[:500])
        except store.StoreError as exc:
            raise _store_failed(exc) from exc
        return JSONResponse(answer, headers=_NO_STORE)

    @app.delete("/api/store/plugins/{slug}/rating")
    async def store_unrate(slug: str) -> JSONResponse:
        try:
            return JSONResponse(await store.unrate(_check_id(slug)), headers=_NO_STORE)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc

    @app.post("/api/store/auth/device")
    async def store_device_start() -> JSONResponse:
        try:
            return JSONResponse(await store.device_start(), headers=_NO_STORE)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc

    @app.post("/api/store/auth/poll")
    async def store_device_poll(payload: DevicePollPayload) -> JSONResponse:
        try:
            return JSONResponse(await store.device_poll(payload.device_code), headers=_NO_STORE)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc

    @app.get("/api/store/me")
    async def store_me() -> JSONResponse:
        try:
            return JSONResponse({"user": await store.me()}, headers=_NO_STORE)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc

    @app.get("/api/store/pending")
    async def store_pending() -> JSONResponse:
        """Submissions and reports waiting for review, for those who review.

        A store that cannot be reached is no reason for an error here: the
        notice is a convenience, and the page works without it.
        """
        try:
            waiting = await store.pending()
        except store.StoreError:
            waiting = None
        return JSONResponse({"pending": waiting}, headers=_NO_STORE)

    @app.post("/api/store/logout")
    async def store_logout() -> JSONResponse:
        await store.logout()
        return JSONResponse({"ok": True}, headers=_NO_STORE)

    @app.get("/api/store/slugs/{slug}")
    async def store_check_slug(slug: str) -> JSONResponse:
        try:
            return JSONResponse(await store.check_slug(_check_id(slug)), headers=_NO_STORE)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc

    @app.post("/api/store/upload-archive")
    async def store_upload_archive(request: Request) -> JSONResponse:
        """Submit a finished archive the window sends as the request body.

        The file name travels in `X-Filename`, so the store can tell a
        tar.gz from a ZIP by its name as well as by its bytes.
        """
        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="no archive in the request")
        if len(data) > plugins.MAX_ARCHIVE_BYTES:
            raise HTTPException(status_code=413, detail="archive is larger than 64 MB")
        try:
            answer = await store.upload(data, request.headers.get("x-filename", "plugin.zip"))
        except store.StoreError as exc:
            raise _store_failed(exc) from exc
        return JSONResponse(answer, status_code=201, headers=_NO_STORE)

    @app.get("/api/store/mine")
    async def store_mine() -> JSONResponse:
        try:
            return JSONResponse(await store.my_plugins(), headers=_NO_STORE)
        except store.StoreError as exc:
            raise _store_failed(exc) from exc

    @app.delete("/api/store/mine/{slug}/{version}")
    async def store_withdraw(slug: str, version: str) -> JSONResponse:
        try:
            answer = await store.withdraw(_check_id(slug), _check_version(version))
        except store.StoreError as exc:
            raise _store_failed(exc) from exc
        return JSONResponse(answer, headers=_NO_STORE)

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
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="expected an object")

        # Secret fields left at the mask sentinel mean "unchanged" — drop them
        # so the deep-merge keeps the stored secret instead of writing "***".
        _strip_unchanged_secrets(body)
        view = await apply_settings(body)
        return JSONResponse({"ok": True, "settings": view}, headers=_NO_STORE)

    async def apply_settings(body: dict[str, Any]) -> dict[str, Any]:
        """Merge, validate, persist, reload, tell the kiosk. Returns the new view.

        Shared by the settings endpoint and the store, which switches on the
        modules of a widget it just installed.
        """
        current_dict = current_cfg().model_dump()
        merged = _deep_merge(current_dict, body)
        try:
            new_cfg = AppConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"validation failed: {_summarize_validation_error(exc)}") from exc

        # Persist to config.local.yaml so the change survives restarts.
        target = LOCAL_CONFIG
        try:
            _write_local_config(target, merged)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to write {target}: {exc}") from exc

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
        return view

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
            raise HTTPException(400, f"invalid JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(400, "expected an object")
        action = str(body.get("action", ""))
        value = body.get("value")
        result = await mod.control(device_id, action, value)
        status = 200 if result.get("ok") else 400
        return JSONResponse(result, status_code=status, headers=_NO_STORE)

    @app.post("/api/modules/{name}/command/{action}")
    async def module_command(name: str, action: str, request: Request) -> JSONResponse:
        """Hand a widget's command to its module. Body: the command's arguments.

        The way an installed widget talks back to its own module, without a
        route of its own. Which actions exist is the module's business; one
        it does not know is a 404, like a module that is not running.
        """
        mod = current_hub().modules.get(name)
        if mod is None:
            raise HTTPException(404, f"module {name} not active")
        try:
            body = await request.json() if await request.body() else {}
        except Exception as exc:
            raise HTTPException(400, f"invalid JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(400, "expected an object")
        try:
            result = await mod.command(action, body)
        except NotImplementedError:
            raise HTTPException(404, f"module {name} has no command {action}") from None
        if not isinstance(result, dict):
            # The contract is an object; an installed module that returns
            # something else should say so instead of crashing the route.
            raise HTTPException(500, f"module {name} answered {type(result).__name__}, not an object")
        status = 400 if result.get("ok") is False else 200
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
            raise HTTPException(400, f"invalid JSON: {exc}") from exc
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
                raise HTTPException(400, f"action #{i + 1}: {_summarize_validation_error(exc)}") from exc
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
                raise HTTPException(400, "timeout_seconds must be a number") from None
        for key in ("columns", "rows"):
            if key in body:
                try:
                    patch[key] = min(max(int(body[key]), 1), 8)
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{key} must be an integer") from None

        current_dict = current_cfg().model_dump()
        merged = _deep_merge(current_dict, {"modules": {"quick_actions": patch}})
        try:
            new_cfg = AppConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(400, f"validation failed: {_summarize_validation_error(exc)}") from exc

        target = LOCAL_CONFIG
        try:
            _write_local_config(target, merged)
        except OSError as exc:
            raise HTTPException(500, f"failed to write {target}: {exc}") from exc

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

    local_notes = NotesStore()

    def _notes_module() -> Any:
        return current_hub().modules.get("notes")

    def _notes_store() -> Any:
        """The store the notes module chose (a file or Joplin); without the
        module, the local file."""
        mod = _notes_module()
        return mod.store if mod is not None else local_notes

    async def _notes_call(method: str, *args: Any, write: bool = False, **kwargs: Any) -> Any:
        """Call the store, local or Joplin, and turn Joplin's trouble into a
        503 the widget can name ("joplin_offline", "joplin_auth", ...)."""
        try:
            result = getattr(_notes_store(), method)(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except JoplinError as exc:
            raise HTTPException(status_code=503, detail=f"joplin_{exc.key}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if write and (mod := _notes_module()) is not None:
            mod.changed()
        return result

    @app.get("/api/notes")
    async def get_notes() -> JSONResponse:
        notes, folders = await _notes_call("contents")
        mod = _notes_module()
        view = public_view(notes, folders)
        view["storage"] = mod.storage if mod is not None else "local"
        return JSONResponse(view, headers=_NO_STORE)

    @app.post("/api/notes")
    async def post_note(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="expected an object")
        title = str(body.get("title", ""))[:MAX_TITLE_LEN]
        text = str(body.get("body", ""))[:MAX_BODY_LEN]
        note_id = body.get("id")
        note_id = str(note_id) if note_id else None
        folder = str(body["folder"]) if "folder" in body and body["folder"] is not None else None
        pinned = bool(body["pinned"]) if "pinned" in body else None
        note = await _notes_call("upsert", title=title, body=text, note_id=note_id,
                                 folder=folder, pinned=pinned, write=True)
        return JSONResponse(note.model_dump(), headers=_NO_STORE)

    async def _folder_name(request: Request) -> str:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
        name = str(body.get("name", "")).strip() if isinstance(body, dict) else ""
        if not name:
            raise HTTPException(status_code=400, detail="a folder needs a name")
        return name

    @app.post("/api/notes/folders")
    async def post_folder(request: Request) -> JSONResponse:
        folder = await _notes_call("add_folder", await _folder_name(request), write=True)
        return JSONResponse(folder.model_dump(), headers=_NO_STORE)

    @app.post("/api/notes/folders/{folder_id}")
    async def rename_folder(folder_id: str, request: Request) -> JSONResponse:
        folder = await _notes_call("rename_folder", folder_id, await _folder_name(request), write=True)
        if folder is None:
            raise HTTPException(status_code=404, detail="folder not found")
        return JSONResponse(folder.model_dump(), headers=_NO_STORE)

    @app.delete("/api/notes/folders/{folder_id}")
    async def delete_folder(folder_id: str) -> JSONResponse:
        if not await _notes_call("delete_folder", folder_id, write=True):
            raise HTTPException(status_code=404, detail="folder not found")
        return JSONResponse({"ok": True}, headers=_NO_STORE)

    @app.delete("/api/notes/{note_id}")
    async def delete_note(note_id: str) -> JSONResponse:
        if not await _notes_call("delete", note_id, write=True):
            raise HTTPException(status_code=404, detail="note not found")
        return JSONResponse({"ok": True}, headers=_NO_STORE)

    """
    What is served over HTTP as a file rather than through the API.

    Two things ask for one: the kiosk opens `player.html` in its video window,
    and the settings window fetches the emoji data set from `vendor/`. Nothing
    else is exposed, so `/` is a 404.
    """
    vendor_dir = FRONTEND_DIR / "vendor"
    if vendor_dir.is_dir():
        app.mount("/vendor", _RevalidatingStaticFiles(directory=str(vendor_dir)),
                  name="vendor")
    else:
        logger.warning(f"vendor directory not found at {vendor_dir} — icons unavailable")

    @app.get("/player.html")
    async def player_page() -> Response:
        """The page the kiosk's video window loads.

        It embeds the player itself; pointing the window straight at the embed
        fails, because the player wants an origin to sit on.
        """
        path = FRONTEND_DIR / "player.html"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="player.html not found")
        return FileResponse(path, media_type="text/html",
                            headers={"Cache-Control": "no-cache"})

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
