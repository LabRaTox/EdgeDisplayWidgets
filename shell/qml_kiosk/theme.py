"""Themes, read out of the CSS files in `frontend/css/themes/`.

Only the `:root` block is of interest, the custom properties that name the
colours and fonts. Reading CSS rather than keeping a second set of theme
files in a format of our own means a file dropped into that directory shows
up in the settings window and works, with nothing to keep in sync.

Beyond the variables, a few rules decide what a theme looks like: the inset
and the corner of a tile, how the heading is set, and the decoration on top,
which is glow, scanlines and the cut corner in toxic.css. Those are read here
as well, see `metrics()` and `effects()`.

Left out are the parts that only a CSS engine can do: the rivet and the gear
steampunk.css draws with pseudo-elements, and the animations that run
forever, which on a panel that is on all day cost more than they give.
"""

from __future__ import annotations

import pathlib
import re

#: The root font size the stylesheets were written against. Every `rem` is
#: relative to this, so it is the conversion factor for every size taken from
#: there.
REM = 20.0

_VAR = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;]+);")
_ROOT = re.compile(r":root\s*\{(.*?)\}", re.S)
_RULE = re.compile(r"([^{}@]+)\{([^{}]*)\}", re.S)
_DECL = re.compile(r"([a-z-]+)\s*:\s*([^;]+)")

#: A theme file restyles more than the variables. These rules decide how big
#: a tile's inset is, how round its corner is and how its heading is set, so
#: they have to come across as well. What is left over are glows, scanlines
#: and overlays, which are decoration rather than layout.
#:
#: `.metric-big` is deliberately not in here, although every theme writes one.
#: The base sheet says `.widget .metric-big`, two classes against the themes'
#: one, and the more specific rule wins no matter which file is loaded later.
#: The big figure is therefore the same in every theme, and taking the theme's
#: value would have made it smaller and thinner than the stylesheet asks for.
_RULES = {
    ".widget": ("padding", "border-radius"),
    ".widget h3": ("font-size", "font-weight", "letter-spacing"),
    ".clock-time": ("font-weight",),
}

#: Rules carrying the decoration. Read by `effects()`, which is separate from
#: `metrics()` because these change nothing about where anything sits.
_EFFECT_RULES = (
    "body::after",      # the scanline overlay
    ".widget",          # box-shadow and the cut corner
    ".widget::before",  # the diagonal sheen in nightclub
    ".widget h3",       # heading colour and its glow
    ".metric-big",      # the glow on the big figure
)

#: Nothing switched on. A theme that says nothing gets this.
NO_EFFECTS = {
    "scanline_color": "", "scanline_period": 0.0, "scanline_thickness": 0.0,
    "glow_color": "", "glow_blur": 0.0, "glow_dx": 0.0, "glow_dy": 0.0,
    "inset_color": "", "inset_width": 0.0,
    "cut": 0.0,
    "sheen_color": "", "sheen_opacity": 0.0,
    "heading_color": "", "heading_glow_color": "", "heading_glow_blur": 0.0,
    "metric_glow_color": "", "metric_glow_blur": 0.0,
}

#: The base values, for every theme that stays silent about them.
BASE_METRICS = {
    "tile_pad_h": 12.0,
    "tile_pad_v": 12.0,
    "tile_radius": 8.0,
    "padding_from_theme": False,
    "heading_size": 0.9 * REM,
    "heading_weight": 500,
    "heading_spacing": 0.1 * 0.9 * REM,      # 0.1em of a 0.9rem font
    "metric_size": 2.8 * REM,
    "metric_weight": 500,
    "clock_weight": 300,
}


def _length(value: str, font_px: float) -> float:
    """A CSS length in pixels. `em` is relative to the element's own size."""
    value = value.strip()
    match = re.fullmatch(r"(-?[\d.]+)(px|rem|em)?", value)
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2) or "px"
    if unit == "rem":
        return number * REM
    if unit == "em":
        return number * font_px
    return number


def _metrics(text: str) -> dict:
    """The handful of rules from a theme file that change a widget's shape."""
    out = dict(BASE_METRICS)
    # Comments first: one left in front of a rule would otherwise become part
    # of its selector, and the rule would be skipped.
    body = _ROOT.sub("", re.sub(r"/\*.*?\*/", "", text, flags=re.S))
    for selector, block in _RULE.findall(body):
        # `.widget h3` in a theme, `.widget .metric-big` in the base sheet.
        name = " ".join(selector.split()).strip()
        if name not in _RULES:
            continue
        wanted = _RULES[name]
        decls = {k: v.strip() for k, v in _DECL.findall(block) if k in wanted}

        if name == ".widget":
            if "padding" in decls:
                parts = decls["padding"].split()
                out["tile_pad_v"] = _length(parts[0], REM)
                out["tile_pad_h"] = _length(parts[1] if len(parts) > 1 else parts[0], REM)
                out["padding_from_theme"] = True
            if "border-radius" in decls:
                out["tile_radius"] = _length(decls["border-radius"], REM)
        elif name == ".widget h3":
            if "font-size" in decls:
                out["heading_size"] = _length(decls["font-size"], REM)
            if "font-weight" in decls:
                out["heading_weight"] = int(float(decls["font-weight"]))
            if "letter-spacing" in decls:
                out["heading_spacing"] = _length(decls["letter-spacing"], out["heading_size"])
        elif name == ".clock-time" and "font-weight" in decls:
            out["clock_weight"] = int(float(decls["font-weight"]))
    return out

#: Values used when a theme leaves them out. These are the base ones the
#: stylesheets defined before any theme was applied, so a half-finished theme
#: still comes out readable rather than blank.
BASE = {
    "bg": "#0a0a0a",
    "fg": "#e0e0e0",
    "fg-muted": "#888888",
    "accent": "#00e0ff",
    "accent-2": "#ff4488",
    "ok": "#4ade80",
    "warn": "#facc15",
    "bad": "#f87171",
    "card-bg": "rgba(255, 255, 255, 0.04)",
    "card-border": "rgba(255, 255, 255, 0.06)",
    "gap": "8px",
}


def _rgba_to_hex(value: str) -> str:
    """QML wants #AARRGGBB where CSS writes rgba(r, g, b, a)."""
    match = re.fullmatch(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", value.strip()
    )
    if not match:
        return value.strip()
    r, g, b = (int(match.group(i)) for i in (1, 2, 3))
    a = float(match.group(4) or 1.0)
    return f"#{round(a * 255):02x}{r:02x}{g:02x}{b:02x}"


def _first_colour(value: str) -> str:
    """The first colour in a value, so a gradient still yields something.

    `card-bg` is a linear-gradient in several themes. A tile painted in the
    gradient's first stop is close enough that the difference is not visible
    against the background, and it keeps the parser from needing to
    understand CSS gradients.
    """
    value = value.strip()
    if value.startswith("linear-gradient"):
        inner = re.findall(r"(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8})", value)
        return _rgba_to_hex(inner[0]) if inner else "#00000000"
    return _rgba_to_hex(value)


def metrics(name: str, themes_dir: pathlib.Path) -> dict:
    """Sizes and weights of one theme: what is not a colour."""
    path = themes_dir / f"{name}.css"
    if not path.is_file():
        return dict(BASE_METRICS)
    return _metrics(path.read_text(encoding="utf-8", errors="replace"))


def load(name: str, themes_dir: pathlib.Path) -> dict:
    """Colour and font values of one theme, ready for QML."""
    values = dict(BASE)
    path = themes_dir / f"{name}.css"
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        for block in _ROOT.findall(text):
            for key, value in _VAR.findall(block):
                values[key] = value.strip()

    out = {}
    for key, value in values.items():
        if key.startswith("font-"):
            # Take the first family; QML picks the fallback itself.
            out[key] = value.split(",")[0].strip().strip('"').strip("'")
        elif key == "gap":
            out[key] = float(re.sub(r"[^\d.]", "", value) or 8)
        else:
            out[key] = _first_colour(value)
    return out


def available(themes_dir: pathlib.Path) -> list[str]:
    return sorted(p.stem for p in themes_dir.glob("*.css"))


_COLOUR = re.compile(r"(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8}|var\(--[a-z0-9-]+\))")


def _split_top(value: str) -> list[str]:
    """Split on commas that are not inside brackets: a shadow list."""
    parts, depth, current = [], 0, ""
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def _resolve(value: str, colours: dict) -> str:
    """A colour value as QML wants it, with `var(--accent)` looked up."""
    value = value.strip()
    match = re.fullmatch(r"var\(--([a-z0-9-]+)\)", value)
    if match:
        return colours.get(match.group(1), "")
    return _rgba_to_hex(value)


def _shadow(part: str, colours: dict) -> dict:
    """One entry of a box-shadow or text-shadow list.

    CSS writes `<dx> <dy> <blur> <spread> <colour>`, any of the lengths may be
    missing, and `inset` may stand anywhere. Only what is actually used in the
    theme files is read: offset, blur and the colour.
    """
    inset = "inset" in part
    part = part.replace("inset", " ")
    colour_match = _COLOUR.search(part)
    colour = _resolve(colour_match.group(1), colours) if colour_match else ""
    if colour_match:
        part = part[: colour_match.start()] + part[colour_match.end() :]
    lengths = [_length(token, REM) for token in part.split() if token.strip()]
    lengths += [0.0] * (4 - len(lengths))
    return {
        "inset": inset,
        "dx": lengths[0], "dy": lengths[1], "blur": lengths[2], "spread": lengths[3],
        "colour": colour,
    }


def effects(name: str, themes_dir: pathlib.Path, colours: dict | None = None) -> dict:
    """The decoration a theme puts on top: glow, scanlines, the cut corner."""
    out = dict(NO_EFFECTS)
    path = themes_dir / f"{name}.css"
    if not path.is_file():
        return out
    colours = colours or {}
    text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    body = _ROOT.sub("", text)

    for selector, block in _RULE.findall(body):
        rule = " ".join(selector.split()).strip()
        if rule not in _EFFECT_RULES:
            continue
        decls = {k: v.strip() for k, v in _DECL.findall(block)}

        if rule == "body::after" and "background" in decls:
            # repeating-linear-gradient(180deg, transparent 0, transparent 2px,
            #                           colour 2px, colour 3px)
            gradient = decls["background"]
            if "repeating-linear-gradient" in gradient:
                colour_match = _COLOUR.search(gradient)
                stops = re.findall(r"([\d.]+)px", gradient)
                if colour_match and len(stops) >= 2:
                    out["scanline_color"] = _resolve(colour_match.group(1), colours)
                    out["scanline_thickness"] = float(stops[-1]) - float(stops[-2])
                    out["scanline_period"] = float(stops[-1])

        elif rule == ".widget":
            for part in _split_top(decls.get("box-shadow", "")):
                shadow = _shadow(part, colours)
                if not shadow["colour"]:
                    continue
                if shadow["inset"]:
                    out["inset_color"] = shadow["colour"]
                    out["inset_width"] = shadow["spread"] or 1.0
                else:
                    out["glow_color"] = shadow["colour"]
                    out["glow_blur"] = shadow["blur"]
                    out["glow_dx"] = shadow["dx"]
                    out["glow_dy"] = shadow["dy"]
            if "clip-path" in decls and "polygon" in decls["clip-path"]:
                sizes = re.findall(r"([\d.]+)px", decls["clip-path"])
                if sizes:
                    out["cut"] = float(sizes[0])

        elif rule == ".widget::before":
            gradient = decls.get("background", "")
            if "linear-gradient" in gradient:
                colour_match = _COLOUR.search(gradient)
                if colour_match:
                    out["sheen_color"] = _resolve(colour_match.group(1), colours)
                    out["sheen_opacity"] = float(decls.get("opacity", "1") or 1)

        elif rule == ".widget h3":
            if "color" in decls:
                out["heading_color"] = _resolve(decls["color"], colours)
            shadows = _split_top(decls.get("text-shadow", ""))
            if shadows:
                first = _shadow(shadows[0], colours)
                out["heading_glow_color"] = first["colour"]
                out["heading_glow_blur"] = first["blur"]

        elif rule == ".metric-big":
            # Only the shadow: the base sheet says `.widget .metric-big` for
            # colour and size, and the more specific rule is the one to take.
            shadows = _split_top(decls.get("text-shadow", ""))
            if shadows:
                first = _shadow(shadows[0], colours)
                out["metric_glow_color"] = first["colour"]
                out["metric_glow_blur"] = first["blur"]
    return out
