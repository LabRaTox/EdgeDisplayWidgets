import { registerWidget } from "../registry.js";
import { Sparkline } from "../lib/sparkline.js";
import { t } from "../i18n.js";

const KB = 1024;
const MB = KB * 1024;

function fmtRate(bps) {
  if (bps >= MB) return (bps / MB).toFixed(1) + " MB/s";
  if (bps >= KB) return (bps / KB).toFixed(1) + " kB/s";
  return Math.round(bps) + " B/s";
}

function fmtAxisRate(bps) {
  if (bps >= MB) return (bps / MB).toFixed(1) + " MB/s";
  if (bps >= KB) return (bps / KB).toFixed(0) + " kB/s";
  return Math.round(bps) + " B/s";
}

class NetworkWidget {
  static modules = ["system"];

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="metric-head">
        <h3>${t("widget.network.title")}</h3>
      </div>
      <div class="net-rates">
        <span class="net-rate net-rx">↓ <span data-bind="rx">–</span></span>
        <span class="net-rate net-tx">↑ <span data-bind="tx">–</span></span>
      </div>
      <div class="chart">
        <div class="chart-axis"></div>
        <div class="chart-canvases">
          <canvas class="spark spark-rx"></canvas>
          <canvas class="spark spark-tx"></canvas>
        </div>
      </div>
    `;
    this._max = 1024 * 1024; // 1 MB/s starting ceiling
    // rx owns the shared axis. tx uses --accent-2 via CSS override.
    this.sparkRx = new Sparkline(el.querySelector(".spark-rx"), {
      max: this._max,
      axisEl: el.querySelector(".chart-axis"),
      axisFormat: fmtAxisRate,
    });
    this.sparkTx = new Sparkline(el.querySelector(".spark-tx"), { max: this._max });
  }

  update(data) {
    const n = data?.network;
    if (!n) return;
    this.el.querySelector('[data-bind="rx"]').textContent = fmtRate(n.rx_bytes_per_s);
    this.el.querySelector('[data-bind="tx"]').textContent = fmtRate(n.tx_bytes_per_s);

    const peak = Math.max(n.rx_bytes_per_s, n.tx_bytes_per_s);
    if (peak > this._max * 0.9) {
      this._max = Math.max(peak * 1.5, this._max);
      this.sparkRx.setMax(this._max);
      this.sparkTx.setMax(this._max);
    }
    this.sparkRx.push(n.rx_bytes_per_s);
    this.sparkTx.push(n.tx_bytes_per_s);
  }

  destroy() {}
}

registerWidget("network", NetworkWidget);
