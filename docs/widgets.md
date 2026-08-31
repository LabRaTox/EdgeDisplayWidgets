# Writing a widget

A widget is two files that never import each other:

* a **backend module** in `backend/modules/`, which produces data
* a **frontend widget** in `frontend/js/widgets/`, which draws it

The hub connects them. It runs every module on its own clock and pushes what
they return over one WebSocket; the frontend routes each frame to the widgets
that subscribed to that module. Neither side knows the other exists, which is
why a widget can be replaced without touching its data source and why a module
can feed several widgets.

A widget that needs no data of its own can skip the backend half entirely, as
`clock.js` and `pomodoro.js` do.

## The short version

```bash
# 1. the producer
$EDITOR backend/modules/moonphase.py
# 2. the consumer
$EDITOR frontend/js/widgets/moonphase.js
# 3. switch it on and place it
$EDITOR config.yaml
systemctl --user restart edge-dashboard
```

Both files are found by name: the module registers itself through a decorator,
the widget file is imported by the id used in the layout.

## The backend module

```python
"""Moon phase — one number, once an hour."""

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

## The frontend widget

```js
import { registerWidget } from "../registry.js";
import { t } from "../i18n.js";

class MoonPhaseWidget {
  // Which modules to receive. Empty for a widget that needs no data.
  static modules = ["moonphase"];
  // Optional: the looks this widget offers, shown in the layout editor.
  static variants = ["compact"];

  mount(el, initial, ctx) {
    this.el = el;
    this.compact = ctx?.variant === "compact";
    el.innerHTML = `
      <div class="metric-head">
        <h3>${t("widget.moonphase.title")}</h3>
        <div class="metric-big" data-bind="phase">–</div>
      </div>
      ${this.compact ? "" : `<div class="metric-sub" data-bind="days">–</div>`}
    `;
    if (initial) this.update(initial);
  }

  update(data, moduleName, ts) {
    if (!data) return;
    this.el.querySelector('[data-bind="phase"]').textContent =
      `${Math.round(data.fraction * 100)}%`;
    if (this.compact) return;
    this.el.querySelector('[data-bind="days"]').textContent =
      `${data.days.toFixed(1)} d`;
  }

  destroy() {
    // Stop timers, disconnect observers, destroy sparklines. Called when the
    // widget is removed or the page is rebuilt after a settings change.
  }
}

registerWidget("moonphase", MoonPhaseWidget);
```

The three methods:

* **`mount(el, initial, ctx)`** builds the DOM once. `el` is the tile,
  `initial` is the last known payload when there is one (a widget added to a
  running dashboard is not blank), and `ctx` carries `{id, variant, options}`.
* **`update(data, moduleName, ts)`** is called per frame. With several entries
  in `static modules`, `moduleName` says which one this is.
* **`destroy()`** has to undo what `mount` set up. A widget survives being
  moved in the layout editor by being destroyed and mounted again.

### Variants

`static variants = ["compact"]` makes the layout editor offer a list instead
of a free-text field: the backend reads that line out of the file when it
scans the directory. The variant reaches the widget as `ctx.variant`, and
`data-variant` is set on the tile so CSS can use it too.

Build the different look, do not hide it. `compact` on the metric widgets
leaves the chart out of the DOM rather than setting `display: none`, because a
hidden sparkline still redraws on every sample.

### Options

Anything under `options` in the layout reaches `ctx.options` untouched. That
is the place for per-instance settings that are not worth a config schema, the
way the clock takes `options: { show_seconds: true }`.

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

The id in `widgets` is the file name in `frontend/js/widgets/`, and the key
under `modules` is the module's `name`. Placing widgets is easier in the
settings window's Layout view, which writes the same YAML.

Translations go into `frontend/locales/de.json` and `en.json`. Keys are flat
and dotted, and `{placeholder}` is the interpolation syntax.

## What to watch out for

**Do not animate per frame.** This is the one that bites. Interpolating 32 CPU
core bars in JavaScript cost 29 CPU points on this machine, for bars that
`transition: height 200ms` in CSS was already animating. One style write per
sample, and let CSS do the moving. The measurements are in the README under
the kiosk section.

**Write to the DOM only when something changed.** `update()` runs as often as
the module polls. Cache the nodes in `mount()` rather than querying them every
frame, and skip the write when the text is the same.

**Rebuild lists only when the set changes, not on every value.** The sensors
widget compares the joined ids and patches the numbers in place otherwise.

**Escape anything from outside.** Payloads reaching `innerHTML` need escaping;
`disk_usage.js` has the two helpers for it. Values that go into an attribute
need it too.

**Tiles are wide and short**, and the display is touched, not clicked. Hit
targets below roughly 44 pixels are frustrating on it.

## Testing

```bash
uv run pytest tests/test_moonphase.py     # a module test needs no display
uv run python -m backend.main             # then open http://127.0.0.1:8765
```

Module tests instantiate the class and await `poll()`; there are plenty of
examples in `tests/`. For the frontend, the browser is the faster loop: the
kiosk has no devtools, but the same page is served to any browser, and a
reload picks up an edited widget file.

---

[Writing a theme](themes.md) · [README](../README.md) · [Deutsch](widgets.de.md)
