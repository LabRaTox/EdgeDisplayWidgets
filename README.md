# Edge Dashboard

![Edge Dashboard](docs/demo.gif)

Modular kiosk dashboard for the **Corsair Xeneon Edge 14.5"** (2560×720)
secondary touch display. Runs as a local FastAPI server, rendered fullscreen
by a Chromium kiosk on a second monitor. Built and tested on
[CachyOS](https://cachyos.org/) (Arch-based) with an NVIDIA GPU, but the
backend is portable to any Linux distro.

- **Live widgets**: CPU / RAM / GPU / network / temperature sensors, disk
  usage, top processes, clock, weather (Open-Meteo), media controls
  (MPRIS), YouTube tiles, smart lights (Govee + Tuya), quick actions,
  pomodoro, notes.
- **Pages + swipe navigation**: arrange widgets in CSS-Grid layouts across
  multiple pages; horizontal swipe between them on the touchscreen.
- **In-browser layout editor**: drag, resize, add, remove widgets and pages
  without editing YAML.
- **Themes**: cyberpunk, clean, steampunk, light, toxic, nightclub,
  industrial — drop a CSS file to add more.
- **i18n**: English / German out of the box, auto-detected from the
  browser; per-user override persisted to localStorage.
- **Hot-reload**: settings saved through the UI are written back to
  `config.local.yaml` and applied without a restart.

## Touch gestures

The dashboard is designed for touch input — there are no visible menu
buttons. Everything is reachable via a small set of gestures:

| Gesture | Action |
|---------|--------|
| Horizontal swipe (or click + drag) | Switch between pages |
| Tap on a page indicator dot (bottom centre) | Jump to that page |
| **Swipe up from the bottom edge** | Open the settings sheet |
| **Long-press a page indicator dot** | Open the settings sheet |
| Tap × / backdrop on the settings sheet | Close it |

Inside the settings sheet, the `Layout` tab → "Enable edit mode" turns
the dashboard into a visual editor for moving, resizing, adding, and
removing widgets and pages.

## Architecture

The codebase follows a **module registry pattern**. Each widget = one
backend producer (`backend/modules/<x>.py` subclassing `Module`, decorated
with `@register_module`) + one frontend consumer
(`frontend/js/widgets/<x>.js` calling `registerWidget`). Data flows
backend → hub → WebSocket → all matching widget instances. Adding a widget
requires no changes to the core scaffolding.

## Requirements

### Operating system

- **Linux** with systemd (Arch / CachyOS reference; Fedora / Ubuntu work
  if you adapt the package names).
- Wayland or X11 session for the kiosk display detection (Sway, Hyprland,
  KDE Plasma, GNOME — all supported via either `wlr-randr` or `xrandr`).

### Hard dependencies

| Component | Purpose | Arch package |
|-----------|---------|--------------|
| Python ≥ 3.11 | runtime | `python` |
| [uv](https://github.com/astral-sh/uv) | virtualenv + dependency manager | `uv` |
| Chromium-compatible browser | kiosk renderer | `chromium`, `google-chrome`, or `brave-browser` |
| `systemd` | user service | (preinstalled) |

```bash
sudo pacman -S python uv chromium
```

### Optional dependencies (per module)

| Module | Needs | Arch package | Notes |
|--------|-------|--------------|-------|
| `nvidia` | NVIDIA driver + nvml | `nvidia`, `nvidia-utils` | Falls back to "no GPU detected" if absent — safe to leave enabled. |
| `sensors` | `/sys/class/hwmon` populated | `lm_sensors` | Run `sudo sensors-detect` once. AMD CPUs need `k10temp` autoloaded. |
| `media` | D-Bus session bus + an MPRIS player | (preinstalled) | Works with Spotify, MPV, browsers via the [MPRIS extension](https://github.com/F-Hauri/Plasma-Browser-Integration), VLC, etc. |
| `weather` | internet access | — | Uses Open-Meteo's free, key-less API. |
| `youtube` | internet access | — | Fetches oEmbed metadata; no API key needed. |
| `smart_lights` | Govee and/or Tuya account | — | API keys configured per provider (see below). |
| `quick_actions` | varies per action | `libnotify` for `notify-send`, etc. | Each action declares its own `command`. |

### KDE Plasma 6 (optional)

If you run KDE Plasma 6 on Wayland and want deterministic kiosk window
placement, also install:

```bash
sudo pacman -S kwriteconfig5 qt6-tools     # provides kwriteconfig6 + qdbus6
```

`scripts/kiosk.sh` detects KDE automatically and installs a KWin window
rule per launch — see [Kiosk display](#kiosk-display-setup).

## Installation

### Quick path (recommended)

```bash
git clone https://github.com/LabRaTox/EdgeDisplayWidgets.git
cd EdgeDisplayWidgets
./scripts/install.sh
```

The installer:

1. Runs `uv sync` to create `.venv/` and install Python deps locked in
   `uv.lock`.
2. Renders `systemd/edge-dashboard.service` into
   `~/.config/systemd/user/edge-dashboard.service` (with the project path
   and `uv` binary path baked in).
3. Reloads the systemd user daemon.

Re-running is idempotent.

### Starting the service

```bash
systemctl --user start  edge-dashboard         # one-shot run
systemctl --user enable --now edge-dashboard   # auto-start at graphical login
journalctl --user -u edge-dashboard -f         # live logs
```

The dashboard is now served at `http://127.0.0.1:8765/` — open it in any
browser to test.

### Launching the kiosk

```bash
./scripts/kiosk.sh
```

By default this picks the first connected output matching the Edge's
native `2560×720` resolution and opens Chromium fullscreen on it. See
[Kiosk display setup](#kiosk-display-setup) for overrides and
multi-monitor edge cases.

### Manual install (without the script)

```bash
uv sync                                # install deps into ./.venv
uv run python -m backend.main          # run on http://127.0.0.1:8765
uv run pytest                          # 130-test suite, should pass clean
```

To run as a system service without the installer, copy
`systemd/edge-dashboard.service` to `~/.config/systemd/user/`, replace
`__PROJECT_DIR__` with the absolute path of your checkout and `__UV__`
with `$(command -v uv)`, then `systemctl --user daemon-reload`.

## Configuration

The dashboard loads its config in this order:

1. `$EDGE_CONFIG` environment variable (explicit path — useful for tests).
2. `config.local.yaml` in the project root, if it exists.
3. `config.yaml` (the committed template).

**Workflow**: edit settings through the UI (swipe up from the bottom
edge, or long-press a page indicator dot — see [Touch gestures](#touch-gestures)).
Changes persist to `config.local.yaml`, which is gitignored. The committed
`config.yaml` stays as a clean template.

### Top-level schema

```yaml
server:
  host: "127.0.0.1"    # bind address — localhost = kiosk on same machine only
  port: 8765

logging:
  level: "INFO"        # TRACE | DEBUG | INFO | WARNING | ERROR | CRITICAL
  json: false          # true ⇒ one JSON object per line (for journald parsing)

default_theme: "cyberpunk"   # cyberpunk | clean | steampunk | light | toxic | nightclub | industrial

modules: { ... }       # per-module settings (next section)
pages:   [ ... ]       # page layouts (last section)
```

### Module configuration

Each key under `modules:` matches a `Module` subclass's `name`. Common
fields: `enabled` (bool) and `interval` (seconds between polls). Module-
specific keys are forwarded to the module.

```yaml
modules:
  heartbeat:
    enabled: true
    interval: 1.0          # connection indicator at the top of the dashboard

  system:                  # CPU + RAM + network counters via psutil
    enabled: true
    interval: 1.0

  nvidia:                  # nvml-based GPU stats
    enabled: true
    interval: 1.0

  sensors:                 # /sys/class/hwmon temperatures
    enabled: true
    interval: 2.0

  media:                   # MPRIS player control (Spotify, browsers, MPV, …)
    enabled: true
    interval: 0.5

  weather:
    enabled: true
    interval: 600          # Open-Meteo recommends ≥ 10 min between polls
    name: ""
    lat: 0
    lon: 0
    timezone: "auto"
    units: "metric"        # metric | imperial

  youtube:
    enabled: true
    interval: 3600         # oEmbed metadata rarely changes — once an hour is plenty
    entries:
      - "https://www.youtube.com/watch?v=dQw4w9WgXcQ"   # video URL
      - "fh-i7gw4Dwg"                                   # bare 11-char ID
      - "https://www.youtube.com/playlist?list=PL..."   # playlist

  disk_usage:
    enabled: true
    interval: 30
    min_size_gb: 1.0       # hide tiny mounts like /boot/efi
    # mounts: ["/", "/home"]    # optional allowlist; defaults to all real disks

  top_processes:
    enabled: true
    interval: 3
    limit: 6               # number of rows shown
```

### Quick actions

Configurable touch buttons that run a local shell command or fire an HTTP
request. The frontend only knows opaque IDs — actual commands stay in the
config. Edit them through the UI (`Settings → Aktionen`) or directly in
YAML:

```yaml
modules:
  quick_actions:
    enabled: true
    timeout_seconds: 30
    actions:
      # Shell actions — argv list, no shell interpreter, no globs.
      - id: lock
        label: "Lock"
        icon: "🔒"
        kind: shell
        command: ["loginctl", "lock-session"]

      - id: notify
        label: "Ping"
        icon: "🔔"
        kind: shell
        command: ["notify-send", "Edge Dashboard", "Hello!"]

      # `confirm: true` triggers the themed confirm dialog before running.
      - id: reboot
        label: "Reboot"
        icon: "🔄"
        kind: shell
        command: ["systemctl", "reboot"]
        confirm: true

      # HTTP action (e.g. Home Assistant)
      - id: lights_off
        label: "Lights off"
        icon: "💡"
        kind: http
        method: POST
        url: "http://homeassistant.local:8123/api/services/light/turn_off"
        headers:
          Authorization: "Bearer YOUR_LONG_LIVED_TOKEN"
        json:
          entity_id: "all"
```

### Smart lights

Govee and/or Tuya devices appear as a single unified list in the widget.

```yaml
modules:
  smart_lights:
    enabled: true
    interval: 30
    govee:
      # Govee API key: Govee Home app → Profile → "Apply for API Key".
      # Free tier ~10 000 requests/day — far above what this widget uses.
      api_key: "YOUR-GOVEE-API-KEY"
    tuya:
      # Covers Smart Life, Tuya Smart, Antela and most Tuya-rebranded OEMs.
      # Setup at https://iot.tuya.com:
      #   1. Sign up + create a Cloud project (free)
      #   2. Devices tab → "Link Tuya App Account" → scan QR with Smart Life
      #   3. Copy Access ID / Access Secret from "Authorization Key"
      #   4. The linked App Account's UID is shown after the QR link step
      client_id: "YOUR-TUYA-CLIENT-ID"
      secret:    "YOUR-TUYA-SECRET"
      uid:       "YOUR-TUYA-UID"
      region:    "eu"       # eu | us | cn | in (closest to your account)
```

Leave either block empty (`api_key: ""`) to disable that provider — the
widget shows a "not configured" hint instead of erroring out.

### Pages and widget placement

Each page is a CSS-Grid container. `grid.columns` and `grid.rows` are
literal `grid-template-columns` / `grid-template-rows` values. Each
widget gets a 1-indexed `col` / `row` plus optional `colspan` / `rowspan`.
The optional `variant` is an opaque string the widget can branch on.

```yaml
pages:
  - id: main
    title: "Main"
    grid:
      # 1.66 / 1 / 1 / 1.66 ≈ 800 / 480 / 480 / 800 on the 2560-wide Edge
      columns: "minmax(0, 1.66fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.66fr)"
      rows: "32px 1fr 1fr"
    widgets:
      - { id: heartbeat, col: 1, row: 1, colspan: 4, rowspan: 1 }
      - { id: clock,     col: 1, row: 2 }
      - { id: cpu,       col: 2, row: 2 }
      - { id: gpu,       col: 3, row: 2 }
      - { id: media,     col: 4, row: 2, rowspan: 2 }
      - { id: weather,   col: 1, row: 3 }
      - { id: ram,       col: 2, row: 3 }
      - { id: network,   col: 3, row: 3 }

  - id: detail
    title: "Detail"
    grid:
      columns: "1fr 1fr"
      rows: "1fr 1fr"
    widgets:
      - { id: cpu,     col: 1, row: 1, variant: detail }
      - { id: gpu,     col: 2, row: 1, variant: detail }
      - { id: network, col: 1, row: 2 }
      - { id: sensors, col: 2, row: 2 }
```

In practice it's easier to set this up visually with the **layout editor**:
open the settings sheet, tab `Layout` → "Enable edit mode". Drag to move,
resize from the bottom-right handle, `×` to remove, `+` to add widgets
or pages.

## Available widgets

| Widget | Backend module | Description |
|--------|----------------|-------------|
| `heartbeat` | `heartbeat` | Connection status + uptime |
| `clock` | none (frontend-only) | Time + locale-formatted date |
| `cpu` | `system` | Per-core CPU usage + sparkline |
| `ram` | `system` | Memory usage |
| `network` | `system` | RX/TX rate + dual sparkline |
| `gpu` | `nvidia` | NVIDIA usage + VRAM + temp + power |
| `sensors` | `sensors` | hwmon temperature sensors |
| `disk_usage` | `disk_usage` | Per-mountpoint fill bars |
| `top_processes` | `top_processes` | Top-N CPU consumers |
| `weather` | `weather` | Current + hourly forecast |
| `media` | `media` | MPRIS player controls + album art |
| `youtube` | `youtube` | Tile grid; tap opens fullscreen embed |
| `quick_actions` | `quick_actions` | Configurable touch buttons |
| `smart_lights` | `smart_lights` | Govee + Tuya unified control |
| `pomodoro` | none (frontend-only) | Pomodoro timer + stopwatch |
| `notes` | (REST `/api/notes`) | Tabbed plain-text notepad |

## Kiosk display setup

`scripts/kiosk.sh` picks the output matching `EDGE_WIDTH × EDGE_HEIGHT`
(default `2560×720`). Detection order:

1. `$EDGE_OUTPUT` (forces a specific connector, e.g. `DP-3`).
2. **Wayland**: `wlr-randr` — first output with that mode marked
   `current`. Works on wlroots-based compositors (Sway, Hyprland, river,
   labwc, …).
3. **X11 / XWayland**: `xrandr` — first connected output with that
   geometry.
4. **Fallback**: plain `--kiosk` on the primary display.

### Override examples

```bash
EDGE_OUTPUT=DP-3 ./scripts/kiosk.sh         # force a connector
EDGE_WIDTH=1920 EDGE_HEIGHT=1080 …          # different panel
EDGE_URL=http://my-host:8765 …              # remote dashboard
EDGE_BROWSER=brave-browser …                # different Chromium build
```

### KDE Plasma 6 (Wayland)

KWin Wayland ignores `--window-position` from XWayland clients and
applies its own placement policy — which often lands the kiosk on the
primary monitor at cold boot, before the target output is fully
arranged. To make placement deterministic, `kiosk.sh` writes a
per-session KWin window rule to `~/.config/kwinrulesrc` on every launch:

- Match: `chrome-<host>` substring on the window's resource class (so the
  rule survives port / path changes in `EDGE_URL`).
- Force: `output`, `position`, `size`, `fullscreen`,
  `skip taskbar/pager/switcher`.
- Reload via `qdbus6 org.kde.KWin reconfigure`.

The rule is upserted by id — your other KWin rules stay intact. To remove
it, delete the `[edge-dashboard-kiosk]` group from `kwinrulesrc`. The
behaviour only activates when `kwriteconfig6` + `qdbus6` are present
(Plasma 6); on other compositors `kiosk.sh` skips it silently.

## Adding a widget

The registry pattern means new widgets need **zero changes** to the core:

1. **Backend producer** — drop a `Module` subclass in
   `backend/modules/<name>.py`, decorate with `@register_module`. Override
   `setup()` (one-time init), `poll()` (returns a JSON-serialisable dict),
   and optionally `teardown()`.
2. **Frontend consumer** — drop a class in `frontend/js/widgets/<name>.js`
   that calls `registerWidget(name, class)`. The class needs at least
   `mount(el, initial, meta)` and `update(data, moduleName, ts)`, plus
   a static `modules = [...]` listing which backend modules to subscribe
   to. `destroy()` is called on teardown.
3. **Wire it up** — add the module to `config.yaml` under `modules:` and
   place the widget on a page (or do it in the layout editor at runtime).

Frontend-only widgets (no backend producer) work too: just set
`static modules = []`. See `clock.js`, `pomodoro.js`, `notes.js`.

## Themes

Drop a `<name>.css` file in `frontend/css/themes/` and it appears in the
settings sheet automatically — themes are auto-discovered by the backend
from the directory listing. CSS files should define the same custom
properties as `cyberpunk.css` (the canonical reference).

## Languages

UI strings live in `frontend/locales/<code>.json`, fetched at boot by
`frontend/js/i18n.js`. Detection: `navigator.languages` → first match in
`SUPPORTED` → fallback to English. The user can override in
`Settings → Design → Sprache`; the override persists in `localStorage`.

Adding a language: drop a new JSON file alongside `en.json` / `de.json`,
extend `SUPPORTED` in `frontend/js/i18n.js`. That's it.

## Development

```bash
uv sync                              # set up .venv
uv run python -m backend.main        # dev server with auto-restart via uvicorn flags
uv run pytest                        # 130-test suite
uv run ruff check                    # lint
uv run ruff format                   # format
```

Project layout:

```
backend/
  main.py             FastAPI app, lifespan, routes
  hub.py              Module runner, WebSocket fanout, hot-reload
  config.py           Pydantic schema (single source of truth)
  notes.py            REST store for the notes widget
  modules/            Module subclasses — one file per backend producer
frontend/
  index.html
  js/
    app.js            Bootstrap: fetch config, mount widgets, route WS frames
    registry.js       registerWidget / getWidget
    i18n.js           Tiny t() helper
    ws.js             WebSocket client with auto-reconnect
    swiper.js         Page swiping + long-press + bottom-edge swipe-up
    theme.js          Theme manager + settings sheet
    layout_editor.js  In-browser drag/resize/add layout editor
    confirm.js        Themed confirm dialog
    widgets/          One file per frontend consumer
    settings/         Editor sub-views (currently just quick_actions)
    lib/              Sparkline (in-house, no dependencies)
  css/
    base.css          Layout + general components
    widgets.css       Per-widget styles
    fonts.css
    themes/           One file per theme
  locales/            One JSON file per language
config.yaml           Committed template
config.local.yaml     Gitignored, written by the UI
systemd/              User unit template
scripts/
  install.sh          Idempotent installer (uv sync + systemd unit)
  kiosk.sh            Chromium kiosk launcher with output detection
tests/                pytest, asyncio mode auto
```

## License

MIT — see [LICENSE](LICENSE).

## Support

If this is useful to you, you can support development on
[Ko-Fi](https://ko-fi.com/labratox).

![Edge Dashboard](docs/screenshots/Shot_2.png)
