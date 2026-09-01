"""Tests for the theme reader the QML kiosk uses.

The kiosk has no stylesheet of its own: it reads the theme CSS files and
turns them into values QML understands. That parsing is regular expressions
over CSS, so it is worth pinning down, both against the real theme files in
the repository and against small written-out cases that say exactly what is
expected.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shell" / "qml_kiosk"))

import theme as theme_module  # noqa: E402

THEMES = ROOT / "frontend" / "css" / "themes"


def test_colours_come_from_root():
    values = theme_module.load("cyberpunk", THEMES)
    assert values["accent"] == "#00f5ff"
    assert values["bg"] == "#07020d"
    # rgba() has to arrive as #AARRGGBB, alpha first, which is what QML reads.
    assert values["card-bg"] == "#0a00f5ff"


def test_missing_theme_falls_back_to_base():
    values = theme_module.load("does-not-exist", THEMES)
    assert values["accent"] == theme_module._rgba_to_hex(theme_module.BASE["accent"])


def test_font_takes_the_first_family():
    values = theme_module.load("cyberpunk", THEMES)
    assert values["font-mono"] == "JetBrains Mono"


def test_metrics_read_the_tile_rules():
    metrics = theme_module.metrics("clean", THEMES)
    assert metrics["tile_radius"] > 0
    assert metrics["heading_size"] > 0


def test_effects_scanlines_and_glow():
    colours = theme_module.load("cyberpunk", THEMES)
    fx = theme_module.effects("cyberpunk", THEMES, colours)
    # repeating-linear-gradient(..., transparent 2px, colour 2px, colour 3px)
    assert fx["scanline_period"] == 3.0
    assert fx["scanline_thickness"] == 1.0
    assert fx["glow_blur"] == 12.0
    assert fx["glow_dx"] == 0.0 and fx["glow_dy"] == 0.0
    # `.widget h3 { color: var(--accent) }` resolves against the theme.
    assert fx["heading_color"] == "#00f5ff"
    assert fx["heading_glow_blur"] == 6.0


def test_effects_cut_corner():
    fx = theme_module.effects("toxic", THEMES, theme_module.load("toxic", THEMES))
    assert fx["cut"] == 10.0
    assert fx["inset_width"] == 1.0


def test_effects_offset_shadow():
    fx = theme_module.effects("light", THEMES, theme_module.load("light", THEMES))
    # box-shadow: 0 1px 2px rgba(0, 0, 0, 0.15)
    assert (fx["glow_dx"], fx["glow_dy"], fx["glow_blur"]) == (0.0, 1.0, 2.0)


def test_theme_without_decoration_stays_empty():
    fx = theme_module.effects("clean", THEMES, theme_module.load("clean", THEMES))
    assert fx["scanline_color"] == ""
    assert fx["glow_color"] == ""
    assert fx["cut"] == 0.0


def test_shadow_list_is_split_on_top_level_commas(tmp_path):
    css = tmp_path / "t.css"
    css.write_text(
        ":root { --accent: #abcdef; }\n"
        ".widget {\n"
        "  box-shadow: 0 0 0 1px rgba(1, 2, 3, 0.5) inset, 0 0 14px rgba(4, 5, 6, 0.25);\n"
        "}\n",
        encoding="utf-8",
    )
    fx = theme_module.effects("t", tmp_path, {"accent": "#abcdef"})
    assert fx["inset_color"] == "#80010203"
    assert fx["inset_width"] == 1.0
    assert fx["glow_color"] == "#40040506"
    assert fx["glow_blur"] == 14.0


def test_var_in_a_shadow_is_looked_up(tmp_path):
    css = tmp_path / "t.css"
    css.write_text(".widget h3 { color: var(--accent); }\n", encoding="utf-8")
    fx = theme_module.effects("t", tmp_path, {"accent": "#123456"})
    assert fx["heading_color"] == "#123456"


def test_every_shipped_theme_parses():
    for path in sorted(THEMES.glob("*.css")):
        colours = theme_module.load(path.stem, THEMES)
        fx = theme_module.effects(path.stem, THEMES, colours)
        assert set(fx) == set(theme_module.NO_EFFECTS)
        assert theme_module.metrics(path.stem, THEMES)["tile_radius"] >= 0
