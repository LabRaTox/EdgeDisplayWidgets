import { registerWidget } from "../registry.js";
import { t } from "../i18n.js";

const GiB = 1024 ** 3;
const MiB = 1024 ** 2;

function fmtBytes(n) {
  if (n >= GiB) return (n / GiB).toFixed(1) + " GiB";
  if (n >= MiB) return (n / MiB).toFixed(0) + " MiB";
  return Math.round(n / 1024) + " KiB";
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

class TopProcessesWidget {
  static modules = ["top_processes"];

  mount(el) {
    this.el = el;
    el.classList.add("top-processes-widget");
    el.innerHTML = `
      <h3>${t("widget.top_processes.title")}</h3>
      <div class="proc-list" data-bind="list">
        <div class="proc-empty">…</div>
      </div>
    `;
  }

  update(data) {
    const list = this.el.querySelector('[data-bind="list"]');
    const rows = data?.processes || [];
    if (rows.length === 0) {
      list.innerHTML = `<div class="proc-empty">${t("widget.top_processes.empty")}</div>`;
      return;
    }
    list.innerHTML = rows
      .map(
        (p) => `
        <div class="proc-row">
          <span class="proc-name" title="PID ${p.pid}${p.user ? " · " + escapeHtml(p.user) : ""}">${escapeHtml(p.name)}</span>
          <span class="proc-cpu">${p.cpu_percent.toFixed(1)}%</span>
          <span class="proc-mem">${fmtBytes(p.rss)}</span>
        </div>`,
      )
      .join("");
  }

  destroy() {}
}

registerWidget("top_processes", TopProcessesWidget);
