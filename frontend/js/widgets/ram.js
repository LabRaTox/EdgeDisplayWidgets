import { registerWidget } from "../registry.js";
import { Sparkline } from "../lib/sparkline.js";

class RamWidget {
  static modules = ["system"];

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="metric-head">
        <h3>RAM</h3>
        <div class="metric-big" data-bind="percent">–</div>
      </div>
      <div class="metric-sub">
        <span data-bind="used">–</span> / <span data-bind="total">–</span>
      </div>
      <div class="chart">
        <div class="chart-axis"></div>
        <div class="chart-canvases">
          <canvas class="spark"></canvas>
        </div>
      </div>
    `;
    this.spark = new Sparkline(el.querySelector(".spark"), {
      max: 100,
      axisEl: el.querySelector(".chart-axis"),
      axisFormat: (v) => `${Math.round(v)}%`,
    });
  }

  update(data) {
    const r = data?.ram;
    if (!r) return;
    this.el.querySelector('[data-bind="percent"]').textContent =
      r.percent.toFixed(0) + "%";
    this.el.querySelector('[data-bind="used"]').textContent =
      (r.used / 1024 ** 3).toFixed(1) + " GiB";
    this.el.querySelector('[data-bind="total"]').textContent =
      (r.total / 1024 ** 3).toFixed(1) + " GiB";
    this.spark.push(r.percent);
  }

  destroy() {}
}

registerWidget("ram", RamWidget);
