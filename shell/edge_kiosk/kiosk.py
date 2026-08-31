"""The kiosk window: a Qt WebEngine view pinned to the Xeneon Edge.

Why a real application instead of a browser in kiosk mode
--------------------------------------------------------
The dashboard used to be rendered by Chromium started from a shell script.
Placing that window on the right output was the hard part: Chromium is an
XWayland client, KWin ignores the geometry such a client asks for, and on a
cold boot the window would often land on the primary monitor because the
Xeneon was not arranged yet. The workaround was a generated KWin rule.

Here the window *is* ours. Qt hands us the list of screens, we pick one and
put the window on it — and when the Xeneon shows up late, `screenAdded` tells
us and we move over. No compositor rules, no window-manager guessing.

Layout of the process tree: the backend is its own systemd service, this is a
second one. Keeping them apart means the settings window still has a backend
to talk to when the kiosk is not running, and a crashing renderer never takes
the data collection down with it.
"""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QKeySequence, QScreen, QShortcut
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

DEFAULT_URL = "http://127.0.0.1:8765"
DEFAULT_WIDTH = 2560
DEFAULT_HEIGHT = 720

# Backoff for "the backend is not up yet". The kiosk service and the backend
# service start at the same time, so the first attempt losing the race is the
# normal case, not an error.
RETRY_START_MS = 500
RETRY_MAX_MS = 5000

CACHE_ROOT = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "edge-dashboard",
    "webengine",
)

WAITING_HTML = """
<!doctype html>
<meta charset="utf-8">
<title>Edge Dashboard</title>
<style>
  html, body {{ height: 100%; margin: 0; }}
  body {{
    background: #06080c; color: #4a5a6a;
    font: 500 15px/1.5 system-ui, sans-serif;
    display: flex; align-items: center; justify-content: center;
  }}
  .msg {{ text-align: center; letter-spacing: .04em; }}
  .url {{ color: #26323f; font-size: 13px; margin-top: .5em; }}
</style>
<div class="msg">{message}<div class="url">{url}</div></div>
"""


def log(message: str) -> None:
    """One line to stderr — journald picks it up from there."""
    print(f"kiosk: {message}", file=sys.stderr, flush=True)


class KioskPage(QWebEnginePage):
    """Page that forwards the dashboard's console output to the journal.

    Without this, a JavaScript error on a screen nobody is sitting in front of
    is invisible: there is no devtools window to open on a kiosk.
    """

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            log(f"js error: {message} ({source}:{line})")
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel:
            log(f"js warning: {message}")


class KioskView(QWebEngineView):
    """The dashboard view, with the recovery behaviour a kiosk needs."""

    def __init__(self, url: str, profile: QWebEngineProfile) -> None:
        super().__init__()
        self._url = url
        self._retry_ms = RETRY_START_MS
        # The waiting screen is itself a page load, and its `loadFinished`
        # looks exactly like a successful dashboard load. Without this flag it
        # would reset the backoff on every attempt and report a dashboard that
        # is not there.
        self._showing_waiting = False
        self.setPage(KioskPage(profile, self))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setWindowTitle("Edge Dashboard")

        settings = self.settings()
        attr = QWebEngineSettings.WebAttribute
        # The media widget and the YouTube overlay start playback from code.
        settings.setAttribute(attr.PlaybackRequiresUserGesture, False)
        # Theme and language are remembered per device in localStorage.
        settings.setAttribute(attr.LocalStorageEnabled, True)
        # Nothing on the dashboard scrolls; a scrollbar would only ever be a
        # rendering artefact of a widget that overflows by a pixel.
        settings.setAttribute(attr.ShowScrollBars, False)
        settings.setAttribute(attr.ScrollAnimatorEnabled, False)
        settings.setAttribute(attr.FocusOnNavigationEnabled, False)

        self.loadFinished.connect(self._on_load_finished)
        self.page().renderProcessTerminated.connect(self._on_render_terminated)

    # ---------------------------------------------------------------- loading
    def load_dashboard(self) -> None:
        log(f"loading {self._url}")
        self._showing_waiting = False
        self.load(QUrl(self._url))

    def _on_load_finished(self, ok: bool) -> None:
        if self._showing_waiting:
            return  # that was our own waiting screen finishing
        if ok:
            self._retry_ms = RETRY_START_MS
            log("dashboard loaded")
            return
        # Most likely the backend has not finished starting. Say so on screen
        # instead of leaving a white page, and keep trying.
        self._showing_waiting = True
        self.setHtml(
            WAITING_HTML.format(message="Warte auf das Backend …", url=self._url),
            QUrl(self._url),
        )
        log(f"load failed, retrying in {self._retry_ms} ms")
        QTimer.singleShot(self._retry_ms, self.load_dashboard)
        self._retry_ms = min(self._retry_ms * 2, RETRY_MAX_MS)

    def _on_render_terminated(self, status, exit_code: int) -> None:
        log(f"render process gone (status={status}, code={exit_code}) — reloading")
        QTimer.singleShot(1000, self.load_dashboard)


def find_screen(
    app: QApplication, name: str, width: int, height: int
) -> QScreen | None:
    """Pick the output to display on: by name first, then by resolution.

    Returns None when neither matches, so the caller can decide whether to
    wait for the display to appear or fall back to the primary screen.
    """
    screens = app.screens()
    if name:
        for screen in screens:
            if screen.name() == name:
                return screen
        return None
    for screen in screens:
        geometry = screen.geometry()
        if geometry.width() == width and geometry.height() == height:
            return screen
    return None


def describe(screen: QScreen) -> str:
    g = screen.geometry()
    return f"{screen.name()} {g.width()}x{g.height()}+{g.x()}+{g.y()}"


def place(view: KioskView, screen: QScreen, fullscreen: bool) -> None:
    """Move the window onto `screen` and fill it."""
    log(f"placing window on {describe(screen)}")
    view.setScreen(screen)
    view.setGeometry(screen.geometry())
    if fullscreen:
        view.showFullScreen()
    else:
        view.show()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="edge-kiosk",
        description="Render the Edge Dashboard fullscreen on the Xeneon Edge display.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("EDGE_URL", DEFAULT_URL),
        help=f"dashboard URL (default: {DEFAULT_URL}, or $EDGE_URL)",
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("EDGE_OUTPUT", ""),
        help="output name to use verbatim, e.g. DP-4 (default: match by resolution)",
    )
    parser.add_argument(
        "--width", type=int, default=int(os.environ.get("EDGE_WIDTH", DEFAULT_WIDTH))
    )
    parser.add_argument(
        "--height", type=int, default=int(os.environ.get("EDGE_HEIGHT", DEFAULT_HEIGHT))
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="run in a normal window on the primary screen (for development)",
    )
    parser.add_argument(
        "--show-cursor",
        action="store_true",
        help="keep the mouse cursor visible (hidden by default on the touch display)",
    )
    parser.add_argument(
        "--zoom", type=float, default=float(os.environ.get("EDGE_ZOOM", "1.0"))
    )
    parser.add_argument(
        "--debug-port",
        type=int,
        default=int(os.environ.get("EDGE_DEBUG_PORT", "0")),
        help="expose Chromium remote debugging on this port (0 = off)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.debug_port:
        # Has to be set before QApplication exists.
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = str(args.debug_port)

    app = QApplication(sys.argv)
    app.setApplicationName("edge-dashboard")
    app.setApplicationDisplayName("Edge Dashboard")
    app.setDesktopFileName("edge-dashboard")

    # A named profile keeps its storage on disk, so the theme and language the
    # dashboard writes to localStorage survive a restart of the kiosk.
    profile = QWebEngineProfile("edge-kiosk", app)
    profile.setPersistentStoragePath(os.path.join(CACHE_ROOT, "storage"))
    profile.setCachePath(os.path.join(CACHE_ROOT, "cache"))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )

    view = KioskView(args.url, profile)

    # Keep the dashboard out of the task manager, the pager and Alt+Tab.
    #
    # On X11 the window can ask for this itself: `Qt::Tool` becomes
    # `_NET_WM_WINDOW_TYPE_UTILITY`, which every window manager worth the name
    # skips in its task list. That covers X11 sessions on any desktop with no
    # configuration at all.
    #
    # Wayland has no equivalent — xdg-shell knows no window types — so there
    # the compositor has to be told instead, which is what
    # scripts/window-rule.sh does for the compositors that allow it.
    if not args.windowed and app.platformName() == "xcb":
        view.setWindowFlag(Qt.WindowType.Tool, True)

    if args.zoom != 1.0:
        view.setZoomFactor(args.zoom)
    if not args.show_cursor and not args.windowed:
        view.setCursor(Qt.CursorShape.BlankCursor)

    if args.windowed:
        view.resize(args.width // 2, args.height // 2)
        view.show()
    else:
        screen = find_screen(app, args.output, args.width, args.height)
        if screen is None:
            wanted = args.output or f"{args.width}x{args.height}"
            log(f"no output matching '{wanted}' yet — using the primary screen for now")
            screen = app.primaryScreen()
        place(view, screen, fullscreen=True)

        def on_screen_added(added: QScreen) -> None:
            """The Xeneon often initialises after we do on a cold boot."""
            wanted = find_screen(app, args.output, args.width, args.height)
            if wanted is added and view.screen() is not added:
                log(f"target display appeared: {describe(added)}")
                place(view, added, fullscreen=True)

        def on_screen_removed(removed: QScreen) -> None:
            if view.screen() is not removed:
                return
            fallback = app.primaryScreen()
            if fallback is not None:
                log("display disconnected — falling back to the primary screen")
                place(view, fallback, fullscreen=True)

        app.screenAdded.connect(on_screen_added)
        app.screenRemoved.connect(on_screen_removed)

    # A kiosk has no keyboard most of the time; these exist for the times it
    # does — a stuck page, or a developer looking at the thing.
    QShortcut(QKeySequence("Ctrl+R"), view, activated=view.load_dashboard)
    QShortcut(QKeySequence("Ctrl+Q"), view, activated=app.quit)
    QShortcut(QKeySequence("F11"), view, activated=lambda: (
        view.showNormal() if view.isFullScreen() else view.showFullScreen()
    ))

    view.load_dashboard()
    sys.exit(app.exec())


__all__ = ["KioskView", "find_screen", "main"]
