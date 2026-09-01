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

A widget that needs no data of its own can skip the backend part entirely, as
the clock and the pomodoro do.

## The short version

```bash
# 1. the producer
$EDITOR backend/modules/moonphase.py
# 2. the view
$EDITOR shell/qml_kiosk/qml/widgets/Moonphase.qml
# 3. the registration
$EDITOR widgets/moonphase.json
# 4. switch it on and place it
$EDITOR config.yaml
systemctl --user restart edge-dashboard edge-kiosk
```

Both files are found by name: the module registers itself through a decorator,
the widget file is imported by the id used in the layout.

## The backend module

```python
"""Moon phase, one number, once an hour."""

from __future__ import annotations

import math
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

That is a complete module. What the base class offers beyond it:

| | |
|---|---|
| `default_interval` | seconds between calls to `poll()`. The config can override it per module. |
| `dedupe` | `True` by default: an unchanged payload is not sent again. Set `False` for sample streams, where a sparkline needs a frame even when the value repeats. |
| `await self.emit(data)` | push a frame *now*, outside the clock. Use it when the source signals by itself, as the media module does for MPRIS changes. A module may use `poll`, `emit` or both. |
| `settings_schema` | fields the settings window should offer for this module, see below. |

A failing `poll()` is logged and skipped; it does not take the hub down.

### Editable settings

Every module gets `enabled` and `interval` in the settings window for free.
For anything module-specific, declare it, and the window renders it:

```python
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
```

`type` is one of `bool`, `int`, `float`, `text`, `select`, `list`. A dotted
`key` reaches into nested config (`govee.api_key`). `secret=True` masks the
value in the API and keeps the stored one when the field comes back unchanged.
`label_key` and the optional `help_key` are looked up in
`frontend/locales/*.json`, so add them there in both languages.

**A new field needs a backend restart.** The config model rejects unknown
keys, so a value the running process has never heard of fails validation on
save.

## The view

The view is a QML file in `shell/qml_kiosk/qml/widgets/`. It is named after
the widget, in CamelCase: `moonphase` becomes `Moonphase.qml`.

```qml
import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: root
    // Set by the window once the widget is loaded.
    property var theme
    // Which modules arrive. Empty when the widget needs no data.
    readonly property var moduleNames: ["mondphase"]
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
            label: bridge.tr("widget.mondphase.title")
            Layout.bottomMargin: Style.headingBottom
        }

        Text {
            text: root.payload ? Math.round(root.payload.fraction * 100) + "%" : "–"
            color: root.theme ? root.theme["accent"] : "#00e0ff"
            font.pixelSize: bridge.metrics.metric_size
            font.family: root.theme ? root.theme["font-mono"] : "monospace"
        }

        Text {
            visible: !root.compact
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
* **`theme`**, **`options`**, **`compact`** and **`confirm`** are set by the
  window, for whichever of them the widget declares. `confirm` is the shared
  question dialog, `ask(text, button, dangerous, callback)`.
* **`padH`** and **`padV`** are the inset the tile should use. A theme may
  override it, as long as the tile has room for it.

Cleaning up is QML's job: the object goes and everything hanging off it goes
with it.

Colours come from `theme`, sizes from the `Style` singleton, strings from
`bridge.tr(...)`. For the usual shapes there are ready-made pieces:
`Heading`, `Chart`, `MetricWidget`, `CoreBars` and `Confirm`.

The window finds the file by name: `moonphase` becomes `Moonphase.qml`,
`disk_usage` becomes `DiskUsage.qml`. The rule lives in
`shell/qml_kiosk/views.py`. With no file to find, the tile says so instead of
staying blank.

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
view can be checked against each other. A test fails when the two drift apart.

### Variants

`variants` makes the layout editor show a picker instead of a free-text
field. The variant reaches the widget as `compact`.

Build the other look, do not hide it. On the metric widgets `compact` leaves
the chart out entirely through a `Loader` rather than setting
`visible: false`, because a hidden chart still holds its texture.

### Options

`options` describes fields the layout editor shows underneath the tile, in
the same format as the module settings (`SettingField`):

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
A `select` can ask the server for its values instead of naming them:
`"options_source": "sensors"` fills the list with the current sensors and
adds readable labels. The value lands in the widget's `options` unchanged.

What gets stored is a reading's id, such as `k10temp@0000:00:18.3:1`. It names
the chip and the address it sits at, a PCI slot or an i2c address, so a tile
still points at the same sensor after a reboot and can never point at another
one: the chip name is part of the id. If the id is gone, the widget says so
rather than showing a neighbouring value.

A malformed manifest costs that widget its variants and options and logs a
warning. The widget still appears in the picker, and the editor keeps working.

## Wiring it up

```yaml
modules:
  moonphase:
    enabled: true
    interval: 3600

pages:
  - id: main
    grid:
      columns: "1fr 1fr 1fr"
      rows: "32px 1fr 1fr"
    widgets:
      - { id: moonphase, col: 3, row: 2, variant: compact }
```

The id in `widgets` is the file name in `widgets/`, and the key
under `modules` is the module's `name`. Placing widgets is easier in the
settings window's Layout view, which writes the same YAML.

Translations go into `frontend/locales/de.json` and `en.json`. Keys are flat
and dotted, and `{placeholder}` is the interpolation syntax.

## What to watch out for

**Do not animate continuously.** This is the mistake that hurts. A surface
that keeps moving costs about 20 CPU points on this machine no matter how
small it is. That is why `Chart.travel` is `false` and why the media widget
counts the playhead forward four times a second rather than per frame. Move
something only where the movement explains something.

**Bindings, not assignments.** A value assigned once replaces the binding and
never updates again. That is how the GPU widget once showed "GPU" forever
instead of the card's name, because `text` was set in `Component.onCompleted`.

**Rebuild lists only when the set changes, not on every value.** A `clear()`
on a `ListModel` throws the delegates away, resets the scroll position and
reloads images. The sensors widget compares the joined ids and patches the
numbers in place otherwise.

**Handle only your own modules.** `moduleNames` keeps `receive` from running
on every foreign frame. Without it every tile recomputes five times a second
for data that arrives once a minute.

**An unchecked colour is a crash.** Anything going from the config into a
`color` property has to be checked against `#rgb`/`#rrggbb` first;
`safeColour` in `QuickActions.qml` and `SensorFocus.qml` does exactly that.

**Tiles are wide and short**, and the display is touched, not clicked. Hit
targets below roughly 44 pixels are frustrating on it.

## Testing

```bash
uv run pytest tests/test_moonphase.py     # a module test needs no display
/usr/lib/qt6/bin/qmllint -I shell/qml_kiosk/qml \
    shell/qml_kiosk/qml/widgets/Moonphase.qml
systemctl --user restart edge-kiosk
```

Module tests instantiate the class and await `poll()`; there are plenty of
examples in `tests/`. For the view, `qmllint` is the fast first pass: it
catches typos and unknown properties before the window starts.

To avoid restarting the real kiosk every time, render the window away from
the display:

```bash
cd shell
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m qml_kiosk.main --windowed
```

QML errors land on stderr. `--windowed` puts the window on the primary screen
instead of the Xeneon.

---

[Writing a theme](themes.md) · [Why it looks the way it does](decisions.md) · [README](../README.md) · [Deutsch](widgets.de.md)
