"""Where a page's tracks sit: the CSS grid template turned into pixels.

The config describes a page the way the settings window draws it, as a CSS
track list (`32px 1fr 1fr`). QML's GridLayout cannot express that: it shares
space by the items' own sizes, not by `fr`, and it has no fixed column width.
So the kiosk places the tiles itself, from the offsets worked out here.

Kept apart from the bridge for the same reason as views.py: it is arithmetic,
not Qt, and testable without a Qt application.
"""

from __future__ import annotations

import re

_PX = re.compile(r"(\d+(?:\.\d+)?)px")
_FR = re.compile(r"(\d+(?:\.\d+)?)fr")
_MINMAX = re.compile(r"minmax\([^,]+,\s*(\d+(?:\.\d+)?)fr\)")
#: One track: a `minmax(...)` as a whole, spaces inside it included, or else
#: a run of non-space characters. A plain split would cut `minmax(0, 1fr)` in
#: two and count it as two tracks.
_TOKEN = re.compile(r"minmax\([^)]*\)|\S+")


def tracks(template: str) -> list[dict]:
    """A CSS grid template as fixed sizes and stretch factors.

    `32px 1fr 2fr` becomes one fixed track of 32 pixels and two sharing the
    rest one to two. `minmax(0, 1fr)` counts as its `fr` part. Anything
    unrecognised falls back to an equal share.
    """
    out = []
    for token in _TOKEN.findall(template):
        px = _PX.fullmatch(token)
        fr = _FR.fullmatch(token)
        minmax = _MINMAX.fullmatch(token)
        if px:
            out.append({"fixed": float(px.group(1)), "stretch": 0.0})
        elif fr:
            out.append({"fixed": 0.0, "stretch": float(fr.group(1))})
        elif minmax:
            out.append({"fixed": 0.0, "stretch": float(minmax.group(1))})
        else:
            out.append({"fixed": 0.0, "stretch": 1.0})
    return out or [{"fixed": 0.0, "stretch": 1.0}]


def spans(track_list: list[dict], total: float, gap: float) -> list[list[float]]:
    """Start and size of every track along one axis, in pixels.

    Fixed tracks get their size, the gaps come off next, and whatever is left
    is shared by the stretch factors. When the fixed tracks alone do not fit,
    the stretching ones get nothing rather than a negative size.
    """
    if not track_list:
        return []
    fixed = sum(t["fixed"] for t in track_list)
    stretch = sum(t["stretch"] for t in track_list)
    free = max(0.0, total - gap * (len(track_list) - 1) - fixed)
    out = []
    start = 0.0
    for t in track_list:
        size = t["fixed"] + (free * t["stretch"] / stretch if stretch > 0 else 0.0)
        out.append([start, size])
        start += size + gap
    return out
