# Writing a theme

A theme is one CSS file in `frontend/css/themes/`. The file being in that
directory is the registration: the backend lists it, and the settings window
renders a preview by loading the actual stylesheet.

```bash
cp frontend/css/themes/clean.css frontend/css/themes/mytheme.css
```

Pick it under **Design** in the settings window, or set `default_theme:
mytheme` in the config. No restart, the display switches over as soon as the
setting is saved.

## What a theme actually is

Every variable has a working base value, and the theme is laid over it. A
theme therefore **overrides**, it does not have to be complete. Three lines
are a valid theme:

```css
:root {
  --bg: #101418;
  --fg: #e8eef4;
  --accent: #7dd3fc;
}
```

Everything else keeps its base value; the list is `BASE` in
`shell/qml_kiosk/theme.py`. That is why a half-finished theme looks unfinished
rather than broken.

## The variables

| Variable | What it colours |
|---|---|
| `--bg` | the page behind everything |
| `--fg` | normal text |
| `--fg-muted` | labels, units, secondary lines |
| `--accent` | the main figure of a widget, active states, sparklines |
| `--accent-2` | the second series where there are two (upload in the network widget) |
| `--ok` `--warn` `--bad` | states: connected, warning, critical |
| `--card-bg` | the surface of a widget tile |
| `--card-border` | its border |
| `--font-ui` | interface text |
| `--font-mono` | numbers, everything that should not jump around while counting |
| `--font-display` | the large figures |
| `--gap` | space between tiles (`8px`) |

A theme may go beyond variables, but only some of it reaches the display: the
kiosk does not render CSS, it reads the file. What it reads is the inset,
corner radius, background and cut corner of `.widget`, the size, weight,
letter spacing, colour and text shadow of `.widget h3`, the font weight of
`.clock-time`, the shadow on `.metric-big`, and the scanlines a theme lays
over the page with `repeating-linear-gradient`.

Everything else belongs to a browser rendering and has no effect on the panel,
animations and pseudo-element decorations among them. What is read is listed
in `shell/qml_kiosk/theme.py`.

## What to watch out for

**Contrast on a display you look at from the side.** The Xeneon Edge sits
below the monitors, usually at an angle. `--fg-muted` at 40 % opacity reads
fine straight on and disappears at 30 degrees.

**The display is 2560x720.** Widgets are wide and short. A theme that adds
vertical padding eats the space the charts need.

**Animations stay in the file.** The kiosk runs none of them, so a pulsing
border does not move on the display. That is deliberate: a surface that keeps
moving costs about twenty points of CPU on this machine, for something nobody
is watching from a metre away.

**Test both languages.** German labels are longer than English ones, and a
theme that tightens the tiles will show it there first.

## Checking it

```bash
systemctl --user restart edge-dashboard   # picks up a new file in the theme list
systemctl --user restart edge-kiosk       # after each edit to the file
```

The theme is read at startup, so restarting the kiosk shows the change. To
avoid switching the display every time, render the window beside it:

```bash
cd shell
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m qml_kiosk.main --windowed
```

`clean.css` is the smallest theme to read, `cyberpunk.css` the one that shows
how far a theme can go.

If an edit has no effect, check the list above: only part of a stylesheet
reaches the display.

---

[Writing a widget](widgets.md) · [Why it looks the way it does](decisions.md) · [README](../README.md) · [Deutsch](themes.de.md)
