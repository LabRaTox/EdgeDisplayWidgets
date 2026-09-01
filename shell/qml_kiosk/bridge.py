"""Everything QML needs from the outside: config, theme and live data.

The kiosk stays a display. It reads the same `config.local.yaml` the rest of
the system writes, subscribes to the backend's WebSocket, and hands both to
QML. No state of its own, nothing written back.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys

import theme as theme_module
import yaml
from PySide6.QtCore import (
    Property,
    QObject,
    QProcess,
    QProcessEnvironment,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtWebSockets import QWebSocket
from views import view_path

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPRITE = ROOT / "frontend" / "vendor" / "tabler" / "tabler-sprite.svg"
ICON_CACHE = pathlib.Path(
    os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache")
) / "edge-dashboard" / "icons"
#: Tabler names are lowercase kebab-case. Anything else is
#: not looked up, so a crafted name from the config cannot reach the disk.
SAFE_ICON = re.compile(r"^[a-z0-9-]+$")
SAFE_APP_ICON = re.compile(r"^[A-Za-z0-9._+-]+$")
THEMES_DIR = ROOT / "frontend" / "css" / "themes"
LOCALES_DIR = ROOT / "frontend" / "locales"


def _tracks(template: str) -> list[dict]:
    """A CSS grid template as stretch factors and fixed sizes.

    `32px 1fr 1fr` becomes one fixed row of 32 pixels and two sharing the
    rest, which is exactly what GridLayout needs. Covers every page in the
    real config; anything unrecognised falls back to an equal share.
    """
    out = []
    for token in template.split():
        px = re.fullmatch(r"(\d+(?:\.\d+)?)px", token)
        fr = re.fullmatch(r"(\d+(?:\.\d+)?)fr", token)
        minmax = re.fullmatch(r"minmax\([^,]+,\s*(\d+(?:\.\d+)?)fr\)", token)
        if px:
            out.append({"fixed": float(px.group(1)), "stretch": 0.0})
        elif fr:
            out.append({"fixed": 0.0, "stretch": float(fr.group(1))})
        elif minmax:
            out.append({"fixed": 0.0, "stretch": float(minmax.group(1))})
        else:
            out.append({"fixed": 0.0, "stretch": 1.0})
    return out or [{"fixed": 0.0, "stretch": 1.0}]


class Bridge(QObject):
    pagesChanged = Signal()
    themeChanged = Signal()
    onlineChanged = Signal()
    #: module name, payload. QML routes it to the widgets that asked for it.
    dataArrived = Signal(str, "QVariant")
    #: The video window has closed; whatever was paused for it may resume.
    videoClosed = Signal()

    def __init__(self, url: str | None = None) -> None:
        super().__init__()
        self._pages: list[dict] = []
        #: Last payload per module, so a widget mounting later is not blank.
        self._cache: dict = {}
        self._strings: dict = {}
        self._theme: dict = {}
        self._online = False
        self._retry_ms = 500
        #: The video player, while one is running, and the output it uses.
        self._player: QProcess | None = None
        self._output = ""
        self._sprite: str | None = None
        self._load_config()
        self._url = url or f"ws://127.0.0.1:{self._port}/ws"

        self._socket = QWebSocket()
        self._socket.textMessageReceived.connect(self._on_message)
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.errorOccurred.connect(lambda _: self._on_disconnected())
        self._connect()

    def set_output(self, name: str) -> None:
        """Which display the window ended up on; the video uses the same one."""
        self._output = name

    # -- configuration -----------------------------------------------------

    def _load_locale(self, language: str) -> None:
        """The display's texts, from the same files the settings window reads.

        Widget labels are translated from `frontend/locales/<code>.json`,
        the one place they live for both this window and the settings window,
        so a wording fixed there is fixed everywhere.
        """
        if language in ("", "auto"):
            language = (os.environ.get("LANG", "en") or "en")[:2].lower()
        path = LOCALES_DIR / f"{language}.json"
        if not path.is_file():
            path = LOCALES_DIR / "en.json"
        try:
            self._strings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._strings = {}

    @Slot(str, result=str)
    @Slot(str, str, result=str)
    def tr(self, key: str, fallback: str = "") -> str:
        """One translated string; the key itself if it is missing."""
        return self._strings.get(key, fallback or key)

    def _load_config(self) -> None:
        path = ROOT / "config.local.yaml"
        if not path.is_file():
            path = ROOT / "config.yaml"
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self._port = (cfg.get("server") or {}).get("port", 8765)
        name = cfg.get("default_theme", "clean")
        self._theme = theme_module.load(name, THEMES_DIR)
        self._metrics = theme_module.metrics(name, THEMES_DIR)
        self._effects = theme_module.effects(name, THEMES_DIR, self._theme)
        self._load_locale(cfg.get("default_language", "auto"))

        pages = []
        for page in cfg.get("pages", []):
            grid = page.get("grid") or {}
            pages.append({
                "id": page.get("id", ""),
                "title": page.get("title", page.get("id", "")),
                "columns": _tracks(grid.get("columns", "1fr")),
                "rows": _tracks(grid.get("rows", "1fr")),
                "widgets": [
                    {
                        "id": w.get("id", ""),
                        "col": int(w.get("col", 1) or 1),
                        "row": int(w.get("row", 1) or 1),
                        "colspan": int(w.get("colspan", 1) or 1),
                        "rowspan": int(w.get("rowspan", 1) or 1),
                        "variant": w.get("variant") or "",
                        "options": w.get("options") or {},
                    }
                    for w in page.get("widgets", [])
                ],
            })
        self._pages = pages

    def reload(self) -> None:
        """Re-read the config after the settings window saved it."""
        self._load_config()
        self.themeChanged.emit()
        self.pagesChanged.emit()

    @Property("QVariant", notify=pagesChanged)
    def pages(self):
        return self._pages

    @Property("QVariant", notify=themeChanged)
    def theme(self):
        return self._theme

    @Property("QVariant", notify=themeChanged)
    def metrics(self):
        """Sizes a theme sets outside its variables: inset, corner, type.

        A theme file is more than a palette. Clean gives every tile a
        different inset and a smaller, lighter figure; industrial squares the
        corners. Reading those few rules keeps a theme looking like itself.
        """
        return self._metrics

    @Property("QVariant", notify=themeChanged)
    def effects(self):
        """The decoration a theme puts on top of the layout.

        Glow around a tile, the scanline overlay, the cut corner in toxic.
        Kept apart from `metrics` because none of it moves anything: a widget
        looks the same with all of it switched off.
        """
        return self._effects

    @Slot(str, result=str)
    def viewUrl(self, widget_id: str) -> str:
        """The QML file that draws one widget, or "" when there is none.

        Found by name rather than by a table: `disk_usage` is `DiskUsage.qml`.
        A new widget therefore needs no entry anywhere in the window, the same
        way a new module needs no entry in the backend.

        Returning "" for a widget with no file of its own is deliberate. The
        window then shows its placeholder, which says whether the id is
        unknown or the tile has none at all, and that is more use than a
        loader failing with a missing file.
        """
        path = view_path(widget_id)
        return QUrl.fromLocalFile(str(path)).toString() if path else ""

    @Slot(str, str, result=str)
    def iconUrl(self, icon: str, colour: str) -> str:
        """A drawable file for one icon string, or "" for text and emoji.

        The settings window points an `<svg><use>` at a fragment of the sprite
        and lets CSS colour it. QML draws whole files, so the symbol is cut
        out of the sprite once, with the colour written in, and kept in the
        cache directory. `app:` icons come from the backend as before.
        """
        if not icon:
            return ""
        if icon.startswith("app:"):
            name = icon[4:]
            return f"{self.api}/api/apps/icon/{name}" if SAFE_APP_ICON.match(name) else ""
        if not icon.startswith("ti:"):
            return ""                              # emoji or plain text
        name = icon[3:]
        if not SAFE_ICON.match(name) or not SPRITE.is_file():
            return ""

        tint = colour or "#e0e0e0"
        target = ICON_CACHE / f"{name}-{tint.lstrip('#')}.svg"
        if not target.is_file():
            symbol = self._symbol(name)
            if symbol is None:
                return ""
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(symbol.replace("currentColor", tint), encoding="utf-8")
        return QUrl.fromLocalFile(str(target)).toString()

    def _symbol(self, name: str) -> str | None:
        """One `<symbol>` from the sprite, as a standalone SVG document."""
        if self._sprite is None:
            self._sprite = SPRITE.read_text(encoding="utf-8", errors="replace")
        start = self._sprite.find(f'<symbol id="tabler-{name}"')
        if start < 0:
            return None
        end = self._sprite.find("</symbol>", start)
        if end < 0:
            return None
        body = self._sprite[start:end]
        attributes, _, inner = body.partition(">")
        attributes = attributes.replace("<symbol", "<svg", 1)
        attributes = re.sub(r'\s*id="[^"]*"', "", attributes, count=1)
        return f'{attributes} xmlns="http://www.w3.org/2000/svg">{inner}</svg>'

    @Slot(str)
    def openVideo(self, url: str) -> None:
        """Play one video in a separate window, in a process of its own.

        The kiosk window has no web view in it. Rather than pulling one in
        in for the rare video, the player is started here and ends when the
        window is closed, so nothing of it stays behind.
        """
        if self._player is not None and self._player.state() != QProcess.NotRunning:
            return
        process = QProcess(self)
        process.finished.connect(self._on_player_finished)
        process.setProgram(sys.executable)
        process.setArguments([
            "-m", "qml_kiosk.player", "--url", url,
            *(["--output", self._output] if self._output else []),
        ])
        # The whole environment, not just our addition: an empty one has no
        # WAYLAND_DISPLAY in it and the player would find no display to open on.
        environment = QProcessEnvironment.systemEnvironment()
        existing = environment.value("PYTHONPATH", "")
        environment.insert("PYTHONPATH",
                           os.pathsep.join(filter(None, [str(ROOT / "shell"), existing])))
        process.setProcessEnvironment(environment)
        # Its errors belong in our log, not in the void.
        process.setProcessChannelMode(QProcess.ForwardedChannels)
        process.start()
        self._player = process

    def _on_player_finished(self, *_args) -> None:
        self._player = None
        self.videoClosed.emit()

    @Property(str, constant=True)
    def api(self):
        """Base address of the backend's REST endpoints.

        Notes, quick actions and the lights read and write over HTTP, the same
        routes the settings window calls. The WebSocket only carries the live
        module data.
        """
        return f"http://127.0.0.1:{self._port}"

    @Property(bool, notify=onlineChanged)
    def online(self):
        return self._online

    # -- live data ---------------------------------------------------------

    def _connect(self) -> None:
        self._socket.open(QUrl(self._url))

    def _on_connected(self) -> None:
        self._retry_ms = 500
        self._online = True
        self.onlineChanged.emit()

    def _on_disconnected(self) -> None:
        if self._online:
            self._online = False
            self.onlineChanged.emit()
        QTimer.singleShot(self._retry_ms, self._connect)
        self._retry_ms = min(self._retry_ms * 2, 5000)

    @Slot(str, result="QVariant")
    def cached(self, module: str):
        """Last payload of one module, for a widget that mounts later."""
        return self._cache.get(module)

    def _on_message(self, text: str) -> None:
        try:
            frame = json.loads(text)
        except ValueError:
            return
        if frame.get("event") == "settings":
            # The settings window saved; follow along without a restart.
            self.reload()
            return
        module = frame.get("module")
        if module:
            data = frame.get("data")
            self._cache[module] = data
            self.dataArrived.emit(module, data)

    @Slot(result=str)
    def summary(self) -> str:
        widgets = sum(len(p["widgets"]) for p in self._pages)
        return f"{len(self._pages)} Seiten, {widgets} Widgets"
