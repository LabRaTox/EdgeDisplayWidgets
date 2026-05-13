import { registerWidget } from "../registry.js";
import { t } from "../i18n.js";

const GiB = 1024 ** 3;
const MiB = 1024 ** 2;

function fmtBytes(n) {
  if (n >= GiB) return (n / GiB).toFixed(1) + " GiB";
  if (n >= MiB) return (n / MiB).toFixed(0) + " MiB";
  return n + " B";
}

class DiskUsageWidget {
  static modules = ["disk_usage"];

  mount(el) {
    this.el = el;
    el.classList.add("disk-usage-widget");
    el.innerHTML = `
      <h3>${t("widget.disk.title")}</h3>
      <div class="disk-list" data-bind="list">
        <div class="disk-empty">…</div>
      </div>
    `;
    this._cells = new Map();
    this._lastKey = "";
  }

  update(data) {
    const list = this.el.querySelector('[data-bind="list"]');
    const disks = data?.disks || [];
    if (disks.length === 0) {
      list.innerHTML = `<div class="disk-empty">${t("widget.disk.empty")}</div>`;
      this._cells.clear();
      this._lastKey = "";
      return;
    }

    const key = disks.map((d) => d.mountpoint).join("|");
    if (key !== this._lastKey) {
      list.innerHTML = "";
      this._cells.clear();
      for (const d of disks) {
        const row = document.createElement("div");
        row.className = "disk-row";
        row.innerHTML = `
          <div class="disk-head">
            <span class="disk-mount" title="${escapeAttr(d.device || "")}">${escapeHtml(d.mountpoint)}</span>
            <span class="disk-value" data-bind="value">–</span>
          </div>
          <div class="disk-bar"><div class="disk-fill" data-bind="fill"></div></div>
          <div class="disk-meta" data-bind="meta"></div>
        `;
        list.appendChild(row);
        this._cells.set(d.mountpoint, {
          row,
          value: row.querySelector('[data-bind="value"]'),
          fill: row.querySelector('[data-bind="fill"]'),
          meta: row.querySelector('[data-bind="meta"]'),
        });
      }
      this._lastKey = key;
    }

    for (const d of disks) {
      const cell = this._cells.get(d.mountpoint);
      if (!cell) continue;
      cell.value.textContent = `${d.percent.toFixed(0)}%`;
      cell.fill.style.width = `${Math.min(100, d.percent)}%`;
      cell.fill.classList.toggle("is-warn", d.percent >= 80 && d.percent < 90);
      cell.fill.classList.toggle("is-bad", d.percent >= 90);
      cell.meta.textContent = `${fmtBytes(d.used)} / ${fmtBytes(d.total)} • ${d.fstype}`;
    }
  }

  destroy() {}
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}
function escapeAttr(s) {
  return String(s).replace(/"/g, "&quot;");
}

registerWidget("disk_usage", DiskUsageWidget);
