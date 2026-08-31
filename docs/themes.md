# Writing a theme

A theme is one CSS file in `frontend/css/themes/`. Drop it there and it shows
up in the settings window: the backend lists the directory, the window renders
a preview by loading the actual stylesheet, so there is nothing to register
anywhere.

```bash
cp frontend/css/themes/clean.css frontend/css/themes/mytheme.css
```

Pick it under **Design** in the settings window, or set `default_theme:
mytheme` in the config. No restart, the display switches over as soon as the
setting is saved.

## What a theme actually is

`base.css` defines every variable with a working value first, and the theme is
loaded after it. A theme therefore **overrides**, it does not have to be
complete. Three lines are a valid theme:

```css
:root {
  --bg: #101418;
  --fg: #e8eef4;
  --accent: #7dd3fc;
}
```

Everything else keeps the values from `base.css`, which is why a half-finished
theme looks unfinished rather than broken.

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
| `--transition` | duration of the built-in transitions (`220ms ease`) |

Two more are optional, and only the quick action tiles read them. They fall
back to a shade of `--card-bg` and to `--fg`, so leaving them out is fine:
`--qa-tile-bg` and `--qa-tile-fg`.

A theme is free to go beyond variables. `cyberpunk.css` adds a scanline
overlay through `body::after`, a glow on `.widget h3` and a short flicker when
a widget mounts. Anything in the page is fair game, the variables are simply
the part that needs no knowledge of the markup.

## What to watch out for

**Contrast on a display you look at from the side.** The Xeneon Edge sits
below the monitors, usually at an angle. `--fg-muted` at 40 % opacity reads
fine straight on and disappears at 30 degrees.

**The display is 2560x720.** Widgets are wide and short. A theme that adds
vertical padding eats the space the charts need.

**Do not animate continuously.** A pulsing border or a moving gradient costs
about twenty points of CPU on this machine, permanently, for something nobody
is watching from a metre away. The animations in `cyberpunk.css` run once when
a widget mounts and then stop. See the measurements in the README.

**Test both languages.** German labels are longer than English ones, and a
theme that tightens the tiles will show it there first.

## Checking it

```bash
systemctl --user restart edge-dashboard   # picks up a new file in the theme list
```

Open `http://127.0.0.1:8765/` in a browser to iterate without the kiosk
window; a plain reload is enough after each edit. `clean.css` is the smallest
theme to read, `cyberpunk.css` the one that shows how far a theme can go.

---

[Writing a widget](widgets.md) · [README](../README.md) · [Deutsch](themes.de.md)
