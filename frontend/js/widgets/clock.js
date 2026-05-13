// Frontend-only clock — no backend module required.
// Subscribes to no modules; ticks at 1Hz (or 250ms when seconds visible).

import { registerWidget } from "../registry.js";
import { getLang } from "../i18n.js";

const PAD = (n) => String(n).padStart(2, "0");

class ClockWidget {
  static modules = [];

  mount(el, _initial, meta) {
    this.el = el;
    // Default: HH:MM only. Enable seconds explicitly via config.yaml:
    //   widgets: [{ id: clock, ..., options: { show_seconds: true } }]
    this._showSeconds = meta?.options?.show_seconds === true;
    el.innerHTML = `
      <div class="clock-time" data-bind="time">--:--</div>
      <div class="clock-date" data-bind="date">…</div>
    `;
    this._render();
    this._timer = setInterval(() => this._render(), this._showSeconds ? 250 : 1000);
  }

  _render() {
    const now = new Date();
    const time = `${PAD(now.getHours())}:${PAD(now.getMinutes())}` +
      (this._showSeconds ? `:${PAD(now.getSeconds())}` : "");
    const date = now.toLocaleDateString(getLang(), {
      weekday: "long",
      day: "numeric",
      month: "long",
    });
    this.el.querySelector('[data-bind="time"]').textContent = time;
    this.el.querySelector('[data-bind="date"]').textContent = date;
  }

  // No-op: clock doesn't subscribe to any module.
  update() {}

  destroy() {
    clearInterval(this._timer);
  }
}

registerWidget("clock", ClockWidget);
