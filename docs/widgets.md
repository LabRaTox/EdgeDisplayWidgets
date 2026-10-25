# Writing a widget

A widget is three files that never import each other:

* a **backend module** in `backend/modules/`, which produces data
* a **view** in `shell/qml_kiosk/qml/widgets/`, which draws it
* a **manifest** in `widgets/`, which makes it known to the layout editor

The hub connects them. It runs every module on its own clock and pushes what
they return over one WebSocket; the kiosk routes each frame to the widgets
that subscribed to that module. Neither side knows the other exists, which is
why a view can be replaced without touching its data source and why a module
can feed several widgets.

```text
poll() / emit() → hub → {"module", "data", "ts"} → WebSocket → bridge → receive(module, data)
```

A widget that needs no data of its own can skip the backend part entirely, as
the clock and the pomodoro do: just a view and a manifest.

## The short version

```bash
# 1. the producer
$EDITOR backend/modules/moonphase.py
# 2. the view
$EDITOR shell/qml_kiosk/qml/widgets/Moonphase.qml
# 3. the registration
$EDITOR widgets/moonphase.json
# 4. switch it on and place it
$EDITOR config.local.yaml
systemctl --user restart edge-dashboard edge-kiosk
```

All three are found by name: the module registers itself through a
decorator, the manifest lives under its id, and the view is named after the
id in CamelCase. Placing the widget can happen in the settings window
instead of the editor; it writes the same YAML. Which change needs which
restart is listed in the table under [Wiring it up](#wiring-it-up).

## How the hub connects the parts

To understand what your module is doing, read `backend/hub.py`. In short:

1. **Discover.** At startup the hub imports every file in
   `backend/modules/` (except `base` and those starting with an
   underscore). Importing alone runs the `@register_module` decorators,
   which is what fills the registry. A module that fails to import is
   logged and skipped; it does not take the others down with it.
2. **Instantiate.** For every block enabled in the config, the matching
   class is created from the registry and handed the block, serialised with
   `model_dump()`. After that the module receives its way of pushing on its
   own through `bind()`.
3. **Poll.** One task per module calls `poll()` every `interval` seconds,
   but never more often than every 50 milliseconds, even if the config
   asks for less. A failing `poll()` is logged; the next tick still comes.
4. **Broadcast.** Every answer goes out as
   `{"module": name, "data": …, "ts": …}` to all open connections, unless
   it is byte-identical to the previous one and the module has
   `dedupe = True` (the default). It lands in the cache either way,
   because the cache is what serves a freshly connected kiosk at once.
5. **Replay.** A client that connects receives the last known answer for
   every module. The same happens inside the window: a widget that mounts
   later, for instance because the layout was just saved, is handed the cached
   values through `bridge.cached()` and never starts blank.
6. **Reload.** When the settings window saves, the modules are torn down
   and re-created from the new config; the classes are *not* re-imported,
   the registry stays as it is. The hub also broadcasts a control frame
   `{"event": "settings", …}`, on which the kiosk re-reads its config and
   rebuilds its pages. Module frames carry a `module` key, control frames
   an `event` key; the two never collide.

## The backend module

```python
"""Moon phase, one number, once an hour."""

from __future__ import annotations

import time
from typing import Any

from .base import Module, register_module


@register_module
class MoonPhaseModule(Module):
    name = "moonphase"          # the key in config.yaml, and what widgets subscribe to
    default_interval = 3600.0   # seconds between polls, overridable per config

    async def setup(self) -> None:
        """Called once before the first poll. Open connections here."""

    async def poll(self) -> dict[str, Any]:
        """Called on the interval. Return anything JSON can carry."""
        days = (time.time() / 86400.0 - 6.0) % 29.53058867
        return {"fraction": days / 29.53058867, "days": days}

    async def teardown(self) -> None:
        """Called on reload and on shutdown. Close what setup opened."""
```

That is a complete module. Its lifecycle:

* `__init__(config)` receives the serialised config block. The base class
  reads `interval` from it; everything else the module picks out itself,
  with its own defaults. `float(config.get("lat", 52.52))` in the weather
  module is the pattern. Those defaults have to match the ones in
  `settings_schema`, or the window offers a value that behaves differently
  from an untouched field.
* `setup()` runs once before the first `poll()`. If it fails, that is
  logged and the module is skipped; it is not retried over and over.
* `poll()` is the only abstract method and must return a
  JSON-serialisable dict. Blocking work such as reading files or querying
  psutil belongs in `asyncio.to_thread(...)`, so it does not stall the whole event
  loop; the media module does exactly that when it reads cover art.
* `teardown()` runs on reload and on shutdown. Errors in it are logged, the
  rest carries on.

What the base class offers beyond it:

| | |
|---|---|
| `default_interval` | seconds between calls to `poll()`, `1.0` when unset. The config overrides it per module with `interval`. |
| `dedupe` | `True` by default: an unchanged payload is not sent again. Set `False` for sample streams, where a sparkline needs a frame even when the value repeats. This applies to `poll()` and `emit()` alike. |
| `await self.emit(data)` | push a frame *now*, outside the clock. Use it when the source signals by itself, as the media module does for MPRIS changes. A module may use `poll`, `emit` or both; `emit` with no hub running (in tests) is a no-op. |
| `settings_schema` | fields the settings window should offer for this module, see below. |

### Two resilience patterns

A module that reaches outward over HTTP, sensors or D-Bus fails occasionally.
Two patterns have settled in for that, both visible to the view:

* **`available`/`reason`** (sensors): the answer always carries
  `{"available": false, "reason": "…"}` when there is nothing to read right
  now, and the view shows the reason instead of an empty tile.
* **`stale`** (weather): when the fetch failed but an old answer exists,
  the old answer is sent again with `stale: true`. The widget keeps showing
  values instead of vanishing for the length of a short outage.

### Editable settings

Every module gets `enabled` and `interval` in the settings window for free.
For anything module-specific, declare it, and the window renders it:

```python
import time
from typing import Any

from .base import Module, SettingField, register_module

@register_module
class MoonPhaseModule(Module):
    name = "moonphase"
    settings_schema = [
        SettingField(
            key="southern_hemisphere",
            type="bool",
            label_key="settings.mod.moonphase.southern",
            default=False,
        ),
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # Same default as in settings_schema, or an untouched field behaves
        # differently from one that was saved once.
        self.southern = bool(config.get("southern_hemisphere", False))

    async def poll(self) -> dict[str, Any]:
        days = (time.time() / 86400.0 - 6.0) % 29.53058867
        # Seen from the south the lit side is on the left, so a view that
        # draws the disc mirrors it when this is set.
        return {"fraction": days / 29.53058867, "days": days,
                "southern": self.southern}
```

The fields in detail:

| | |
|---|---|
| `key` | the config key, relative to the module block. A dot reaches into nested config (`govee.api_key`). |
| `type` | `bool`, `int`, `float`, `text`, `select`, `list` or `color`. |
| `label_key` | translation key for the label, see below. When the entry is missing the window shows the key itself. |
| `default` | the value an untouched field has. Must match the default in the constructor. |
| `help_key` | optional explanation shown under the field. |
| `group_key` | optional heading the window groups fields under. |
| `placeholder_key` | optional placeholder text for empty inputs. |
| `secret` | `True` masks the value in the API as `***`. When the field comes back masked and unchanged, the stored value is kept. That is how an API key is not accidentally overwritten with `***`. |
| `min`, `max`, `step` | bounds and step for number fields. |
| `options` | the values of a `select`. |
| `option_label_keys` | translation keys for a fixed `options` list, one to one. |
| `option_labels` | already-readable names for a list discovered at runtime; the window does not translate them again. |

**A new field needs a backend restart.** The settings window fetches the
field list from the running process (`/api/modules/schema`), and the hub
imports module code only at startup; reloading re-creates the classes but
reads no new files. Unknown keys added to the config by hand are allowed and
passed through to the module; the window offers only what it knows about.

### Do not poll forever

Choosing an `interval` as large as the view can tolerate is part of the
design. The moon phase needs one poll an hour, the weather ten minutes, and
CPU load looks once a second. `dedupe` helps on top: a module that
describes a state does not need a frame on every tick.

## The view

The view is a QML file in `shell/qml_kiosk/qml/widgets/`. It is named after
the widget, in CamelCase: `moonphase` becomes `Moonphase.qml`. The rule
(`disk_usage` becomes `DiskUsage.qml`, underscores split the words) lives
in `shell/qml_kiosk/views.py`; an id that is not lowercase letters, digits
and underscores is not looked up at all.

```qml
import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: root
    // Set by the window once the widget is loaded.
    property var theme
    // Which modules arrive. Empty when the widget needs no data.
    readonly property var moduleNames: ["moonphase"]
    // Whatever the layout put under `options`, unchanged.
    property var options: ({})
    // Is the tile placed as `compact`?
    property bool compact: false

    property var payload: null

    // Called for every frame of a subscribed module. With more than one
    // entry in `moduleNames`, `module` says which one it is.
    function receive(module, data) {
        payload = data
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Heading {
            theme: root.theme
            label: bridge.tr("widget.moonphase.title")
            Layout.bottomMargin: Style.headingBottom
        }

        Text {
            text: root.payload ? Math.round(root.payload.fraction * 100) + "%" : "–"
            color: root.theme ? root.theme["accent"] : "#00e0ff"
            font.pixelSize: bridge.metrics.metric_size
            font.family: root.theme ? root.theme["font-mono"] : "monospace"
        }

        Text {
            // `show_days` defaults to true; it has to be switched off
            // explicitly. Options arrive only when the layout set them;
            // a default in the manifest is not a value.
            visible: !root.compact
                     && (root.options && root.options.show_days !== false)
            text: root.payload ? root.payload.days.toFixed(1) + " d" : "–"
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: Style.subSize
            font.family: root.theme ? root.theme["font-mono"] : "monospace"
        }
    }
}
```

The contract is small:

* **`moduleNames`** decides what arrives. The window delivers only those
  frames, so a tile does not recompute on every foreign frame.
* **`receive(module, data)`** is called per frame. On load the widget is also
  handed the last known payload, so it does not start empty on a running
  kiosk.
* **`theme`** is set by the window as a binding and follows a theme change
  on its own. **`online`** (the connection state, bound), **`compact`**,
  **`options`** and **`confirm`** are set by the window, for whichever of
  them the widget declares. `confirm` is the shared question dialog,
  `ask(text, button, dangerous, callback)`. The callback receives `true`
  on confirmation.
* **`padH`** and **`padV`** are the inset the tile should use. Without a
  declaration the theme's own measures apply. A theme may override them, as
  long as the tile has room for it.

Cleaning up is QML's job: the object goes and everything hanging off it goes
with it.

With no file to find for an id, the tile says so ("no widget: …") instead of
staying blank, so a typo in the id stays visible. A tile saved without any id
reads "tile without a widget". Both texts come from the locale files
(`kiosk.no_widget`, `kiosk.tile_without_widget`).

### Colours, sizes, strings

Colours come from `theme`, sizes from the `Style` singleton, strings from
`bridge.tr(...)`. The `theme` dict holds the active theme's variables as
strings; whatever a theme does not set falls back to the base values. The
usual keys:

| | |
|---|---|
| `bg`, `fg`, `fg-muted` | background, foreground, muted text |
| `accent`, `accent-2` | the two accent colours |
| `ok`, `warn`, `bad` | green, yellow, red for states |
| `card-bg`, `card-border` | tile surface and border |
| `gap` | the page's grid gap, in pixels, as a number |
| `font-ui`, `font-mono`, `font-display` | fonts for text, numbers and large figures; the first family of the CSS list in each case |

What a theme adds in sizes and decoration, such as heading sizes, glow and
corners, is not in `theme` but in `bridge.metrics` and `bridge.effects`, filled by
`shell/qml_kiosk/theme.py`.

The `Style` singleton (`shell/qml_kiosk/qml/Style.qml`) holds the measures
that are the same in every theme: `headingBottom`, `subSize`, `subBottom`,
`axisSize`, `axisWidth`, `chartMinHeight`, `chartTicks`, the core-bar
measures and `pageGap`. It is registered in
`shell/qml_kiosk/qml/qmldir`, as is the `Temperatures` singleton; with
`import ".."` all shared building blocks are available.

### What the bridge offers

| | |
|---|---|
| `bridge.tr(key)` | one translated string, the key itself when the translation is missing. A second argument is the fallback. |
| `bridge.theme`, `bridge.metrics`, `bridge.effects` | theme, measures and decoration, see above. |
| `bridge.cached(module)` | the last known payload of one module. |
| `bridge.iconUrl(icon, colour)` | a drawable file for an icon (`ti:…` Tabler, `app:…` desktop symbol) or `""` for text and emoji. |
| `bridge.api` | the base address of the REST endpoints, for widgets that read or write on their own (notes, quick actions). |
| `bridge.online` | whether the WebSocket is currently connected; the window binds it into widgets that declare `online`. |
| `bridge.viewUrl(id)` | the QML file for a widget id; no widget needs it for its own tile, but it shows how the window finds the file. |

### Ready-made pieces

* **`Heading`**: the tile heading, upper-cased, letter-spaced, with the
  theme's glow.
* **`Chart`**: the sparkline. Properties: `theme`, `series`
  (`[{ values: [...], color: c }]`), `maxValue`, `tickFormat` (a function),
  `samples` (default 60), `gapMs` (the measured gap between two samples)
  and `travel` (default `false`, see below).
* **`MetricWidget`**: the shape cpu, gpu and ram share: a heading, the large
  figure beside it, detail line underneath, chart filling the rest. On
  `compact` it leaves the chart out. A view showing a sample series calls
  `noteArrival()` after each frame, so `Chart.gapMs` follows the module's
  interval.
* **`CoreBars`**: one bar per CPU core, as in the CPU widget.
* **`Confirm`**: the question dialog; the widget declares `confirm` and
  receives it from the window.
* **`Tile`**: the tile itself, inset included; a widget does not normally
  draw its own.

`MetricWidget` and `Temperatures` are building blocks, not widgets. They
have no manifest, and a test fails should one of them ever gain one.

## The manifest

`widgets/<name>.json` is what makes the layout editor aware of the widget.
The file being there is the registration; what is in it is optional.

```json
{
  "modules": ["moonphase"],
  "variants": ["compact"]
}
```

`modules` repeats what the view declares in `moduleNames`. The kiosk does not
read it, it goes by the QML file; it is in the manifest so the docs and the
view can be checked against each other. A test fails when the two drift
apart.

### Variants

`variants` makes the layout editor show a picker instead of a free-text
field. The variant reaches the widget as `compact`.

Build the other look, do not hide it. On the metric widgets `compact` leaves
the chart out entirely through a `Loader` rather than setting
`visible: false`, because a hidden chart still holds its texture.

### Options

`options` describes fields the layout editor shows underneath the tile, in
the same format as the module settings (`SettingField`), as JSON:

```json
{
  "modules": ["moonphase"],
  "options": [
    {
      "key": "show_days",
      "type": "bool",
      "label_key": "settings.widget.moonphase.show_days",
      "default": true
    }
  ]
}
```

The types are `bool`, `int`, `float`, `text`, `select`, `list` and `color`.
A `color` is a `#rrggbb` string; empty means "whatever the theme uses", which
is why the colour well comes with a way to clear it. A `select` can ask the
server for its values instead of naming them: `"options_source": "sensors"`
fills the list with the current sensors and adds readable labels. The value
lands in the widget's `options` unchanged.

A field can depend on others: `"depends_on": {"display": "analog"}` shows it
only while `display` is `analog`, and a list (`{"scheme": ["night", "light"]}`)
allows several values. The clock uses it so that only the faces of the chosen
display appear. A hidden field keeps its value; it just does not apply. The
same works for module settings.

What gets stored is a reading's id, such as `k10temp@0000:00:18.3:1`. It
names the chip and the address it sits at, a PCI slot or an i2c address, so
a tile still points at the same sensor after a reboot and can never point
at another one: the chip name is part of the id. The list starts with an
empty entry, which is how the field is cleared again. If the id is gone, the
widget says so rather than showing a neighbouring value.

A broken manifest logs a warning and never takes the editor down; the
widget still appears in the picker. How much it loses depends on the
damage. A file that is not valid JSON, or not a JSON object, counts as
empty and loses its variants and its options. A readable file with an
invalid `options` block keeps its variants and loses only the options, and
a single invalid field takes the whole list with it.

## Wiring it up

There are two config files: `config.yaml` as the template and
`config.local.yaml` as your own. Backend and kiosk each read exactly one of
them: `config.local.yaml` when it exists, otherwise `config.yaml`. Nothing is
merged, so a local file replaces the template entirely. Only the local file
is written by the settings window, with a `.bak` copy of the previous state.
The backend additionally accepts a path in `$EDGE_CONFIG` (the tests use it);
the kiosk does not, so leave it unset on the real machine. Your own changes belong in
`config.local.yaml`.

```yaml
modules:
  moonphase:
    enabled: true
    interval: 3600
    # every further key reaches the module unchanged

pages:
  - id: main
    grid:
      columns: "1fr 1fr 1fr"
      rows: "32px 1fr 1fr"
    widgets:
      - { id: moonphase, col: 3, row: 2, colspan: 1, rowspan: 1, variant: compact }
```

The id in `widgets` is the file name in `widgets/`, and the key
under `modules` is the module's `name`. Columns and rows understand the same
track list: fixed pixel sizes (`32px`) and shares (`1fr`, `2fr`, also
`minmax(0, 1fr)`, of which only the `fr` part counts). Fixed tracks keep
their size, the gaps come off next, and the shares split what is left by
ratio, so `200px 1fr 2fr` is a 200 pixel column and two that divide the rest
one to two. Anything else, such as `auto`, counts as `1fr`. The arithmetic
is in `shell/qml_kiosk/grid.py`. Placing widgets is easier in the
settings window's Layout view, which writes the same YAML.

What needs a restart when:

| Change | Takes effect |
|---|---|
| layout, options, `interval`, `enabled` | immediately; saving in the settings window reloads the hub and rebuilds the pages |
| new QML file | when the tile is loaded again. A save in the layout editor is usually enough, otherwise `systemctl --user restart edge-kiosk` |
| changed QML file | `systemctl --user restart edge-kiosk`; the QML engine keeps a loaded file in its cache, a save does not replace it |
| new module, new `settings_schema`, changed module code | `systemctl --user restart edge-dashboard`; the kiosk only when the view came with it |

## Translations

Translations go into `frontend/locales/de.json` and `en.json`. Keys are flat
and dotted, and `{placeholder}` is the interpolation syntax. `bridge.tr`
returns the key itself for a missing entry, and the settings window does the
same. A missing text does not break anything, but it stays visible. Add it
in both languages, or the window shows a different kind of leftover per
language.

## What to watch out for

**Do not animate continuously.** This is the mistake that hurts. A surface
that keeps moving costs about 20 CPU points on this machine no matter how
small it is. That is why `Chart.travel` is `false` and why the media widget
counts the playhead forward four times a second rather than per frame. Move
something only where the movement explains something.

**Bindings, not assignments.** A value assigned once replaces the binding
and never updates again. That is how the GPU widget once showed "GPU"
forever instead of the card's name, because `text` was set in
`Component.onCompleted`. When something has to be computed after the fact:
declare a helper property and bind to it.

**Rebuild lists only when the set changes, not on every value.** A `clear()`
on a `ListModel` throws the delegates away, resets the scroll position and
reloads images. The YouTube widget joins every entry's `kind` and `id` into
one string and rebuilds only when that changes; the quick actions do the
same for their folder tree with `treeKey()`. (The sensors widget rebuilds
its rows on every frame, because the values themselves live in the model.
With a table of numbers that is the exception you choose on purpose.)

**Handle only your own modules.** `moduleNames` keeps `receive` from running
on every foreign frame. Without it every tile recomputes five times a
second for data that arrives once a minute.

**An unchecked colour is a crash.** Anything going from the config into a
`color` property has to be checked against `#rgb`/`#rrggbb` first;
`safeColour` in `QuickActions.qml` and `SensorFocus.qml` does exactly that.
Empty is the result for anything that is not a colour, and the view falls back
to the theme's colour instead of letting Qt crash on an invalid value.

**One character for "no value".** Missing values are a single dash (`–`),
not several different dashes. A test checks this across every view.

**Tiles are wide and short**, and the display is touched, not clicked. Hit
targets below roughly 44 pixels are frustrating on it.

## Testing and debugging

```bash
uv run pytest tests/test_moonphase.py     # a module test needs no display
/usr/lib/qt6/bin/qmllint -I shell/qml_kiosk/qml \
    shell/qml_kiosk/qml/widgets/Moonphase.qml
systemctl --user restart edge-kiosk
```

Module tests instantiate the class and await `poll()`; `asyncio` tests run
without a decorator, the pytest configuration sets the mode automatically.
The pattern (clear the registry, register your own module, fake the
response) is in `tests/test_weather.py`, and examples for every module are
in `tests/`. For the view, `qmllint` is the fast first pass: it catches
typos and unknown properties before the window starts. The import path
(`-I …`) is needed so it finds the shared pieces and the singletons.

To avoid restarting the real kiosk every time, render the window away from
the display:

```bash
cd shell
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m qml_kiosk.main --windowed
```

`--windowed` opens a normal window at half size on the primary screen, with
a visible cursor. Without the argument the window goes to the Xeneon and
hides the cursor. QML errors land on stderr.

For the question "is the data arriving at all?" there are three places to
look:

```bash
curl -s localhost:8765/api/snapshot | less    # last frame per module
curl -s localhost:8765/api/widgets | less     # what the layout editor sees
curl -s localhost:8765/api/modules/schema | less
journalctl --user -u edge-dashboard -u edge-kiosk -f
```

The port is under `server.port`, 8765 by default. The snapshot shows what
the hub last sent. If a value is there, the module is fine and the view is
where it is stuck.

## A widget for the store

Widgets can also be shared through the plugin store, the same one
DECK//SWITCH gets its plugins from. A store widget does not live in the
repository but in a folder of its own, and brings all three parts with it.
A complete example is in `examples/plugins/moon-phase/`.

```text
moon-phase/
  manifest.json
  Widget.qml        the view
  module.py         optional, the backend module
  locales/de.json   optional, the texts
  locales/en.json
```

The manifest is the one from [The manifest](#the-manifest), plus what the
store needs:

```json
{
  "app": "edgedash",
  "type": "widget",
  "id": "moon-phase",
  "version": "1.0.0",
  "min_app_version": "1.0.0",
  "name": { "de": "Mondphase", "en": "Moon phase" },
  "summary": { "de": "…", "en": "…" },
  "license": "MIT",
  "view": "Widget.qml",
  "module": "module.py",
  "modules": ["moon-phase"],
  "variants": ["compact"]
}
```

* **`app`** must be `edgedash`. Without it the store takes the archive for a
  DECK//SWITCH plugin and refuses `type: widget`.
* **`id`** is also the widget id in the layout: three to forty characters,
  lowercase letters, digits and hyphens. The names of the built-in widgets
  are reserved in the store, including their hyphenated spelling
  (`disk-usage`).
* **`view`** names the QML file, `Widget.qml` if omitted. **`module`** is
  optional; without it the widget is a plain view like the clock.
* **`min_app_version`** is compared with the running Edge Dash, which
  installs nothing that needs a newer one.

Three differences from a built-in widget:

* **The view imports `EdgeDash` instead of `".."`.** Its folder is not next
  to the shared building blocks. `import EdgeDash` provides `Heading`,
  `Chart`, `CoreBars`, `Confirm`, `MetricWidget`, `Style` and
  `Temperatures`, from the same files the built-in views use.
* **The module imports absolutely:** `from backend.modules.base import
  Module, SettingField, register_module`. It may register only the names
  listed under `modules`, and none that already exists, so a widget cannot
  replace the built-in weather module.
* **The texts live in the folder**, under `locales/<language>.json`. Only
  keys in the widget's own space are taken: `widget.<id>.…`,
  `settings.widget.<id>.…` and `settings.mod.<module>.…` for its own
  modules. Anything else is dropped, so a widget cannot reword the
  dashboard.

### Commands from the widget to its module

A store widget has no routes of its own. When a tap has to do something in
the backend (join a channel, mute), the view sends it to its module:

```qml
var xhr = new XMLHttpRequest()
xhr.open("POST", bridge.api + "/api/modules/discord/command/join")
xhr.setRequestHeader("Content-Type", "application/json")
xhr.send(JSON.stringify({ channel_id: id }))
```

The module answers in `command()`:

```python
async def command(self, action: str, args: dict) -> dict:
    if action == "join":
        ...
        return {"ok": True}
    raise NotImplementedError
```

The body arrives as `args`, the answer goes back to the view unchanged.
`{"ok": False, "error": ...}` comes back with status 400. An action the
module does not know, or a module without `command()`, is a 404. The new
state does not need to be part of the answer: the module pushes it with
`emit()` like any other change, and every tile gets it.

### Installing and submitting

Both happen in the settings window under **Plugins**, in the **Widgets** tab, which lists built-in, installed and store widgets together. A card's switch turns the widget's modules on and off, and "Plugin settings" opens their settings. To install, the backend
downloads the archive, checks the checksum from the catalog before opening
it, and unpacks it to `~/.local/share/edge-dashboard/plugins/<id>/`. Paths
that leave the folder and links are not unpacked. It then loads the module,
switches it on in the config and sends the kiosk the new config. Neither an
install nor an update needs a restart: the kiosk appends the checksum to the
view's address, and a new address bypasses the QML cache. That covers the
file `view` names. If it loads further QML files from its folder, the kiosk
sees their new version only after a restart.

An installed module runs in the backend with your rights, the same as a
DECK//SWITCH plugin. The store reviews every submission, Python through its
syntax tree, QML and JavaScript by text search, and a submission from an
author not marked as trusted goes through moderation. What the review finds
(addresses, network, starting programs, runtime code) is shown before
installing, and a widget with findings needs a second click.

To submit, sign in with GitHub under **Plugins → Sign in to the store** and
open **Submit a plugin**. Drag the archive into the field, or click it and
choose the file. ZIP, TAR and tar.gz all work, with the plugin folder as the
top level or the files directly at the root. The archive goes to the store
unchanged. What the store says about it, and what its review found, is
shown at the top of the dialog afterwards. Below are your submissions with
every version and where it stands. What is still waiting or was rejected
can be deleted there, what was approved withdrawn. The store does not
accept a version number that already exists.

**Trying it without the store:** **Install plugins** takes a zip file or a folder and installs it by the same rules, only without the store's checksum. That way you can try your own widget before submitting it.

Before submitting, a run without the store is worth it:

```bash
/usr/lib/qt6/bin/qmllint -I shell/qml_kiosk/qml examples/plugins/moon-phase/Widget.qml
uv run pytest tests/test_plugins.py
```

To use another store, set `EDGE_STORE_URL` for the backend.
`EDGE_PLUGINS_DIR` moves the plugins folder; the tests use it.

## From idea to widget: a calendar

A calendar widget, as a checklist through the sections above:

1. **Module** `calendar`. The source can be a calendar file, a CalDAV
   server or a script. Appointments rarely change, so
   `default_interval = 900` is plenty, and `dedupe` keeps the wire quiet in
   between. The config fields `url` and `days_ahead` go into
   `settings_schema`. For HTTP, use httpx with a timeout (the weather module
   uses 10 seconds), and the `available`/`stale` pattern on failure.
2. **Answer.** Keep it small and stable, because a changed shape rebuilds
   the lists in the view:

   ```python
   {"available": True,
    "events": [{"title": "…", "start": "2026-10-12T09:00", "all_day": False}],
    "fetched_at": 1760000000.0}
   ```

3. **View** `Calendar.qml` with `moduleNames: ["calendar"]`, one line per
   appointment.
4. **Manifest.** `{"modules": ["calendar"]}` is enough to start; a
   `compact` variant for a shorter list can follow.
5. **Strings and tests.** Keys in both locale files, a module test with a
   fixed sample response, `qmllint` for the view.

---

[Writing a theme](themes.md) · [Why it looks the way it does](decisions.md) · [README](../README.md) · [Deutsch](widgets.de.md)
