# Configuration

*[Deutsche Fassung](configuration.de.md)*

The settings window covers all of this. This page is for editing
`config.local.yaml` by hand and for knowing what each value does.


The dashboard loads its config in this order:

1. `$EDGE_CONFIG` environment variable (explicit path, useful for tests).
2. `config.local.yaml` in the project root, if it exists; after the one-line
   install that is `~/.local/share/edge-dashboard/app`. Installed as a
   package, `~/.config/edge-dashboard/config.yaml` instead.
3. `config.yaml` (the committed template).

**Workflow**: edit in the settings window, not in the file. What it saves
goes to `config.local.yaml`, which is gitignored, so the committed
`config.yaml` stays a clean template. The write is atomic and keeps the
replaced version as `config.local.yaml.bak`.

## Top-level schema

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

While bound to `127.0.0.1`, the backend only answers requests addressed to
`127.0.0.1`, `localhost` or `::1`. That keeps a web page whose domain was made
to resolve to this machine (DNS rebinding) from reading the API. Further names
can be allowed with `EDGE_ALLOWED_HOSTS=name1,name2` in the environment of the
service.

## Module configuration

Each key under `modules:` matches a `Module` subclass's `name`. Common
fields: `enabled` (bool) and `interval` (seconds between polls). Module-
specific keys are forwarded to the module.

> **Edit in the settings window, not in the file.** Under **Plugins**, the
> switch on a widget's card turns its modules on and off, and **Plugin
> settings** opens an input for every field those modules declare: interval
> plus whatever is module-specific (smart-light API keys, disk `min_size_gb`
> and mountpoints, the `top_processes` limit, quick-action timeouts, where the
> notes are stored). Secrets are masked and only overwritten when a new value
> is typed. The YAML below is the reference for what those fields mean, not a
> place you normally edit.
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

  gpu:                     # GPU stats, NVIDIA via nvml, AMD via amdgpu
    enabled: true
    interval: 1.0

  sensors:                 # /sys/class/hwmon temperatures
    enabled: true
    interval: 2.0

  media:                   # MPRIS player control (Spotify, browsers, MPV, …)
    enabled: true          # no interval: it pushes on player signals

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

  notes:
    enabled: true
    interval: 5            # how often a change elsewhere is looked for
    storage: local         # local | joplin
    joplin_token: ""       # optional; empty: "Connect to Joplin" on the tile asks for one
    joplin_notebook: "Edge Dash"   # the Joplin notebook for quick notes
    joplin_port: 0         # 0: find Joplin on ports 41184 to 41194
```

**Notes in Joplin.** Joplin's desktop app serves a local API once its Web
Clipper service is on (Options → Web Clipper). With `storage: joplin` the
notes widget keeps everything there: notebooks become folders, sub-notebooks
show as "Parent › Child", checklists stay Markdown (`- [ ]`) and tick on the
display, and quick notes go into the notebook named by `joplin_notebook`.
Connecting needs a token, either typed into the plugin settings or requested
from the tile with **Connect to Joplin** and a confirmation in Joplin. Pinning
is not a Joplin feature, so which notes are pinned is kept on this machine.

## Quick actions

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

![The quick action deck on the display](screenshots/kiosk-actions.png)

### YAML schema

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
- `label_size` / `icon_size`: text size (10..48) and icon size (16..128) of
  this one tile, in pixels; leave them out for the deck's default.

## Smart lights

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

## Pages and widget placement

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

![Pomodoro, disks and sensors on the second page](screenshots/kiosk-tools.png)

---

[Setup and development](setup.md) · [Writing a widget](widgets.md) · [Writing a theme](themes.md) · [README](../README.md)
