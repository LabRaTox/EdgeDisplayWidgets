import { registerWidget } from "../registry.js";
import { Sparkline } from "../lib/sparkline.js";
import { Smoothed } from "../lib/smooth.js";
import { t } from "../i18n.js";

class GpuWidget {
  static modules = ["nvidia"];
  static variants = ["compact"];

  mount(el, _, ctx) {
    this.el = el;
    // See cpu.js: compact drops the chart from the DOM rather than hiding it,
    // so nothing is drawn for it at all.
    this.compact = ctx?.variant === "compact";
    el.innerHTML = `
      <div class="metric-head">
        <h3 data-bind="title">${t("widget.gpu.title")}</h3>
        <div class="metric-big" data-bind="percent">–</div>
      </div>
      <div class="metric-sub" data-bind="sub">–</div>
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
    this._percent = new Smoothed((v) => { percentEl.textContent = v.toFixed(0) + "%"; }, { el });
  }

  update(data) {
    if (!data) return;
    if (!data.available) {
      this.el.classList.add("widget-disabled");
      this.el.querySelector('[data-bind="title"]').textContent = t("widget.gpu.title");
      this.el.querySelector('[data-bind="percent"]').textContent = "—";
      this.el.querySelector('[data-bind="sub"]').textContent =
        data.reason || t("widget.gpu.no_nvidia");
      return;
    }
    this.el.classList.remove("widget-disabled");
    this.el.querySelector('[data-bind="title"]').textContent = data.name || t("widget.gpu.title");
    this._percent.set(data.gpu_percent);

    const usedGiB = (data.vram.used / 1024 ** 3).toFixed(1);
    const totalGiB = (data.vram.total / 1024 ** 3).toFixed(1);
    const parts = [`${usedGiB} / ${totalGiB} GiB`, `${data.temp_c}°C`];
    if (data.power_w != null) parts.push(`${data.power_w.toFixed(0)} W`);
    this.el.querySelector('[data-bind="sub"]').textContent = parts.join(" • ");
    this.spark?.push(data.gpu_percent);
  }

  destroy() {
    this.spark?.destroy();
    this._percent.destroy();
  }
}

registerWidget("gpu", GpuWidget);
