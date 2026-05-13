import { registerWidget } from "../registry.js";
import { t } from "../i18n.js";

function classify(temp) {
  if (temp == null) return "";
  if (temp >= 85) return "is-hot";
  if (temp >= 70) return "is-warm";
  if (temp <= 0)  return "is-cold";
  return "";
}

class SensorsWidget {
  static modules = ["sensors"];

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <h3>${t("widget.sensors.title")}</h3>
      <div class="sensors-list" data-bind="list">
        <div class="sensors-empty">…</div>
      </div>
    `;
    this._cells = new Map(); // id -> {row, value}
  }

  update(data) {
    const list = this.el.querySelector('[data-bind="list"]');
    if (!data?.available) {
      list.innerHTML = `<div class="sensors-empty">${data?.reason || t("common.unavailable")}</div>`;
      this._cells.clear();
      return;
    }
    const readings = data.readings || [];
    if (readings.length === 0) {
      list.innerHTML = `<div class="sensors-empty">${t("widget.sensors.empty")}</div>`;
      this._cells.clear();
      return;
    }

    // Re-render only when the set of readings changes; otherwise just patch values.
    const ids = readings.map((r) => r.id).join("|");
    if (ids !== this._lastIds) {
      list.innerHTML = "";
      this._cells.clear();
      for (const r of readings) {
        const row = document.createElement("div");
        row.className = "sensors-row";
        if (r.primary) row.classList.add("is-primary");
        const chip = r.display_chip || r.chip;
        const label = r.display_label || r.label;
        row.innerHTML = `
          <span class="sensors-chip">${chip}</span>
          <span class="sensors-label">${label}</span>
          <span class="sensors-value">–</span>
        `;
        list.appendChild(row);
        this._cells.set(r.id, {
          row,
          value: row.querySelector(".sensors-value"),
        });
      }
      this._lastIds = ids;
    }

    for (const r of readings) {
      const cell = this._cells.get(r.id);
      if (!cell) continue;
      cell.value.textContent = `${r.temp_c.toFixed(1)}°C`;
      cell.row.classList.remove("is-hot", "is-warm", "is-cold");
      const cls = classify(r.temp_c);
      if (cls) cell.row.classList.add(cls);
    }
  }

  destroy() {}
}

registerWidget("sensors", SensorsWidget);
