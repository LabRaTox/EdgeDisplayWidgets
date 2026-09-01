"""The kiosk window, in QML.

    /usr/bin/python3 -m qml_kiosk [--windowed]

Runs on the system Python, like the WebEngine version it replaces, and reads
the same config. `--windowed` puts it in a normal window for development;
without it the window goes fullscreen on the display matching 2560x720 and
carries no decoration.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

HERE = pathlib.Path(__file__).resolve().parent
#: Fonts a theme may ask for that the system does not ship.
FONTS_DIR = HERE.parents[1] / "frontend" / "vendor" / "fonts"
sys.path.insert(0, str(HERE))

from bridge import Bridge  # noqa: E402

DEFAULT_WIDTH = 2560
DEFAULT_HEIGHT = 720


def log(message: str) -> None:
    print(f"kiosk: {message}", file=sys.stderr, flush=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="qml-kiosk")
    parser.add_argument("--url", default=os.environ.get("EDGE_WS_URL", ""),
                        help="WebSocket of the backend (default: from the config)")
    parser.add_argument("--output", default=os.environ.get("EDGE_OUTPUT", ""),
                        help="output name to use verbatim, e.g. DP-4")
    parser.add_argument("--width", type=int, default=int(os.environ.get("EDGE_WIDTH", DEFAULT_WIDTH)))
    parser.add_argument("--height", type=int, default=int(os.environ.get("EDGE_HEIGHT", DEFAULT_HEIGHT)))
    parser.add_argument("--windowed", action="store_true",
                        help="normal window on the primary screen, for development")
    parser.add_argument("--show-cursor", action="store_true")
    return parser.parse_args(argv)


def pick_screen(app: QGuiApplication, name: str, width: int, height: int):
    """The output to display on: by name first, then by resolution."""
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


def load_fonts() -> None:
    """Register the vendored fonts, so a theme asking for one gets it.

    Three themes (industrial, nightclub, toxic) name "Share Tech Mono", which
    is not installed anywhere on this system, so without this those themes are
    silently drawn in whatever monospace font Qt falls back to.

    Missing files are not fatal. A font that cannot be loaded costs a theme
    its typeface, not the display.
    """
    if not FONTS_DIR.is_dir():
        return
    for path in sorted(FONTS_DIR.glob("*.woff2")) + sorted(FONTS_DIR.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            log(f"could not load font {path.name}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    app = QGuiApplication(sys.argv)
    app.setApplicationName("edge-dashboard")
    # QSettings needs both names, or the pomodoro state lands in a file called "Unknown".
    app.setOrganizationName("edge-dashboard")
    app.setApplicationDisplayName("Edge Dashboard")
    app.setDesktopFileName("edge-dashboard")
    load_fonts()

    bridge = Bridge(args.url or None)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(HERE / "qml"))
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Main.qml")))
    if not engine.rootObjects():
        log("QML could not be loaded")
        return 1

    window = engine.rootObjects()[0]
    if not args.show_cursor and not args.windowed:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QCursor
        app.setOverrideCursor(QCursor(Qt.CursorShape.BlankCursor))

    if args.windowed:
        window.setWidth(args.width // 2)
        window.setHeight(args.height // 2)
        window.show()
    else:
        screen = pick_screen(app, args.output, args.width, args.height)
        if screen is None:
            wanted = args.output or f"{args.width}x{args.height}"
            log(f"no output matching '{wanted}' yet, using the primary screen")
            screen = app.primaryScreen()
        window.setScreen(screen)
        window.setGeometry(screen.geometry())
        window.showFullScreen()
        bridge.set_output(screen.name())
        log(f"placed on {screen.name()} {screen.geometry().width()}x{screen.geometry().height()}")

        def on_screen_added(added):
            """The Xeneon often initialises after we do on a cold boot."""
            wanted = pick_screen(app, args.output, args.width, args.height)
            if wanted is added and window.screen() is not added:
                log(f"target display appeared: {added.name()}")
                window.setScreen(added)
                window.setGeometry(added.geometry())
                window.showFullScreen()

        app.screenAdded.connect(on_screen_added)

    log(f"running: {bridge.summary()}")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
