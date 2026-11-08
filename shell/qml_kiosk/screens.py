"""Which output the kiosk belongs on.

Shared by the kiosk window and the video player, so both land on the same
display. Kept free of a QApplication of its own: it takes the screens it is
given, which keeps it testable without a display.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

#: What the model or maker name of the display contains, as the EDID gives it.
#: Matched when the resolution says nothing, e.g. at a scale other than 100 %.
KNOWN_MODELS = ("XENEON EDGE", "XENEON")


class ScreenLike(Protocol):
    def name(self) -> str: ...
    def model(self) -> str: ...
    def manufacturer(self) -> str: ...
    def geometry(self): ...
    def devicePixelRatio(self) -> float: ...


def physical_size(screen: ScreenLike) -> tuple[int, int]:
    """The output's size in device pixels.

    `geometry()` is in logical pixels: at 125 % scaling a 2560x720 panel
    reports 2048x576, and a match on the resolution alone would miss it.
    """
    geometry = screen.geometry()
    ratio = screen.devicePixelRatio() or 1.0
    return round(geometry.width() * ratio), round(geometry.height() * ratio)


def pick_screen(screens: Iterable[ScreenLike], name: str, width: int, height: int):
    """The output to display on, or None when it is not (yet) connected.

    In this order: the output name given verbatim; the resolution in device
    pixels, either way round, so a panel mounted on its side is found too;
    the model name the display reports.
    """
    screens = list(screens)
    if name:
        return next((s for s in screens if s.name() == name), None)
    for screen in screens:
        if physical_size(screen) in ((width, height), (height, width)):
            return screen
    for screen in screens:
        label = f"{screen.manufacturer()} {screen.model()}".upper()
        if any(model in label for model in KNOWN_MODELS):
            return screen
    return None
