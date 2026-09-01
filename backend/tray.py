"""Icon in the system tray.

Shows that the dashboard is running and opens the settings window on a
click. The icon reflects whether the kiosk is actually connected: a running
backend nobody is displaying looks different from a live dashboard.

Implemented over StatusNotifierItem — the D-Bus standard that KDE Plasma,
GNOME (with an extension), Waybar and others understand. That keeps a GUI
toolkit out of the backend: no GTK, no Qt, only ``dbus-next``, which is
needed for the media module anyway.

Without a session or without a panel (server, TTY) the tray is skipped
silently — the backend runs on unimpressed.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from dbus_next import BusType, Variant
from dbus_next.aio import MessageBus
from dbus_next.constants import PropertyAccess
from dbus_next.service import ServiceInterface, dbus_property, method, signal
from loguru import logger

from . import brand

# The string annotations on the interface methods below are D-Bus type
# signatures, not Python types: dbus-next reads them off the function to build
# the interface description. They are not valid annotations and ruff is told
# so in pyproject.toml, per file — a blanket ignore would hide real typos in
# the rest of the backend.

WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

#: Sizes offered to the panel. Covers the usual panel heights (16/18/22/24)
#: and their doubles for display scaling.
ICON_SIZES = (16, 18, 22, 24, 32, 36, 44, 48, 64)

ROOT = Path(__file__).resolve().parent.parent

#: Where to look for the settings window, in order. The packaged binary wins
#: over the development build, so an installed copy is not shadowed by a
#: stale one in the checkout.
GUI_CANDIDATES = (
    Path("/usr/bin/edgedash"),
    Path("/usr/local/bin/edgedash"),
    ROOT / "gui" / "src-tauri" / "target" / "release" / "edgedash",
    ROOT / "gui" / "src-tauri" / "target" / "debug" / "edgedash",
)

LABELS = {
    "de": {"open": "Einstellungen öffnen", "quit": "Beenden"},
    "en": {"open": "Open settings", "quit": "Quit"},
}

TOOLTIP = {
    "de": {
        "connected": "Dashboard verbunden",
        "waiting": "Kein Dashboard verbunden",
    },
    "en": {
        "connected": "Dashboard connected",
        "waiting": "No dashboard connected",
    },
}


def _resolve_language(language: str) -> str:
    """Maps the config value to a language the menu has labels for.

    `default_language` may be "auto". The kiosk resolves that from its own
    environment; here the locale of the session the backend runs in is the
    next best source.
    """
    if language in LABELS:
        return language
    if language == "auto":
        for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
            value = os.environ.get(variable, "")
            if value:
                return value[:2].lower() if value[:2].lower() in LABELS else "en"
    return "en"


def find_settings_app() -> Path | None:
    """The settings window's executable, or None if it has not been built."""
    override = os.environ.get("EDGE_GUI_BINARY")
    if override:
        path = Path(override)
        return path if path.is_file() and os.access(path, os.X_OK) else None
    for candidate in GUI_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("edgedash")
    return Path(found) if found else None


# --------------------------------------------------------------------------
# Icon
# --------------------------------------------------------------------------


def _argb_pixmap(image) -> list:
    """Converts an image into the StatusNotifierItem pixmap format.

    Expected is ARGB32 in network byte order — Pillow hands out RGBA, so the
    channels have to be reordered. Done with strided slices over the raw
    buffer rather than a loop over pixels: the panel asks for every offered
    size at once, and at 64x64 that is a quarter of a million pixels per
    icon change.
    """
    rgba = image.convert("RGBA")
    raw = rgba.tobytes()
    data = bytearray(len(raw))
    data[0::4] = raw[3::4]  # A
    data[1::4] = raw[0::4]  # R
    data[2::4] = raw[1::4]  # G
    data[3::4] = raw[2::4]  # B
    return [[rgba.width, rgba.height, bytes(data)]]


# --------------------------------------------------------------------------
# Menu (com.canonical.dbusmenu)
# --------------------------------------------------------------------------


class TrayMenu(ServiceInterface):
    """The tray icon's context menu."""

    def __init__(self, entries: list[dict]) -> None:
        super().__init__("com.canonical.dbusmenu")
        self.entries = entries
        self._revision = 1

    @dbus_property(access=PropertyAccess.READ)
    def Version(self) -> "u":
        return 3

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":
        return "normal"

    @dbus_property(access=PropertyAccess.READ)
    def TextDirection(self) -> "s":
        return "ltr"

    @dbus_property(access=PropertyAccess.READ)
    def IconThemePath(self) -> "as":
        return []

    def _item(self, index: int, entry: dict) -> list:
        properties = {
            "label": Variant("s", entry.get("label", "")),
            "enabled": Variant("b", entry.get("enabled", True)),
            "visible": Variant("b", True),
        }
        if entry.get("separator"):
            properties["type"] = Variant("s", "separator")
        return [index + 1, properties, []]

    @method()
    def GetLayout(
        self, parentId: "i", recursionDepth: "i", propertyNames: "as"
    ) -> "u(ia{sv}av)":
        children = [
            Variant("(ia{sv}av)", self._item(i, entry))
            for i, entry in enumerate(self.entries)
        ]
        return [
            self._revision,
            [0, {"children-display": Variant("s", "submenu")}, children],
        ]

    @method()
    def GetGroupProperties(
        self, ids: "ai", propertyNames: "as"
    ) -> "a(ia{sv})":
        result = []
        for i, entry in enumerate(self.entries):
            if not ids or (i + 1) in ids:
                item = self._item(i, entry)
                result.append([item[0], item[1]])
        return result

    @method()
    def GetProperty(self, id: "i", name: "s") -> "v":
        index = id - 1
        if 0 <= index < len(self.entries):
            return Variant("s", str(self.entries[index].get(name, "")))
        return Variant("s", "")

    @method()
    def Event(self, id: "i", eventId: "s", data: "v", timestamp: "u"):
        if eventId != "clicked":
            return
        index = id - 1
        if 0 <= index < len(self.entries):
            action = self.entries[index].get("action")
            if callable(action):
                asyncio.get_event_loop().call_soon(action)

    @method()
    def AboutToShow(self, id: "i") -> "b":
        return False

    @signal()
    def LayoutUpdated(self) -> "ui":
        self._revision += 1
        return [self._revision, 0]


# --------------------------------------------------------------------------
# Tray icon (org.kde.StatusNotifierItem)
# --------------------------------------------------------------------------


class TrayItem(ServiceInterface):
    def __init__(self, tray: SystemTray) -> None:
        super().__init__("org.kde.StatusNotifierItem")
        self.tray = tray

    @dbus_property(access=PropertyAccess.READ)
    def Category(self) -> "s":
        return "ApplicationStatus"

    @dbus_property(access=PropertyAccess.READ)
    def Id(self) -> "s":
        return "edge-dashboard"

    @dbus_property(access=PropertyAccess.READ)
    def Title(self) -> "s":
        return "Edge Dashboard"

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":
        return "Active"

    @dbus_property(access=PropertyAccess.READ)
    def IconName(self) -> "s":
        # No theme icon: the symbol is drawn and delivered as a pixmap.
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def IconPixmap(self) -> "a(iiay)":
        return self.tray.pixmaps()

    @dbus_property(access=PropertyAccess.READ)
    def AttentionIconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def OverlayIconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def ToolTip(self) -> "(sa(iiay)ss)":
        return ["", [], "Edge Dashboard", self.tray.tooltip()]

    @dbus_property(access=PropertyAccess.READ)
    def ItemIsMenu(self) -> "b":
        # False: a left click opens the settings window instead of the menu.
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Menu(self) -> "o":
        return MENU_PATH

    @method()
    def Activate(self, x: "i", y: "i"):
        self.tray.open_settings()

    @method()
    def SecondaryActivate(self, x: "i", y: "i"):
        self.tray.open_settings()

    @method()
    def Scroll(self, delta: "i", orientation: "s"):
        pass

    # Signals without payload: dbus-next derives the empty signature from the
    # missing return annotation.
    @signal()
    def NewIcon(self):
        pass

    @signal()
    def NewToolTip(self):
        pass

    @signal()
    def NewStatus(self) -> "s":
        return "Active"


# --------------------------------------------------------------------------
# Control
# --------------------------------------------------------------------------


class SystemTray:
    """Registers a tray icon and keeps it current."""

    def __init__(
        self,
        *,
        url: str,
        language: str = "en",
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        self.url = url
        self.language = _resolve_language(language)
        self._on_quit = on_quit

        self.bus: MessageBus | None = None
        self.item: TrayItem | None = None
        self.menu: TrayMenu | None = None

        self.clients = 0
        #: Tasks waiting on the settings windows we started.
        #:
        #: A child that exits stays in the process table until its parent
        #: collects the exit status, and the backend outlives many openings of
        #: the window. Awaiting each one collects it the moment it ends, which
        #: also covers the second process that starting an already-running
        #: window produces: it hands its arguments to the first instance and
        #: exits immediately.
        self._windows: set[asyncio.Task] = set()

    # -- registering -------------------------------------------------------

    async def start(self) -> bool:
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            logger.info("no session bus — tray icon skipped")
            return False

        try:
            self.bus = await MessageBus(bus_type=BusType.SESSION).connect()
        except Exception as exc:
            logger.info(f"session bus unreachable, no tray icon: {exc}")
            return False

        self.item = TrayItem(self)
        self.menu = TrayMenu(self._entries())
        self.bus.export(ITEM_PATH, self.item)
        self.bus.export(MENU_PATH, self.menu)

        name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        try:
            await self.bus.request_name(name)
            introspection = await self.bus.introspect(WATCHER_NAME, WATCHER_PATH)
            proxy = self.bus.get_proxy_object(WATCHER_NAME, WATCHER_PATH, introspection)
            watcher = proxy.get_interface(WATCHER_NAME)
            await watcher.call_register_status_notifier_item(name)
        except Exception as exc:
            # No panel that speaks StatusNotifierItem — no reason to stop the
            # backend over it.
            logger.info(f"tray icon could not register (no supported panel?): {exc}")
            await self.stop()
            return False

        logger.info("tray icon registered")
        return True

    async def stop(self) -> None:
        bus, self.bus = self.bus, None
        if bus is not None:
            with contextlib.suppress(Exception):
                bus.disconnect()

    # -- state -------------------------------------------------------------

    def update(self, *, clients: int) -> None:
        """Called when a dashboard connects or disconnects."""
        changed = (clients > 0) != (self.clients > 0)
        self.clients = clients
        if self.item is None:
            return
        with contextlib.suppress(Exception):
            self.item.NewToolTip()
            if changed:
                self.item.NewIcon()

    def pixmaps(self) -> list:
        # Offer plenty of sizes: if the panel finds no match it scales one
        # itself, and an upscaled 22 looks ragged at 24 pixels. Every size is
        # drawn fresh anyway.
        result = []
        for size in ICON_SIZES:
            result.extend(_argb_pixmap(brand.icon_image(size, online=self.clients > 0)))
        return result

    def tooltip(self) -> str:
        texts = TOOLTIP[self.language]
        state = texts["connected"] if self.clients > 0 else texts["waiting"]
        return f"{state}\n{self.url}"

    # -- menu actions ------------------------------------------------------

    def _entries(self) -> list[dict]:
        labels = LABELS[self.language]
        return [
            {"label": labels["open"], "action": self.open_settings},
            {"separator": True, "label": ""},
            {"label": labels["quit"], "action": self._quit},
        ]

    def open_settings(self) -> None:
        """Start the settings window, or raise the one already running.

        Raising is the settings window's own job: it registers as a single
        instance, so starting it a second time makes the first one come
        forward and the second exit immediately.
        """
        binary = find_settings_app()
        if binary is None:
            logger.warning(
                "settings window not found — build it with: "
                "cd gui && npm run tauri build"
            )
            return
        task = asyncio.get_event_loop().create_task(self._run_window(binary))
        self._windows.add(task)
        task.add_done_callback(self._windows.discard)

    async def _run_window(self, binary: Path) -> None:
        """Start the settings window and wait for it, so nothing is left over."""
        try:
            # start_new_session: the window must not die with the backend, and
            # must not inherit its terminal.
            process = await asyncio.create_subprocess_exec(
                str(binary),
                start_new_session=True,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.warning(f"settings window could not be started: {exc}")
            return
        logger.info(f"settings window started: {binary}")
        await process.wait()

    def _quit(self) -> None:
        if self._on_quit is not None:
            self._on_quit()


__all__ = ["SystemTray", "find_settings_app"]
