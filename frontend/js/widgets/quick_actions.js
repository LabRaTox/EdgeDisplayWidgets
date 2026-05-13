// Quick Actions: configurable touch buttons that fire backend-defined
// commands or HTTP requests. The frontend only knows opaque ids — the
// actual command/URL/headers live in the backend config.

import { registerWidget } from "../registry.js";
import { confirmDialog } from "../confirm.js";
import { t } from "../i18n.js";

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

function isDestructive(action) {
  const haystack = `${action.id} ${action.label || ""}`.toLowerCase();
  return /reboot|shutdown|poweroff|restart|neustart|herunterfahren|delete|löschen/.test(haystack);
}

class QuickActionsWidget {
  static modules = ["quick_actions"];

  mount(el) {
    this.el = el;
    el.classList.add("quick-actions-widget");
    el.innerHTML = `
      <div class="qa-grid" data-bind="grid">
        <div class="qa-empty">…</div>
      </div>
    `;
    this._lastKey = "";
  }

  update(data) {
    const grid = this.el.querySelector('[data-bind="grid"]');
    const actions = data?.actions || [];
    if (actions.length === 0) {
      grid.innerHTML = `<div class="qa-empty">${t("widget.quick_actions.empty")}</div>`;
      this._lastKey = "";
      return;
    }
    // Rebuild only when the set/order of actions changes.
    const key = actions.map((a) => `${a.id}:${a.label}:${a.icon}:${a.confirm}`).join("|");
    if (key === this._lastKey) return;
    this._lastKey = key;
    grid.innerHTML = "";
    for (const action of actions) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "qa-btn";
      btn.dataset.id = action.id;
      if (action.confirm) btn.classList.add("has-confirm");
      btn.innerHTML = `
        <div class="qa-icon">${escapeHtml(action.icon || "•")}</div>
        <div class="qa-label">${escapeHtml(action.label || action.id)}</div>
      `;
      btn.addEventListener("click", () => this._run(action, btn));
      grid.appendChild(btn);
    }
  }

  async _run(action, btn) {
    if (action.confirm) {
      const ok = await confirmDialog(
        t("widget.quick_actions.run_confirm", { label: action.label || action.id }),
        { okLabel: t("common.run"), danger: isDestructive(action) },
      );
      if (!ok) return;
    }

    btn.disabled = true;
    btn.classList.remove("is-ok", "is-err");
    btn.classList.add("is-pending");
    try {
      const r = await fetch(
        `/api/quick_actions/${encodeURIComponent(action.id)}/run`,
        { method: "POST" },
      );
      let body = {};
      try {
        body = await r.json();
      } catch (_) {
        /* leave body empty */
      }
      if (r.ok && body.ok) {
        this._flash(btn, "ok");
      } else {
        const msg = body.error
          || (body.exit_code != null ? `exit ${body.exit_code}` : "")
          || (body.status_code != null ? `HTTP ${body.status_code}` : "")
          || `HTTP ${r.status}`;
        console.error(`[quick_actions] '${action.id}' failed:`, body);
        this._flash(btn, "err", msg);
      }
    } catch (err) {
      console.error(`[quick_actions] '${action.id}' network error:`, err);
      this._flash(btn, "err", err.message);
    } finally {
      btn.disabled = false;
      btn.classList.remove("is-pending");
    }
  }

  _flash(btn, state, msg) {
    btn.classList.add(state === "ok" ? "is-ok" : "is-err");
    if (msg) btn.title = msg;
    setTimeout(() => {
      btn.classList.remove("is-ok", "is-err");
      btn.removeAttribute("title");
    }, 1800);
  }

  destroy() {}
}

registerWidget("quick_actions", QuickActionsWidget);
