import { registerWidget } from "../registry.js";
import { Sparkline } from "../lib/sparkline.js";
import { t } from "../i18n.js";

class CpuWidget {
  static modules = ["system"];

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="metric-head">
        <h3>CPU</h3>
        <div class="metric-big" data-bind="percent">–</div>
      </div>
      <div class="metric-sub" data-bind="sub">–</div>
      <div class="chart">
        <div class="chart-axis"></div>
        <div class="chart-canvases">
          <canvas class="spark"></canvas>
        </div>
      </div>
      <div class="cpu-cores" data-bind="cores_bars"></div>
    `;
    this.spark = new Sparkline(el.querySelector(".spark"), {
      max: 100,
      axisEl: el.querySelector(".chart-axis"),
      axisFormat: (v) => `${Math.round(v)}%`,
    });
    this._coreEls = null;
  }

  update(data) {
    const cpu = data?.cpu;
    if (!cpu) return;
    this.el.querySelector('[data-bind="percent"]').textContent =
      cpu.percent.toFixed(0) + "%";
    const parts = [];
    if (cpu.model) parts.push(cpu.model);
    parts.push(`${cpu.count} ${t("widget.cpu.cores")}`);
    if (cpu.freq_mhz) parts.push(`${(cpu.freq_mhz / 1000).toFixed(2)} GHz`);
    this.el.querySelector('[data-bind="sub"]').textContent = parts.join(" • ");
    this.spark.push(cpu.percent);
    this._renderCores(cpu.per_core || []);
  }

  _renderCores(values) {
    const root = this.el.querySelector('[data-bind="cores_bars"]');
    if (!this._coreEls || this._coreEls.length !== values.length) {
      root.innerHTML = "";
      this._coreEls = values.map(() => {
        const wrap = document.createElement("div");
        wrap.className = "core-bar";
        const fill = document.createElement("div");
        fill.className = "core-fill";
        wrap.appendChild(fill);
        root.appendChild(wrap);
        return fill;
      });
    }
    for (let i = 0; i < values.length; i++) {
      const v = Math.max(0, Math.min(100, values[i]));
      this._coreEls[i].style.height = v + "%";
    }
  }

  destroy() {}
}

registerWidget("cpu", CpuWidget);
