"""The app icon — defined once, drawn two ways.

The tray icon, the settings window's favicon and the wordmark next to it are
meant to be the same picture. The geometry therefore lives here as plain
ratios, and both outputs derive from it:

* :func:`icon_image` draws with Pillow — that is what the tray needs, since
  it hands its icons to the panel as pixmaps over D-Bus.
* :func:`icon_svg` writes the same rectangles as SVG — that is what the
  settings window needs. ``scripts/make-icon.py`` puts the file in ``gui/``.

The motif: a dashboard grid — two tiles side by side, one wide tile below
them, and a sparkline along the bottom. Deliberately *not* the real widget
layout: at 16 pixels a faithful grid collapses into noise, three tiles and a
line stay readable.

Body, gradient and corner radius are the same as DECK//SWITCH's icon on
purpose — the two applications are a pair and should look like one. What
distinguishes them is only what sits on the body: uneven dashboard tiles
here, an even key grid there.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

# -- Colours ---------------------------------------------------------------

#: Identical to DECK//SWITCH by intent: the two applications belong together
#: and their icons share the body, the gradient and the corner radius. Only
#: the white shapes on top tell them apart.
GRADIENT_TOP = (59, 130, 246)
GRADIENT_BOTTOM = (139, 92, 246)
TILE_COLOR = (255, 255, 255)
#: The sparkline steps back — it is decoration, not a tile.
LINE_ALPHA = 185

#: With the backend down the icon is desaturated rather than reshaped: the
#: silhouette stays recognisable, the state still reads at a glance.
OFFLINE_GRAY = (122, 122, 132)

# -- Geometry (everything as a fraction of the edge length) ----------------

#: Tiles per row, as relative widths. Row one is split in two, row two is a
#: single wide tile — that asymmetry is the whole motif.
ROW_WEIGHTS = ((1, 1), (1,))
CASE_RADIUS = 0.24
#: Distance between the body's edge and the motif.
PADDING = 0.17
GAP = 0.075          # relative to the motif width
TILE_RADIUS = 0.22   # relative to the tile height
ROW_HEIGHT = 0.44    # relative to the tile width of a full-width row
LINE_HEIGHT = 0.30   # relative to a row's height
LINE_GAP = 1.1       # relative to the gap between tiles

#: Below this edge length (in pixels) a shape gets square corners. Under it
#: nothing would be left of the shape: a one pixel radius cuts all four
#: corners off a three pixel tile, leaving a plus sign.
MIN_ROUNDED = 8


def _shapes(size: int) -> tuple[list[tuple[int, int, int, int, int]], tuple]:
    """Returns (tiles, sparkline) as ``(x, y, width, height, radius)``.

    All integers, snapped to the pixel grid. On a tray icon that is not
    cosmetics: at 22 pixels a tile is seven pixels wide and the gap beside it
    exactly one. Computed in fractions, that gap disappears when drawing and
    the tiles merge into one white block.

    The values are width and height — *not* end coordinates. Pillow draws
    rectangles inclusive of their end point, so a plain ``x + width`` would
    be one pixel too wide and close the gaps just the same.
    """
    padding = max(1, round(size * PADDING))
    span = size - 2 * padding

    gap = max(1, round(span * GAP))
    row_height = max(1, round(span * ROW_HEIGHT))
    line_height = max(1, round(row_height * LINE_HEIGHT))
    line_gap = max(1, round(gap * LINE_GAP))
    radius = round(row_height * TILE_RADIUS) if row_height >= MIN_ROUNDED else 0

    block = len(ROW_WEIGHTS) * row_height + (len(ROW_WEIGHTS) - 1) * gap + line_gap + line_height
    top = padding + (span - block) // 2

    tiles: list[tuple[int, int, int, int, int]] = []
    for index, weights in enumerate(ROW_WEIGHTS):
        columns = len(weights)
        # Integer division first, remainder handed to the last tile: that
        # keeps every row exactly `span` wide, so the rows stay flush at the
        # right edge instead of drifting apart by a pixel.
        usable = span - (columns - 1) * gap
        total = sum(weights)
        widths = [max(1, usable * weight // total) for weight in weights]
        widths[-1] += usable - sum(widths)
        y = top + index * (row_height + gap)
        x = padding
        for width in widths:
            tiles.append((x, y, width, row_height, radius))
            x += width + gap

    line = (
        padding,
        top + len(ROW_WEIGHTS) * row_height + (len(ROW_WEIGHTS) - 1) * gap + line_gap,
        span,
        line_height,
        round(line_height * 0.4) if line_height >= MIN_ROUNDED else 0,
    )
    return tiles, line


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


# -- Pillow (tray) ---------------------------------------------------------


def icon_image(size: int, *, online: bool = True) -> Image.Image:
    """The icon as an image — for the tray, which sends pixmaps over D-Bus."""
    if online:
        top, bottom = GRADIENT_TOP, GRADIENT_BOTTOM
    else:
        top = bottom = OFFLINE_GRAY

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Draw the gradient row by row and mask it with the rounded shape —
    # Pillow cannot fill a rounded_rectangle with a gradient.
    gradient = Image.new("RGBA", (size, size))
    pen = ImageDraw.Draw(gradient)
    for row in range(size):
        t = row / max(1, size - 1)
        pen.line([(0, row), (size, row)], fill=(*_mix(top, bottom, t), 255))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=round(size * CASE_RADIUS), fill=255
    )
    image.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(image)
    tiles, line = _shapes(size)
    for x, y, width, height, radius in tiles:
        # -1 because Pillow draws the end point as well.
        draw.rounded_rectangle(
            (x, y, x + width - 1, y + height - 1), radius=radius, fill=(*TILE_COLOR, 255)
        )

    # The sparkline is translucent and therefore has to be *blended* onto the
    # body. ``ImageDraw`` replaces the pixels instead — drawn directly it
    # would tear a half-transparent hole through the icon, showing the
    # panel's background through it.
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x, y, width, height, radius = line
    ImageDraw.Draw(overlay).rounded_rectangle(
        (x, y, x + width - 1, y + height - 1), radius=radius, fill=(*TILE_COLOR, LINE_ALPHA)
    )
    image.alpha_composite(overlay)
    return image


# -- SVG (settings window) -------------------------------------------------


def icon_svg(size: int = 64) -> str:
    """The same icon as SVG — source for the favicon and the header logo."""
    tiles, line = _shapes(size)

    def rect(x, y, width, height, radius, opacity=1.0) -> str:
        # No -1 as with Pillow: SVG rectangles have a real width.
        attrs = f'x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="#ffffff"'
        if opacity < 1.0:
            attrs += f' fill-opacity="{opacity:.3f}"'
        return f"  <rect {attrs}/>"

    body = "\n".join(rect(*tile) for tile in tiles)
    body += "\n" + rect(*line, opacity=LINE_ALPHA / 255)

    top = "#{:02x}{:02x}{:02x}".format(*GRADIENT_TOP)
    bottom = "#{:02x}{:02x}{:02x}".format(*GRADIENT_BOTTOM)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" \
width="{size}" height="{size}" role="img" aria-label="Edge Dashboard">
  <defs>
    <linearGradient id="case" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{top}"/>
      <stop offset="1" stop-color="{bottom}"/>
    </linearGradient>
  </defs>
  <rect width="{size}" height="{size}" rx="{round(size * CASE_RADIUS)}" fill="url(#case)"/>
{body}
</svg>
"""


__all__ = ["icon_image", "icon_svg"]
