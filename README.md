# Edge Dashboard

*[Deutsche Fassung](README.de.md)*

![The Edge Dashboard on a Corsair Xeneon Edge: network, clock, weather, CPU, GPU and RAM widgets](docs/screenshots/kiosk-main.png)

Dashboard for the **Corsair Xeneon Edge 14.5"** (2560x720), the second touch
display that sits under the monitors. It runs on Linux, developed and used
daily on [CachyOS](https://cachyos.org/) (Arch Linux) with KDE Plasma and an
NVIDIA GPU. Three parts: a local FastAPI server, a kiosk window in QML that
fills the display, and **EDGE//DASH**, a separate desktop application for the
settings.

- **Live widgets**: CPU / RAM / GPU / network / temperature sensors, single
  sensors as a curve or a dial, disk usage, top processes, clock, weather
  (Open-Meteo), media controls (MPRIS), YouTube tiles, smart lights
  (Govee + Tuya), quick actions, pomodoro, notes.
- **Pages + swipe navigation**: arrange widgets in CSS-Grid layouts across
  multiple pages; horizontal swipe between them on the touchscreen.
- **Settings window**: themes, module options, weather, YouTube, the quick
  action deck and the page layout, edited in a desktop application rather than
  on the touch strip. It lives in the tray and in the application menu.
- **Widget variants**: a widget can offer more than one look. The metric
  widgets know `compact`, which drops the chart for small tiles and costs no
  drawing time at all.
- **Themes**: cyberpunk, clean, steampunk, light, toxic, nightclub,
  industrial. Drop a CSS file to add more.
- **i18n**: English / German out of the box; the display's language is a
  config value, the window has its own under `Language`.
- **Hot-reload**: what the settings window saves is written to
  `config.local.yaml` and announced over the WebSocket, so the display follows
  along without a restart or a reload.

Guides for extending it: [Writing a widget](docs/widgets.md) and
[Writing a theme](docs/themes.md). Why some of it is the way it is:
[Why it looks the way it does](docs/decisions.md).

## Touch gestures

The display shows; it is not configured on itself. What is left on the
touchscreen is what a finger is good at:

| Gesture | Action |
|---------|--------|
| Horizontal swipe (or click + drag) | Switch between pages |
| Tap on a page indicator dot (bottom centre) | Jump to that page |
| Tap a quick-action tile | Run it |

Everything else, meaning themes, module options, the action deck and the page layout,
lives in the settings window (`gui/`, see [Settings window](#settings-window)).
That is a deliberate split: editing an argv list or a grid template with a
finger on a 2560×720 strip was the worst part of the old design.

## Architecture

Three processes, each doing one thing:

| Process | What it is | Runs on |
|---------|-----------|---------|
| `backend/` | FastAPI + the module hub, the only writer of the config | project virtualenv (`uv`) |
| `shell/qml_kiosk` | the kiosk window on the Xeneon | **system** Python + system PySide6 |
| `gui/` | EDGE//DASH, the settings window | Tauri 2 + React |

The kiosk and the settings window are both plain clients of the backend over
HTTP and one WebSocket. Keeping them apart means the settings still open when
the kiosk is not running, and a crashed renderer never takes the data
collection with it.

The backend also carries the tray icon (`backend/tray.py`, over D-Bus rather
than a GUI toolkit) and starts the settings window from it. It is the only one
of the three that always runs, which makes it the only sensible place for it.

The code follows a **module registry pattern**. Each widget = one backend
producer (`backend/modules/<x>.py` subclassing `Module`, decorated with
`@register_module`) + one kiosk view (`shell/qml_kiosk/qml/widgets/<X>.qml`)
+ one manifest (`widgets/<x>.json`) that makes it known to the layout editor.
Data flows backend → hub → WebSocket → all matching widget instances. Adding
a widget requires no changes to the core scaffolding.

A module produces its data on a clock (`interval`), by pushing when its source
signals it (`await self.emit(...)`, as MPRIS property changes and systemd unit
state), or both. Unchanged payloads are not re-sent unless the module sets
`dedupe = False`, which the sample-stream modules do because a sparkline needs
a frame even when the value repeats.

## Requirements

### Operating system

- **Linux** with systemd (Arch / CachyOS reference; Fedora / Ubuntu work
  if you adapt the package names).
- Wayland or X11 session for the kiosk display detection (Sway, Hyprland,
  KDE Plasma, GNOME, all supported via either `wlr-randr` or `xrandr`).

### Hard dependencies

| Component | Purpose | Arch package |
|-----------|---------|--------------|
| Python ≥ 3.11 | runtime | `python` |
| [uv](https://github.com/astral-sh/uv) | virtualenv + dependency manager | `uv` |
| PySide6 (system-wide) | the kiosk window (Qt Quick) and the video player (Qt WebEngine) | `pyside6` |
| `systemd` | user services | (preinstalled) |

```bash
sudo pacman -S python uv pyside6
```

Node and Rust are needed only to build the settings window; the installer says
so if they are missing and carries on without it.

```bash
sudo pacman -S nodejs npm rust webkit2gtk-4.1
```

### Optional dependencies (per module)

| Module | Needs | Arch package | Notes |
|--------|-------|--------------|-------|
| `nvidia` | NVIDIA driver + nvml | `nvidia`, `nvidia-utils` | Falls back to "no GPU detected" if absent, safe to leave enabled. |
| `sensors` | `/sys/class/hwmon` populated | `lm_sensors` | Run `sudo sensors-detect` once. AMD CPUs need `k10temp` autoloaded. |
| `media` | D-Bus session bus + an MPRIS player | (preinstalled) | Works with Spotify, MPV, browsers via the [MPRIS extension](https://github.com/F-Hauri/Plasma-Browser-Integration), VLC, etc. |
| `weather` | internet access | — | Uses Open-Meteo's free, key-less API. |
| `youtube` | internet access | — | Fetches oEmbed metadata; no API key needed. |
| `smart_lights` | Govee and/or Tuya account | — | API keys configured per provider (see below). |
| `quick_actions` | varies per action | `libnotify` for `notify-send`, etc. | Each action declares its own `command`. |

### Desktop environments

Built and used on KDE Plasma 6 (Wayland). What the other environments need:

| Session | Kiosk out of the task list | Tray icon |
|---|---|---|
| **Any X11 session** | automatic | yes |
| **KDE Plasma** (Wayland) | automatic, a KWin rule | yes |
| **Hyprland** | a snippet to source, the installer writes it | yes (Waybar and others) |
| **Sway / i3** | partly, see below | yes (Waybar and others) |
| **GNOME** (Wayland) | not possible | needs an extension |
| **Others** (Wayland) | not automatic | usually yes |

Two things are environment-specific, and both are cosmetic. The dashboard
itself runs everywhere.

**Keeping the kiosk out of the task manager.** On X11 the window asks for this
itself: it sets `_NET_WM_WINDOW_TYPE_UTILITY`, which every window manager
understands, so an X11 session needs no configuration at all. Wayland has no
equivalent, because xdg-shell knows no window types, so the compositor has to
be told instead. `scripts/window-rule.sh` does that, and the installer runs it:

```bash
./scripts/window-rule.sh
systemctl --user restart edge-kiosk    # applies to windows opened afterwards
```

It writes a KWin rule on Plasma, a `windowrulev2` snippet on Hyprland (which
has to be sourced from `hyprland.conf`, the script says so), and a `for_window`
line for Sway. Sway has no skip-taskbar flag as such, so there the window is
marked and a bar can filter it. GNOME under Wayland offers no way at all; the
window will appear in the overview.

`EDGE_KIOSK_NO_FOCUS=1 ./scripts/window-rule.sh` additionally makes the kiosk
refuse the keyboard focus, so touching the dashboard leaves the keyboard where
it was. Off by default, because Wayland offers no way to take pointer input
while refusing the keyboard: without focus every text field on the kiosk is
read-only, which makes the notes widget pointless.

**The tray icon** uses StatusNotifierItem over D-Bus, which Plasma, Waybar,
XFCE, Cinnamon and most others implement. GNOME needs the *AppIndicator and
KStatusNotifierItem Support* extension. Without any of it the backend runs
unchanged and the settings window still opens from the application menu.

## Installation

### Quick path (recommended)

```bash
git clone https://github.com/LabRaTox/EdgeDisplayWidgets.git
cd EdgeDisplayWidgets
./scripts/install.sh
```

That is the whole installation. When it finishes, the dashboard is on the
display, the tray icon is there, the settings window is in the application
menu, and everything comes back at the next login. Nothing else has to be run
by hand.

The installer, step by step:

1. Checks what is present and names the package for anything missing:
   `uv`, a systemd user session, the system PySide6, and a panel that can show
   a tray icon.
2. Runs `uv sync` to create `.venv/` from `uv.lock`.
3. Builds the settings window, if `npm` and `cargo` are there. Without them
   everything else still works, only the settings UI is missing.
4. Installs its icon and menu entry into `~/.local/share`, and refreshes the
   menu cache.
5. Tells the compositor to keep the kiosk window out of the task list, in
   whatever way that compositor understands (see
   [Desktop environments](#desktop-environments)).
6. Renders both systemd units into `~/.config/systemd/user/`, with the project
   path and the `uv` path baked in.
7. Enables and starts them, then reports whether they came up.

Re-running is idempotent. Options:

```bash
./scripts/install.sh --no-build      # skip building the settings window
./scripts/install.sh --no-start      # install, but do not start anything
./scripts/install.sh --no-autostart  # start now, but not at the next login
```

The kiosk window needs the **distribution's** PySide6, not a wheel in the
virtualenv. The window itself is Qt Quick. For a video it starts a process of
its own on the system Qt WebEngine, which is the build that carries the codecs
YouTube plays.

```bash
sudo pacman -S pyside6           # Arch / CachyOS
```

### Afterwards

```bash
systemctl --user status edge-dashboard edge-kiosk         # what is running
journalctl --user -u edge-dashboard -u edge-kiosk -f      # live logs
systemctl --user stop   edge-dashboard edge-kiosk         # stop both
```

![The EDGE//DASH settings window showing the theme picker](docs/screenshots/settings-theme.png)

### Launching the kiosk by hand

```bash
PYTHONPATH=$PWD/shell /usr/bin/python3 -m qml_kiosk.main
```

It picks the output matching the Edge's native `2560×720` and fills it. If
the display appears later than the window (a cold boot), the window moves over
by itself when it shows up. `--help` lists the overrides; see
[Kiosk display setup](#kiosk-display-setup).

### Settings window

The installer builds it. These are the commands behind that, for development
or for a rebuild after changing the UI:

```bash
cd gui
npm install
npm run tauri dev                 # dev server on http://localhost:5173
npm run tauri build -- --no-bundle # just the binary, which is all that is used
npm run tauri build               # additionally a .deb (and an AppImage)
```

Needs Node ≥ 20, Rust, and `webkit2gtk-4.1`. Running from the checkout needs
no bundle: the binary in `src-tauri/target/release/` is what the tray and the
menu entry point at, which is why the installer passes `--no-bundle`. The full
build also produces a `.deb`; its AppImage step currently fails in
`linuxdeploy` on Arch.

The window talks to the same backend over HTTP, and nothing about it is
required for the display to run. It can also be opened as a plain page during
development, which is what the dev server is for.

![The quick action deck being edited in the settings window](docs/screenshots/settings-actions.png)

There are two ways in, and the installer sets up both: the **tray icon** and
the **EDGE//DASH entry in the application menu**. A click on the tray opens
the window, a right click gives a small menu. The window is a single instance,
so opening it again brings the existing one forward instead of stacking up
another. Finding no backend, it starts the services itself rather than only
reporting that nothing answers.

The icon and the menu entry come from `scripts/install-desktop.sh`. Without
them a task manager has no `.desktop` file to match the window's app id
(`edgedash`) against and shows a question mark instead of an icon:

```bash
./scripts/install-desktop.sh    # into ~/.local/share, no root needed
```

The icon itself is drawn by `backend/brand.py`, the same code the tray uses,
so the two cannot drift apart. After changing it:

```bash
uv run python scripts/make-icon.py    # re-renders every icon file
./scripts/install-desktop.sh          # copies them into the icon theme
```

The icon needs the settings window to have been built, and the tray starts the
binary it finds, in this order:

1. `$EDGE_GUI_BINARY`
2. `/usr/bin/edgedash`, `/usr/local/bin/edgedash` (installed from the `.deb`)
3. `gui/src-tauri/target/release/edgedash`, then the debug build
4. `edgedash` anywhere on `$PATH`

Without a panel that speaks StatusNotifierItem, or without a session bus at
all, the tray is skipped and the backend runs on unchanged. `EDGE_TRAY=0` in
the unit turns it off deliberately.

### Autostart

**System** in the settings window switches the autostart for both user units
at once. It writes the same units `scripts/install.sh` renders and runs
`systemctl --user enable`/`disable` on them, deliberately without `--now`, so
the switch governs the next login and never restarts the backend that is
answering the request.

### Manual install (without the script)

```bash
uv sync                                # install deps into ./.venv
uv run python -m backend.main          # API on http://127.0.0.1:8765
uv run pytest                          # ~200 tests, should pass clean
```

To run as a service without the installer, copy both units from `systemd/`
into `~/.config/systemd/user/`, replacing `__PROJECT_DIR__` with the absolute
path of the checkout and `__UV__` with `$(command -v uv)`, then
`systemctl --user daemon-reload` and enable them. The kiosk unit deliberately
runs `/usr/bin/python3`, not the virtualenv, for the system PySide6.

## Configuration

The dashboard loads its config in this order:

1. `$EDGE_CONFIG` environment variable (explicit path, useful for tests).
2. `config.local.yaml` in the project root, if it exists.
3. `config.yaml` (the committed template).

**Workflow**: edit in the settings window, not in the file. What it saves
goes to `config.local.yaml`, which is gitignored, so the committed
`config.yaml` stays a clean template. The write is atomic and keeps the
replaced version as `config.local.yaml.bak`.

### Top-level schema

```yaml
server:
  host: "127.0.0.1"    # bind address, localhost means kiosk on this machine only
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

> **Edit in the settings window, not in the file.** Its **Module** view
> renders an input for every field a module declares: enabled and interval,
> plus whatever is module-specific (smart-light API keys, disk `min_size_gb`
> and mountpoints, the `top_processes` limit, quick-action timeouts). Secrets
> are masked and only overwritten when a new value is typed. The YAML below is
> the reference for what those fields mean, not a place you normally edit.
> A module declares them through `settings_schema` (see `SettingField` in
> `backend/modules/base.py`), and declaring one there is all it takes for the
> window to show it.

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
    interval: 3600         # oEmbed metadata rarely changes, once an hour is plenty
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

A **Stream-Deck-style tile grid**. Each tile runs a local shell command,
fires an HTTP request, launches a desktop app, or opens a folder of nested
tiles. The frontend only ever knows opaque action IDs, the actual
commands, URLs and HTTP headers stay in the backend config and never reach
the browser. Shell actions run via an argv list (no shell interpreter, so
no globbing / interpolation / pipes).

The deck lays tiles out on a fixed `columns` × `rows` grid (default 4 × 3)
and paginates the overflow with a pager strip. Tiles can span multiple
cells, carry their own colours, sit at a fixed cell, and show a live
on/off status dot.

**Editing.** In the settings window under `Aktionen`: the deck is drawn as a
grid, clicking a cell selects the tile and the panel beside it holds icon,
label, kind, command or URL, HTTP headers, confirmation, colours, size,
position and the live-status probe. `Ausführen` fires the action so you can
check it without leaving the editor, and a double click descends into a
folder.

![The quick action deck on the display](docs/screenshots/kiosk-actions.png)

#### YAML schema

```yaml
modules:
  quick_actions:
    enabled: true
    interval: 60             # action list is static; poll drives live-status refresh
    timeout_seconds: 30      # max runtime per shell/http action
    status_timeout_seconds: 8   # max runtime per live-status probe
    columns: 4               # deck grid width  (1..8)
    rows: 3                  # deck grid height (1..8); overflow paginates
    actions:
      # --- Shell action, argv list, no shell interpreter, no globs.
      - id: lock
        label: "Lock"
        icon: "🔒"            # emoji/text, or "ti:<name>" for a Tabler icon
        kind: shell
        command: ["loginctl", "lock-session"]

      # --- confirm:true shows the themed confirm dialog before running.
      - id: reboot
        label: "Reboot"
        icon: "🔄"
        kind: shell
        command: ["systemctl", "reboot"]
        confirm: true

      # --- Launch a GUI program. detach:true fires it in a new session and
      #     returns at once, so the timeout can't kill the started app.
      - id: launch_firefox
        label: "Firefox"
        icon: "app:firefox"   # resolved via /api/apps/icon/<name>
        kind: shell
        command: ["firefox"]
        detach: true

      # --- HTTP action (e.g. Home Assistant). Headers stay backend-side.
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

      # --- A tile with custom appearance, a fixed grid cell, a 2×1 span,
      #     and a live-status probe. `state` (on/off/unknown) drives the dot.
      - id: vpn
        label: "VPN"
        icon: "ti:shield-lock"
        kind: shell
        command: ["nmcli", "connection", "up", "vpn"]
        color: "#1e293b"       # tile background (hex)
        text_color: "#38bdf8"  # icon + label colour (hex)
        w: 2                   # span 2 cells wide (1..4)
        h: 1                   # span 1 cell tall  (1..4)
        page: 0                # which deck page
        x: 0                   # cell column (omit x/y to auto-flow)
        y: 1                   # cell row
        status:                # probe config never leaves the backend
          kind: shell
          command: ["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"]
          match: "^vpn$"       # matches → on, else off; probe error → unknown

      # --- A folder: opens a nested sub-deck of its own tiles.
      - id: system
        label: "System"
        icon: "ti:settings"
        kind: folder
        tiles:
          - id: suspend
            label: "Suspend"
            icon: "ti:moon"
            kind: shell
            command: ["systemctl", "suspend"]
```

Field notes:

- `icon`: emoji/plain text, `ti:<name>` for a vendored [Tabler](https://tabler.io/icons)
  icon, or `app:<name>` for a resolved desktop-app icon.
- `color` / `text_color`: hex only (`#rgb` or `#rrggbb`); omit to inherit
  the theme.
- `w` / `h`: tile span in grid cells (1..4). `page` / `x` / `y` pin it to
  a cell; leave `x` / `y` unset to auto-flow into the next free cell.
- `status`: an optional live probe (`shell` or `http`). With a `match` regex
  the state is `on` if the output matches, else `off`; without `match` it
  follows success (shell exit 0 / HTTP 2xx). A failing probe yields
  `unknown`. Only the derived `state` is sent to the frontend.
- `detach` (shell): launch fire-and-forget in a new session; use it for
  GUI programs that outlive the request.

### Smart lights

Govee and/or Tuya devices appear as a single unified list in the widget.

```yaml
modules:
  smart_lights:
    enabled: true
    interval: 30
    govee:
      # Govee API key: Govee Home app → Profile → "Apply for API Key".
      # Free tier ~10 000 requests/day, far above what this widget uses.
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

Leave either block empty (`api_key: ""`) to disable that provider. The
widget shows a "not configured" hint instead of erroring out.

### Pages and widget placement

Each page is a CSS-Grid container. `grid.columns` and `grid.rows` are
literal `grid-template-columns` / `grid-template-rows` values. Each
widget gets a 1-indexed `col` / `row` plus optional `colspan` / `rowspan`.
The optional `variant` picks one of the looks a widget offers. A widget
declares them in its manifest (`variants` in `widgets/<id>.json`), the backend
reads them when it scans the directory, and the layout editor offers exactly
those in a list. Leave it out for the widget's default look.

The metric widgets (cpu, gpu, ram, network, sensors, disk_usage) know
`compact`: the number and its subtitle. It is meant for small tiles. The chart
is never loaded in that variant, so it costs neither drawing time nor
memory.

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
      - { id: cpu,     col: 1, row: 1, variant: compact }
      - { id: gpu,     col: 2, row: 1, variant: compact }
      - { id: network, col: 1, row: 2 }
      - { id: sensors, col: 2, row: 2 }
```

In practice it's easier to set this up in the settings window under `Layout`:
pages as tabs, a preview locked to the display's 32:9 proportion, and the
column/row/span numbers for every widget beside it.

![Pomodoro, disks and sensors on the second page](docs/screenshots/kiosk-tools.png)

## Available widgets

| Widget | Backend module | Description |
|--------|----------------|-------------|
| `heartbeat` | `heartbeat` | Connection status + uptime |
| `clock` | none | Time + locale-formatted date |
| `cpu` | `system`, `sensors` | Per-core CPU usage, curve, and the temperature |
| `ram` | `system`, `sensors` | Memory usage, curve, and the temperature |
| `network` | `system` | RX/TX rate + dual sparkline |
| `gpu` | `nvidia` | NVIDIA usage + VRAM + temp + power |
| `sensors` | `sensors` | Every hwmon temperature as a table |
| `sensor_focus` | `sensors` | One or two picked sensors, as a curve or dials |
| `disk_usage` | `disk_usage` | Per-mountpoint fill bars |
| `top_processes` | `top_processes` | Top-N CPU consumers |
| `weather` | `weather` | Current + hourly forecast |
| `media` | `media` | MPRIS player controls + album art |
| `youtube` | `youtube` | Tile grid; a tap opens the video window |
| `quick_actions` | `quick_actions` | Stream-Deck tile grid: shell, HTTP and app-launch tiles, folders, live status |
| `smart_lights` | `smart_lights` | Govee + Tuya unified control |
| `pomodoro` | none | Pomodoro timer + stopwatch |
| `notes` | (REST `/api/notes`) | Tabbed plain-text notepad |

## Kiosk display setup

The kiosk window picks its output itself, in this order:

1. `--output` / `$EDGE_OUTPUT`: a connector name, e.g. `DP-4`.
2. The first screen whose resolution matches `--width × --height`
   (default `2560×720`).
3. The primary screen, as a fallback, and it moves over as soon as the real
   display appears.

```bash
edge-kiosk --output DP-4                 # force a connector
edge-kiosk --width 1920 --height 1080    # different panel
edge-kiosk --url http://my-host:8765     # remote backend
edge-kiosk --windowed                    # a normal window, for development
edge-kiosk --show-cursor                 # keep the mouse pointer visible
```

(`edge-kiosk` above is `PYTHONPATH=$PWD/shell /usr/bin/python3 -m qml_kiosk.main`.)

The kiosk window has no keyboard shortcuts; systemd starts and stops it. In
the video window, Esc closes the video. The cursor is hidden unless
`--show-cursor` is given.

### The window on the Xeneon

Qt places the window directly on the screen we picked. If no display with the
expected resolution is there at startup, the kiosk takes the primary screen
and moves over once the Xeneon appears.

The `[edge-dashboard-kiosk]` group in `~/.config/kwinrulesrc` keeps the window
out of the task list. It carries no geometry and is written by
`scripts/window-rule.sh`.

Why the window is QML and not a browser is in
[Why it looks the way it does](docs/decisions.md).

## Adding a widget

The full walkthrough is in [Writing a widget](docs/widgets.md). In short:

The registry pattern means new widgets need **zero changes** to the core:

1. **Backend producer**: drop a `Module` subclass in
   `backend/modules/<name>.py`, decorate with `@register_module`. Override
   `setup()` (one-time init), `poll()` (returns a JSON-serialisable dict),
   and optionally `teardown()`.
2. **Kiosk view**: drop a QML file in
   `shell/qml_kiosk/qml/widgets/<Name>.qml`. It is found by name:
   `disk_usage` is `DiskUsage.qml`. It needs at least a `moduleNames` property
   listing the modules it consumes and a `receive(module, data)` function.
3. **Manifest**: drop a `widgets/<name>.json`. The file existing is the
   registration; the layout editor lists what it finds there. It may declare
   `variants` and `options`.
4. **Wire it up**: add the module to `config.yaml` under `modules:` and
   place the widget on a page (or do it in the settings window's Layout view).

Widgets without a backend producer work too: leave `moduleNames` empty and
`modules` out of the manifest. The clock, the pomodoro and the notes do that.

## Themes

See [Writing a theme](docs/themes.md) for the variables and what to watch out
for. In short: drop a `<name>.css` file in `frontend/css/themes/` and it
appears in the settings window automatically. Themes are auto-discovered by the backend from
the directory listing, and the window previews each one by loading its actual
stylesheet. CSS files should define the same custom
properties as `cyberpunk.css` (the canonical reference).

## Languages

UI strings live in `frontend/locales/<code>.json`, read at boot by the kiosk
and by the settings window. The display's language is the config value
`default_language` (`auto` | `en` | `de`), set in the settings window under
`Design`; `auto` falls back to `LANG` from the environment. It is a config
value rather than a per-device preference because the settings window is a
separate application and cannot write the display's own storage.

The window has its own language under `Language`, and pulls the same locale
files from the backend so module labels need no second translation.

Adding a language: drop a new JSON file alongside `en.json` / `de.json` and
extend `SUPPORTED_LANGUAGES` in `gui/src/i18n/index.ts`. The kiosk loads the
file named by the config value and needs no list.

## Development

```bash
uv sync                              # set up .venv
uv run python -m backend.main        # dev server with auto-restart via uvicorn flags
uv run pytest                        # ~200 tests
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
  tray.py             Tray icon (StatusNotifierItem over D-Bus)
  autostart.py        The autostart switch, writes and enables the units
  brand.py            The app icon, drawn once for the tray and the window
  modules/            Module subclasses, one file per backend producer
widgets/              One manifest per widget; the file is the registration
frontend/             What the kiosk and settings window read off disk
  player.html         The page the video window loads
  css/themes/         One file per theme
  locales/            One JSON file per language
  vendor/             Tabler icons, fonts, emoji data set
shell/
  qml_kiosk/          The kiosk window (QML, system Python)
    qml/widgets/      One file per widget; this is the view
    theme.py          Reads the themes out of the CSS files
    bridge.py         WebSocket, config, strings, icons
gui/
  src/                EDGE//DASH, the settings window (React)
  src-tauri/          Its window frame (Tauri 2)
config.yaml           Committed template
config.local.yaml     Gitignored, written by the settings window
systemd/              User unit templates (backend + kiosk)
scripts/
  install.sh          The installer, does everything below as well
  install-desktop.sh  Icon and menu entry for the settings window
  window-rule.sh      Keeps the kiosk out of the task list, per compositor
  make-icon.py        Renders every icon file from backend/brand.py
docs/
  widgets.md          Guide: writing a widget
  themes.md           Guide: writing a theme
tests/                pytest, asyncio mode auto
```

## License

MIT, see [LICENSE](LICENSE).
