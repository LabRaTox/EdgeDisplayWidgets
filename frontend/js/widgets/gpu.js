import { registerWidget } from "../registry.js";
import { Sparkline } from "../lib/sparkline.js";
import { t } from "../i18n.js";

class GpuWidget {
  static modules = ["nvidia"];

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="metric-head">
        <h3 data-bind="title">${t("widget.gpu.title")}</h3>
        <div class="metric-big" data-bind="percent">–</div>
      </div>
      <div class="metric-sub" data-bind="sub">–</div>
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
    this.el.querySelector('[data-bind="percent"]').textContent = data.gpu_percent + "%";

    const usedGiB = (data.vram.used / 1024 ** 3).toFixed(1);
    const totalGiB = (data.vram.total / 1024 ** 3).toFixed(1);
    const parts = [`${usedGiB} / ${totalGiB} GiB`, `${data.temp_c}°C`];
    if (data.power_w != null) parts.push(`${data.power_w.toFixed(0)} W`);
    this.el.querySelector('[data-bind="sub"]').textContent = parts.join(" • ");
    this.spark.push(data.gpu_percent);
  }

  destroy() {}
}

registerWidget("gpu", GpuWidget);
