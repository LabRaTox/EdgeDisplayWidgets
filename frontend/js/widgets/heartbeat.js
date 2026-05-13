import { registerWidget } from "../registry.js";
import { t, getLang } from "../i18n.js";

function fmtDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "–";
  if (seconds < 60) return "< 1 min";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return m === 0 ? `${h} h` : `${h} h ${m} min`;
  }
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  return h === 0 ? `${d} T` : `${d} T ${h} h`;
}

class HeartbeatWidget {
  static modules = ["heartbeat"];

  mount(el, _initial, meta) {
    this.el = el;
    // Enable seconds via config.yaml:
    //   widgets: [{ id: heartbeat, ..., options: { show_seconds: true } }]
    this._showSeconds = meta?.options?.show_seconds === true;
    this._timeFmtOpts = this._showSeconds
      ? { hour: "2-digit", minute: "2-digit", second: "2-digit" }
      : { hour: "2-digit", minute: "2-digit" };
    el.innerHTML = `
      <div class="hb-status">
        <span class="hb-dot" aria-hidden="true"></span>
        <span class="hb-state">…</span>
      </div>
      <div class="hb-cell">${t("widget.heartbeat.seq")} <strong data-bind="seq">–</strong></div>
      <div class="hb-cell">${t("widget.heartbeat.uptime")} <strong data-bind="uptime">–</strong></div>
      <div class="hb-spacer"></div>
      <div class="hb-cell"><strong data-bind="now"></strong></div>
    `;
    this._tick = this._tick.bind(this);
    // Tick fast if seconds are visible, otherwise once every half minute.
    this._timer = setInterval(this._tick, this._showSeconds ? 500 : 30_000);
    this._statusObs = new MutationObserver(() => this._renderStatus());
    this._statusObs.observe(document.body, {
      attributes: true,
      attributeFilter: ["data-ws-status"],
    });
    this._renderStatus();
    this._tick();
  }

  _renderStatus() {
    const STATUS_KEYS = {
      connecting: "widget.heartbeat.status.connecting",
      connected: "widget.heartbeat.status.connected",
      disconnected: "widget.heartbeat.status.disconnected",
      closed: "widget.heartbeat.status.closed",
    };
    const raw = document.body.dataset.wsStatus || "?";
    this.el.querySelector(".hb-state").textContent =
      STATUS_KEYS[raw] ? t(STATUS_KEYS[raw]) : raw;
  }

  _tick() {
    this.el.querySelector('[data-bind="now"]').textContent =
      new Date().toLocaleTimeString(getLang(), this._timeFmtOpts);
  }

  update(data, _moduleName, _ts) {
    this.el.querySelector('[data-bind="seq"]').textContent = data.seq;
    const up = Number(data.uptime);
    this.el.querySelector('[data-bind="uptime"]').textContent =
      this._showSeconds ? `${up.toFixed(1)} s` : fmtDuration(up);
  }

  destroy() {
    clearInterval(this._timer);
    this._statusObs?.disconnect();
  }
}

registerWidget("heartbeat", HeartbeatWidget);
