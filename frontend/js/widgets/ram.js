import { registerWidget } from "../registry.js";
import { Sparkline } from "../lib/sparkline.js";
import { Smoothed } from "../lib/smooth.js";

class RamWidget {
  static modules = ["system"];
  static variants = ["compact"];

  mount(el, _, ctx) {
    this.el = el;
    this.compact = ctx?.variant === "compact";
    el.innerHTML = `
      <div class="metric-head">
        <h3>RAM</h3>
        <div class="metric-big" data-bind="percent">–</div>
      </div>
      <div class="metric-sub">
        <span data-bind="used">–</span> / <span data-bind="total">–</span>
      </div>
      ${this.compact ? "" : `
      <div class="chart">
        <div class="chart-axis"></div>
        <div class="chart-canvases">
          <canvas class="spark"></canvas>
        </div>
      </div>
      `}
    `;
    this.spark = this.compact
      ? null
      : new Sparkline(el.querySelector(".spark"), {
          max: 100,
          axisEl: el.querySelector(".chart-axis"),
          axisFormat: (v) => `${Math.round(v)}%`,
          scroll: true,
        });
    const percentEl = el.querySelector('[data-bind="percent"]');
    const usedEl = el.querySelector('[data-bind="used"]');
    this._percent = new Smoothed((v) => { percentEl.textContent = v.toFixed(0) + "%"; }, { el });
    this._used = new Smoothed((v) => {
      usedEl.textContent = (v / 1024 ** 3).toFixed(1) + " GiB";
    }, { el });
  }

  update(data) {
    const r = data?.ram;
    if (!r) return;
    this._percent.set(r.percent);
    this._used.set(r.used);
    this.el.querySelector('[data-bind="total"]').textContent =
      (r.total / 1024 ** 3).toFixed(1) + " GiB";
    this.spark?.push(r.percent);
  }

  destroy() {
    this.spark?.destroy();
    this._percent.destroy();
    this._used.destroy();
  }
}

registerWidget("ram", RamWidget);
