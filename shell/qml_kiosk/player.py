"""Fullscreen player for one YouTube embed, in its own process.

The kiosk window carries no web view. A video needs one, so it gets one for
exactly as long as it plays: this process starts when a tile is tapped and
exits when the video is closed, so the memory a Chromium renderer occupies is
gone afterwards instead of sitting in the kiosk all day.

    python3 -m qml_kiosk.player --url https://www.youtube-nocookie.com/embed/...
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DEFAULT_WIDTH = 2560
DEFAULT_HEIGHT = 720

#: The close button, drawn over the embed.
CLOSE_STYLE = """
QPushButton {
    border: 0;
    border-radius: 22px;
    background: rgba(0, 0, 0, 0.6);
    color: #ffffff;
    font-size: 28px;
}
QPushButton:hover { background: rgba(0, 0, 0, 0.85); }
"""


def pick_screen(app: QApplication, name: str, width: int, height: int):
    """The output to play on: by name first, then by resolution."""
    if name:
        for screen in app.screens():
            if screen.name() == name:
                return screen
        return None
    for screen in app.screens():
        geometry = screen.geometry()
        if geometry.width() == width and geometry.height() == height:
            return screen
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qml-kiosk-player")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    app = QApplication(sys.argv)
    app.setApplicationName("edge-dashboard")
    app.setDesktopFileName("edge-dashboard")

    window = QWidget()
    window.setWindowTitle("Edge Dashboard")
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    window.setStyleSheet("background: #000000;")

    view = QWebEngineView(window)
    settings = view.settings()
    # Without this the embed waits for a click that a kiosk has no way to give.
    settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
    view.setUrl(QUrl(args.url))

    close = QPushButton("\u00d7", window)   # multiplication sign, not a letter x
    close.setStyleSheet(CLOSE_STYLE)
    close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    close.setFixedSize(44, 44)
    close.clicked.connect(app.quit)
    QShortcut(QKeySequence(Qt.Key.Key_Escape), window, app.quit)

    def relayout() -> None:
        view.setGeometry(0, 0, window.width(), window.height())
        close.move(window.width() - 44 - 6, 6)         # top 6px, right 6px
        close.raise_()

    window.resizeEvent = lambda _event: relayout()

    screen = pick_screen(app, args.output, args.width, args.height)
    if screen is not None:
        window.setScreen(screen)
        window.setGeometry(screen.geometry())
    window.showFullScreen()
    relayout()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
