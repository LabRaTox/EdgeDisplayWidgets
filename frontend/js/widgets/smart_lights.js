// Smart lights: per-device toggle + brightness slider, unified across
// Govee and Tuya providers. Backend exposes one normalised device list;
// this widget only needs to know about `id`, `on`, `brightness`, etc.

import { registerWidget } from "../registry.js";
import { t } from "../i18n.js";

const PROVIDER_LABEL = { govee: "Govee", tuya: "Tuya" };

// Preset color palette: one-tap shortcuts above the native picker. Titles
// resolve to the current locale at render time via t().
const COLOR_PRESETS = [
  { hex: "#ff3030", titleKey: "widget.smart_lights.color.red" },
  { hex: "#ff8a1a", titleKey: "widget.smart_lights.color.orange" },
  { hex: "#ffe066", titleKey: "widget.smart_lights.color.warmwhite" },
  { hex: "#a0ff60", titleKey: "widget.smart_lights.color.lime" },
  { hex: "#30c2ff", titleKey: "widget.smart_lights.color.cyan" },
  { hex: "#7a4dff", titleKey: "widget.smart_lights.color.violet" },
  { hex: "#ffffff", titleKey: "widget.smart_lights.color.white" },
];

function hexToRgb(hex) {
  const s = hex.replace("#", "");
  return {
    r: parseInt(s.slice(0, 2), 16),
    g: parseInt(s.slice(2, 4), 16),
    b: parseInt(s.slice(4, 6), 16),
  };
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

class SmartLightsWidget {
  static modules = ["smart_lights"];

  mount(el) {
    this.el = el;
    el.classList.add("smart-lights-widget");
    el.innerHTML = `
      <div class="sl-list" data-bind="list">
        <div class="sl-empty">…</div>
      </div>
      <div class="sl-errors" data-bind="errors" hidden></div>
    `;
    this._cells = new Map(); // id -> { row, toggle, slider, value, name }
    this._lastKey = "";
    // Local optimistic state so the UI doesn't jump while we wait for the
    // next 30 s poll to reflect the change.
    this._optimistic = new Map(); // id -> {on?, brightness?}
  }

  update(data) {
    const list = this.el.querySelector('[data-bind="list"]');
    const errBox = this.el.querySelector('[data-bind="errors"]');
    const devices = data?.devices || [];
    const errors = data?.errors || {};

    // ---- errors strip (only show real failures, not "not configured")
    const realErrors = Object.entries(errors)
      .filter(([_, msg]) => msg && msg !== "not configured");
    if (realErrors.length === 0) {
      errBox.hidden = true;
      errBox.textContent = "";
    } else {
      errBox.hidden = false;
      errBox.textContent = realErrors
        .map(([prov, msg]) => `${PROVIDER_LABEL[prov] || prov}: ${msg}`)
        .join("  •  ");
    }

    if (devices.length === 0) {
      const unconfigured = Object.entries(errors)
        .filter(([_, msg]) => msg === "not configured")
        .map(([prov]) => PROVIDER_LABEL[prov] || prov);
      list.innerHTML = `<div class="sl-empty">${
        unconfigured.length
          ? t("widget.smart_lights.not_configured", { providers: unconfigured.join(" + ") })
          : t("widget.smart_lights.no_devices")
      }</div>`;
      this._cells.clear();
      this._lastKey = "";
      return;
    }

    // Re-render row layout only when the device set changes.
    const key = devices.map((d) => d.id).join("|");
    if (key !== this._lastKey) {
      list.innerHTML = "";
      this._cells.clear();
      for (const d of devices) {
        const row = this._buildRow(d);
        list.appendChild(row.row);
        this._cells.set(d.id, row);
      }
      this._lastKey = key;
    }

    // Patch values
    for (const d of devices) {
      const cell = this._cells.get(d.id);
      if (!cell) continue;
      const opt = this._optimistic.get(d.id) || {};
      const on = opt.on ?? d.on;
      const brightness = opt.brightness ?? d.brightness;
      this._applyState(cell, d, on, brightness);
    }
  }

  _buildRow(d) {
    const row = document.createElement("div");
    row.className = "sl-row";
    row.dataset.id = d.id;
    row.dataset.provider = d.provider;
    row.innerHTML = `
      <div class="sl-head">
        <span class="sl-name" data-bind="name">${escapeHtml(d.name)}</span>
        <button type="button" class="sl-toggle" data-act="toggle" aria-label="${t("widget.smart_lights.toggle")}">
          <span class="sl-toggle-knob"></span>
        </button>
      </div>
      <div class="sl-bright" data-bind="bright" ${d.has_brightness ? "" : "hidden"}>
        <input type="range" min="1" max="100" step="1" class="sl-slider"
               data-act="brightness" aria-label="${t("widget.smart_lights.brightness")}">
        <span class="sl-value" data-bind="value">–</span>
      </div>
      <div class="sl-color" data-bind="color" ${d.has_color ? "" : "hidden"}>
        <div class="sl-swatches">
          ${COLOR_PRESETS.map((p) => {
            const title = t(p.titleKey);
            return `<button type="button" class="sl-swatch"
                       style="background:${p.hex}"
                       data-color="${p.hex}" title="${title}"
                       aria-label="${title}"></button>`;
          }).join("")}
          <label class="sl-picker" title="${t("widget.smart_lights.custom_color")}">
            <input type="color" data-act="color-picker" value="#ffaa00">
            <span aria-hidden="true">🎨</span>
          </label>
        </div>
      </div>
      <div class="sl-foot">
        <span class="sl-provider">${PROVIDER_LABEL[d.provider] || d.provider}</span>
        <span class="sl-status" data-bind="status"></span>
      </div>
    `;
    const cell = {
      row,
      name: row.querySelector('[data-bind="name"]'),
      toggle: row.querySelector('[data-act="toggle"]'),
      slider: row.querySelector('[data-act="brightness"]'),
      value: row.querySelector('[data-bind="value"]'),
      status: row.querySelector('[data-bind="status"]'),
    };
    cell.toggle.addEventListener("click", () => this._toggle(d.id, cell));
    cell.slider.addEventListener("change", (e) =>
      this._setBrightness(d.id, parseInt(e.target.value, 10), cell),
    );
    if (d.has_color) {
      for (const swatch of row.querySelectorAll("[data-color]")) {
        swatch.addEventListener("click", () =>
          this._setColor(d.id, swatch.dataset.color, cell),
        );
      }
      const picker = row.querySelector('[data-act="color-picker"]');
      // `change` fires when the user closes the native picker — better than
      // `input` which would fire continuously while they're dragging.
      picker.addEventListener("change", (e) =>
        this._setColor(d.id, e.target.value, cell),
      );
    }
    return cell;
  }

  _applyState(cell, d, on, brightness) {
    cell.name.textContent = d.name;
    cell.row.classList.toggle("is-on", !!on);
    cell.row.classList.toggle("is-offline", !d.online);
    cell.toggle.disabled = !d.online;
    if (brightness != null) {
      cell.slider.value = String(brightness);
      cell.value.textContent = `${brightness}%`;
    } else {
      cell.value.textContent = "–";
    }
    cell.slider.disabled = !d.has_brightness || !d.online || !on;
  }

  // --------------------------------------------------------- control

  async _toggle(id, cell) {
    const wasOn = cell.row.classList.contains("is-on");
    const next = !wasOn;
    this._optimistic.set(id, {
      ...(this._optimistic.get(id) || {}),
      on: next,
    });
    cell.row.classList.toggle("is-on", next);
    cell.slider.disabled = !next || cell.slider.disabled;
    await this._send(id, cell, next ? "on" : "off");
  }

  async _setBrightness(id, level, cell) {
    this._optimistic.set(id, {
      ...(this._optimistic.get(id) || {}),
      brightness: level,
    });
    cell.value.textContent = `${level}%`;
    await this._send(id, cell, "brightness", level);
  }

  async _setColor(id, hex, cell) {
    // Govee/Tuya color commands typically require the light to be on;
    // flip the toggle first if it's off so the user isn't confused.
    if (!cell.row.classList.contains("is-on")) {
      await this._toggle(id, cell);
    }
    await this._send(id, cell, "color", hexToRgb(hex));
  }

  async _send(id, cell, action, value) {
    cell.row.classList.add("is-pending");
    cell.status.textContent = "";
    try {
      const r = await fetch(
        `/api/smart_lights/${encodeURIComponent(id)}/control`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, value }),
        },
      );
      const body = await r.json().catch(() => ({}));
      if (!r.ok || !body.ok) {
        const msg = body.error || `HTTP ${r.status}`;
        cell.status.textContent = msg;
        cell.status.classList.add("is-error");
        // Roll back optimistic change so the UI doesn't lie.
        this._optimistic.delete(id);
        setTimeout(() => cell.status.classList.remove("is-error"), 2000);
        return;
      }
      // Keep optimistic state until the next poll; clear it after a grace
      // period so a slow refresh doesn't strand us on stale values.
      setTimeout(() => this._optimistic.delete(id), 5000);
    } catch (err) {
      console.error("[smart_lights] control failed:", err);
      this._optimistic.delete(id);
      cell.status.textContent = err.message;
      cell.status.classList.add("is-error");
    } finally {
      cell.row.classList.remove("is-pending");
    }
  }

  destroy() {}
}

registerWidget("smart_lights", SmartLightsWidget);
