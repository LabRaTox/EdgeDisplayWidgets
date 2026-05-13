// Notes widget: tabs + plain-text editor, backend-persisted.
//
// Auto-saves with a 600 ms debounce; switching tabs flushes pending saves
// first so a quick edit-then-switch doesn't drop the change.

import { registerWidget } from "../registry.js";
import { confirmDialog } from "../confirm.js";
import { t } from "../i18n.js";

const DEBOUNCE_MS = 600;

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

class NotesWidget {
  static modules = [];

  mount(el) {
    this.el = el;
    el.classList.add("notes-widget");
    el.innerHTML = `
      <div class="notes-tabs" data-bind="tabs"></div>
      <div class="notes-body">
        <input type="text" class="notes-title" data-bind="title"
               placeholder="${t("widget.notes.title_placeholder")}" maxlength="200">
        <textarea class="notes-text" data-bind="text"
                  placeholder="${t("widget.notes.body_placeholder")}" spellcheck="false"></textarea>
        <div class="notes-status" data-bind="status"></div>
      </div>
    `;

    this._notes = [];
    this._activeId = null;
    this._pending = null;
    this._saveTimer = null;
    this._titleEl = el.querySelector('[data-bind="title"]');
    this._textEl = el.querySelector('[data-bind="text"]');
    this._tabsEl = el.querySelector('[data-bind="tabs"]');
    this._statusEl = el.querySelector('[data-bind="status"]');

    this._titleEl.addEventListener("input", () => this._schedule());
    this._textEl.addEventListener("input", () => this._schedule());
    // Flush on blur so a tap outside the widget commits the latest text.
    this._titleEl.addEventListener("blur", () => this._flush());
    this._textEl.addEventListener("blur", () => this._flush());

    this._refresh();
  }

  destroy() {
    clearTimeout(this._saveTimer);
  }

  // ----------------------------------------------------- data

  async _refresh() {
    try {
      const r = await fetch("/api/notes");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      this._notes = data.notes || [];
    } catch (err) {
      console.error("[notes] load failed:", err);
      this._setStatus(t("widget.notes.load_failed"), true);
      return;
    }
    if (this._notes.length === 0) {
      await this._createNote(t("widget.notes.new_note"), "");
      return;
    }
    if (!this._notes.find((n) => n.id === this._activeId)) {
      this._activeId = this._notes[0].id;
    }
    this._render();
  }

  _activeNote() {
    return this._notes.find((n) => n.id === this._activeId) || null;
  }

  async _createNote(title = t("widget.notes.new_note"), body = "") {
    try {
      const r = await fetch("/api/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, body }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const note = await r.json();
      this._notes.push(note);
      this._activeId = note.id;
      this._render();
      this._titleEl.focus();
      this._titleEl.select();
    } catch (err) {
      console.error("[notes] create failed:", err);
      this._setStatus(t("widget.notes.create_failed"), true);
    }
  }

  async _deleteNote(id) {
    const ok = await confirmDialog(t("widget.notes.delete_confirm"), {
      okLabel: t("common.delete"),
      danger: true,
    });
    if (!ok) return;
    try {
      const r = await fetch(`/api/notes/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (!r.ok && r.status !== 404) throw new Error(`HTTP ${r.status}`);
      this._notes = this._notes.filter((n) => n.id !== id);
      if (this._activeId === id) {
        this._activeId = this._notes[0]?.id ?? null;
      }
      if (this._notes.length === 0) {
        await this._createNote(t("widget.notes.new_note"), "");
        return;
      }
      this._render();
    } catch (err) {
      console.error("[notes] delete failed:", err);
      this._setStatus(t("widget.notes.delete_failed"), true);
    }
  }

  // ----------------------------------------------------- save / debounce

  _schedule() {
    const note = this._activeNote();
    if (!note) return;
    this._pending = {
      id: note.id,
      title: this._titleEl.value,
      body: this._textEl.value,
    };
    clearTimeout(this._saveTimer);
    this._setStatus("…", false);
    this._saveTimer = setTimeout(() => this._flush(), DEBOUNCE_MS);
  }

  async _flush() {
    if (!this._pending) return;
    const payload = this._pending;
    this._pending = null;
    clearTimeout(this._saveTimer);
    try {
      const r = await fetch("/api/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const saved = await r.json();
      const idx = this._notes.findIndex((n) => n.id === saved.id);
      if (idx >= 0) this._notes[idx] = saved;
      this._renderTabs();
      this._setStatus(t("common.saved"), false);
    } catch (err) {
      console.error("[notes] save failed:", err);
      this._setStatus(t("widget.notes.save_failed"), true);
    }
  }

  _setStatus(msg, isError) {
    this._statusEl.textContent = msg || "";
    this._statusEl.classList.toggle("is-error", !!isError);
  }

  // ----------------------------------------------------- render

  _render() {
    this._renderTabs();
    this._renderBody();
  }

  _renderTabs() {
    this._tabsEl.innerHTML = "";
    for (const n of this._notes) {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.className = "notes-tab";
      tab.dataset.id = n.id;
      if (n.id === this._activeId) tab.classList.add("is-active");
      tab.textContent = n.title || t("widget.notes.untitled");
      tab.addEventListener("click", () => this._switchTo(n.id));
      this._tabsEl.appendChild(tab);
    }
    const add = document.createElement("button");
    add.type = "button";
    add.className = "notes-tab notes-tab-add";
    add.textContent = "+";
    add.title = t("widget.notes.new_note");
    add.addEventListener("click", async () => {
      await this._flush();
      this._createNote();
    });
    this._tabsEl.appendChild(add);

    if (this._activeNote()) {
      const del = document.createElement("button");
      del.type = "button";
      del.className = "notes-tab notes-tab-del";
      del.textContent = "×";
      del.title = t("widget.notes.delete_active");
      del.addEventListener("click", () => this._deleteNote(this._activeId));
      this._tabsEl.appendChild(del);
    }
  }

  _renderBody() {
    const note = this._activeNote();
    if (!note) {
      this._titleEl.value = "";
      this._textEl.value = "";
      this._titleEl.disabled = true;
      this._textEl.disabled = true;
      return;
    }
    this._titleEl.disabled = false;
    this._textEl.disabled = false;
    if (document.activeElement !== this._titleEl) {
      this._titleEl.value = note.title;
    }
    if (document.activeElement !== this._textEl) {
      this._textEl.value = note.body;
    }
  }

  async _switchTo(id) {
    if (id === this._activeId) return;
    await this._flush();
    this._activeId = id;
    this._render();
  }
}

registerWidget("notes", NotesWidget);
