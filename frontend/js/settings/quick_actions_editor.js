// Quick Actions editor — GUI for the "Aktionen" tab in the Settings sheet.
//
// Buffers edits in a JS model, posts the full list to
// /api/quick_actions/config on Save. Drag-and-drop reorder uses pointer
// events so it works on mouse + touch.

import { confirmDialog } from "../confirm.js";
import { t } from "../i18n.js";
import { iconMarkup } from "../lib/icon.js";
import { openIconPicker } from "../lib/icon_picker.js";

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

function escapeAttr(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

function emptyAction() {
  return {
    id: "",
    label: "",
    icon: "",
    kind: "shell",
    confirm: false,
    color: "",
    text_color: "",
    w: 1,
    h: 1,
    command: [],
    url: "",
    method: "POST",
    headers: {},
    params: {},
    json: null,
    page: 0,
    x: null,
    y: null,
    tiles: [],
    status: null,
  };
}

function emptyStatus() {
  return { kind: "shell", command: [], url: "", method: "GET", headers: {}, match: "" };
}

const DEFAULT_TILE_BG = "#1b2733";
const DEFAULT_TILE_FG = "#e6edf3";

function clampSpan(v) {
  const n = Math.round(Number(v) || 1);
  return Math.min(Math.max(1, n), 4);
}

function normalizeStatus(raw) {
  const s = { ...emptyStatus(), ...(raw || {}) };
  s.command = Array.isArray(s.command) ? [...s.command] : [];
  s.headers = s.headers && typeof s.headers === "object" ? { ...s.headers } : {};
  s.match = s.match || "";
  return s;
}

function normalizeAction(raw) {
  // Merge a server-supplied action with the editor's expected shape so
  // every field exists (including the kind-specific defaults that the
  // server omits via exclude_defaults).
  const a = { ...emptyAction(), ...(raw || {}) };
  a.command = Array.isArray(a.command) ? [...a.command] : [];
  a.detach = !!a.detach;
  a.headers = a.headers && typeof a.headers === "object" ? { ...a.headers } : {};
  a.params = a.params && typeof a.params === "object" ? { ...a.params } : {};
  a.color = a.color || "";
  a.text_color = a.text_color || "";
  a.w = clampSpan(a.w);
  a.h = clampSpan(a.h);
  a.page = Number.isInteger(a.page) ? a.page : 0;
  a.x = Number.isInteger(a.x) ? a.x : null;
  a.y = Number.isInteger(a.y) ? a.y : null;
  a.back_x = Number.isInteger(a.back_x) ? a.back_x : 0;
  a.back_y = Number.isInteger(a.back_y) ? a.back_y : 0;
  a.tiles = Array.isArray(a.tiles) ? a.tiles.map(normalizeAction) : [];
  a.status = a.status ? normalizeStatus(a.status) : null;
  return a;
}

// Convert the editor's action shape back to the server-side schema.
// Strips empty/default values so config.local.yaml stays readable.
function serializeAction(a) {
  const out = { id: a.id, kind: a.kind };
  if (a.label) out.label = a.label;
  if (a.icon) out.icon = a.icon;
  if (a.confirm && a.kind !== "folder") out.confirm = true;
  if (a.color) out.color = a.color;
  if (a.text_color) out.text_color = a.text_color;
  if (a.w && a.w !== 1) out.w = clampSpan(a.w);
  if (a.h && a.h !== 1) out.h = clampSpan(a.h);
  if (a.page) out.page = a.page;
  if (Number.isInteger(a.x)) out.x = a.x;
  if (Number.isInteger(a.y)) out.y = a.y;
  if (a.kind === "shell") {
    out.command = a.command.filter((arg) => arg.length > 0);
    if (a.detach) out.detach = true;
  } else if (a.kind === "http") {
    out.url = a.url || "";
    if (a.method && a.method.toUpperCase() !== "POST") out.method = a.method.toUpperCase();
    if (a.headers && Object.keys(a.headers).length) out.headers = a.headers;
    if (a.params && Object.keys(a.params).length) out.params = a.params;
    if (a.json !== null && a.json !== undefined && a.json !== "") out.json = a.json;
  } else if (a.kind === "folder") {
    out.tiles = (a.tiles || []).map(serializeAction);
    if (a.back_x) out.back_x = a.back_x;
    if (a.back_y) out.back_y = a.back_y;
  }
  if (a.kind !== "folder" && a.status) {
    out.status = serializeStatus(a.status);
  }
  return out;
}

function serializeStatus(s) {
  const out = { kind: s.kind };
  if (s.kind === "shell") {
    out.command = (s.command || []).filter((arg) => arg.length > 0);
  } else {
    out.url = s.url || "";
    if (s.method && s.method.toUpperCase() !== "GET") out.method = s.method.toUpperCase();
    if (s.headers && Object.keys(s.headers).length) out.headers = s.headers;
  }
  if (s.match) out.match = s.match;
  return out;
}

function parseJsonOrNull(s) {
  const t = (s || "").trim();
  if (!t) return null;
  try {
    return JSON.parse(t);
  } catch (_) {
    return undefined; // signals "invalid"
  }
}

function jsonToText(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch (_) {
    return "";
  }
}


/**
 * Mount the Quick Actions editor into `rootEl`.
 *
 * @param {HTMLElement} rootEl
 * @param {{flashToast: (msg: string, isError?: boolean) => void}} opts
 */
export function mountQuickActionsEditor(rootEl, { flashToast }) {
  // Editor state — a buffer of actions (a tree). Saved only when the user
  // clicks "Speichern" so changes can be discarded by closing the sheet.
  let rootActions = [];
  let path = []; // folder objects from the root to the level being edited
  let actions = []; // tiles at the current level — a reference into the tree
  let timeoutSeconds = 30.0;
  let columns = 4;
  let rows = 3;
  let dirty = false;

  rootEl.innerHTML = `
    <div class="qa-editor">
      <div class="qa-editor-bar">
        <button class="btn" type="button" data-act="add">${t("qa_editor.add")}</button>
        <span class="qa-editor-meta" data-bind="meta"></span>
        <span class="qa-editor-spacer"></span>
        <label class="qa-grid-setting">
          <span>${t("qa_editor.grid")}</span>
          <input type="number" min="1" max="8" class="qa-grid-num" data-bind="cols">
          <span class="qa-grid-x">×</span>
          <input type="number" min="1" max="8" class="qa-grid-num" data-bind="rows">
        </label>
        <button class="btn" type="button" data-act="reset" hidden>${t("common.discard")}</button>
        <button class="btn btn-primary" type="button" data-act="save">${t("common.save")}</button>
      </div>
      <nav class="qa-breadcrumb" data-bind="crumbs" hidden></nav>
      <div class="qa-editor-list" data-bind="list">
        <div class="settings-empty">${t("common.loading")}</div>
      </div>
    </div>
  `;

  const listEl = rootEl.querySelector('[data-bind="list"]');
  const metaEl = rootEl.querySelector('[data-bind="meta"]');
  const crumbsEl = rootEl.querySelector('[data-bind="crumbs"]');
  const resetBtn = rootEl.querySelector('[data-act="reset"]');
  const addBtn = rootEl.querySelector('[data-act="add"]');
  const saveBtn = rootEl.querySelector('[data-act="save"]');
  const colsInput = rootEl.querySelector('[data-bind="cols"]');
  const rowsInput = rootEl.querySelector('[data-bind="rows"]');

  const clampGrid = (v) => Math.min(Math.max(1, Math.round(Number(v) || 1)), 8);
  colsInput.addEventListener("change", () => {
    columns = clampGrid(colsInput.value);
    colsInput.value = columns;
    markDirty();
  });
  rowsInput.addEventListener("change", () => {
    rows = clampGrid(rowsInput.value);
    rowsInput.value = rows;
    markDirty();
  });

  // ---- Folder navigation -------------------------------------------------
  // `path` holds folder *objects* (not ids), so renaming a folder's id while
  // inside it can't break navigation. `actions` is re-pointed at the current
  // level's `tiles` array; all mutations happen in place so the tree stays
  // linked.
  function setLevel() {
    actions = path.length ? path[path.length - 1].tiles : rootActions;
    renderBreadcrumb();
  }
  function renderBreadcrumb() {
    if (!path.length) {
      crumbsEl.hidden = true;
      crumbsEl.innerHTML = "";
      return;
    }
    crumbsEl.hidden = false;
    const parts = [`<button type="button" class="qa-crumb" data-crumb="-1">${t("qa_editor.root")}</button>`];
    path.forEach((f, i) => {
      parts.push(`<span class="qa-crumb-sep">›</span>`);
      parts.push(`<button type="button" class="qa-crumb" data-crumb="${i}">${escapeAttr(f.label || f.id || "…")}</button>`);
    });
    crumbsEl.innerHTML = parts.join("");
  }
  function openFolder(a) {
    if (!a.id) {
      flashToast(t("qa_editor.folder_needs_id"), true);
      return;
    }
    path = [...path, a];
    setLevel();
    renderList();
    metaCount(); // navigation preserves the dirty flag, just refreshes the count
  }
  crumbsEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".qa-crumb");
    if (!btn) return;
    const i = Number(btn.dataset.crumb);
    path = i < 0 ? [] : path.slice(0, i + 1);
    setLevel();
    renderList();
    metaCount();
  });

  function metaCount() {
    if (dirty) {
      metaEl.textContent = t("common.unsaved");
      return;
    }
    metaEl.textContent = actions.length === 1
      ? t("qa_editor.action_count_one", { count: actions.length })
      : t("qa_editor.action_count_other", { count: actions.length });
  }
  function markDirty() {
    dirty = true;
    resetBtn.hidden = false;
    metaEl.textContent = t("common.unsaved");
  }
  function markClean() {
    dirty = false;
    resetBtn.hidden = true;
    metaCount();
  }

  async function load() {
    listEl.innerHTML = `<div class="settings-empty">${t("common.loading")}</div>`;
    try {
      const r = await fetch("/api/quick_actions/config");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      rootActions = (body.actions || []).map(normalizeAction);
      path = [];
      setLevel();
      timeoutSeconds = body.timeout_seconds ?? 30.0;
      columns = clampGrid(body.columns ?? 4);
      rows = clampGrid(body.rows ?? 3);
      colsInput.value = columns;
      rowsInput.value = rows;
      renderList();
      markClean();
    } catch (err) {
      console.error("[qa-editor] load failed:", err);
      listEl.innerHTML = `<div class="settings-empty">${t("qa_editor.load_error", { reason: escapeAttr(err.message) })}</div>`;
    }
  }

  function renderList() {
    listEl.innerHTML = "";
    if (actions.length === 0) {
      listEl.innerHTML = `<div class="settings-empty">${t("qa_editor.empty_hint")}</div>`;
      return;
    }
    for (const a of actions) {
      listEl.appendChild(renderCard(a));
    }
    setupDragReorder();
  }

  function renderCard(a) {
    const card = document.createElement("div");
    card.className = "qa-card";
    card.dataset.id = a.id || "";

    card.innerHTML = `
      <div class="qa-card-head">
        <button type="button" class="qa-drag" aria-label="${t("qa_editor.drag")}">⋮⋮</button>
        <button type="button" class="qa-icon-btn" data-field="icon"
                aria-label="${t("qa_editor.icon_pick")}">${iconMarkup(a.icon, { fallback: '<span class="qa-icon-empty">+</span>' })}</button>
        <input type="text" class="qa-label-input" data-field="label"
               value="${escapeAttr(a.label)}" placeholder="${t("qa_editor.label_placeholder")}">
        <input type="text" class="qa-id-input" data-field="id"
               value="${escapeAttr(a.id)}" placeholder="action-id" maxlength="64">
        <select class="qa-kind-select" data-field="kind">
          <option value="shell"${a.kind === "shell" ? " selected" : ""}>${t("qa_editor.kind.shell")}</option>
          <option value="http"${a.kind === "http" ? " selected" : ""}>${t("qa_editor.kind.http")}</option>
          <option value="folder"${a.kind === "folder" ? " selected" : ""}>${t("qa_editor.kind.folder")}</option>
        </select>
        <button type="button" class="qa-delete" aria-label="${t("common.delete")}" data-act="delete">×</button>
      </div>
      <div class="qa-card-row" data-bind="actionrow"></div>
      <div class="qa-appearance">
        <label class="qa-appear-field">
          <span>${t("qa_editor.tile_bg")}</span>
          <span class="qa-color-wrap">
            <input type="color" data-field="color" value="${escapeAttr(a.color || DEFAULT_TILE_BG)}"${a.color ? "" : " data-unset=\"1\""}>
            <button type="button" class="qa-color-reset" data-act="reset-color" title="${t("qa_editor.tile_color_default")}">↺</button>
          </span>
        </label>
        <label class="qa-appear-field">
          <span>${t("qa_editor.tile_fg")}</span>
          <span class="qa-color-wrap">
            <input type="color" data-field="text_color" value="${escapeAttr(a.text_color || DEFAULT_TILE_FG)}"${a.text_color ? "" : " data-unset=\"1\""}>
            <button type="button" class="qa-color-reset" data-act="reset-text_color" title="${t("qa_editor.tile_color_default")}">↺</button>
          </span>
        </label>
        <label class="qa-appear-field">
          <span>${t("qa_editor.tile_size")}</span>
          <select data-field="size">
            <option value="1x1"${a.w === 1 && a.h === 1 ? " selected" : ""}>1×1</option>
            <option value="2x1"${a.w === 2 && a.h === 1 ? " selected" : ""}>2×1</option>
            <option value="1x2"${a.w === 1 && a.h === 2 ? " selected" : ""}>1×2</option>
            <option value="2x2"${a.w === 2 && a.h === 2 ? " selected" : ""}>2×2</option>
          </select>
        </label>
      </div>
      <div class="qa-card-body" data-bind="body"></div>
    `;

    renderActionRow(card, a);
    renderKindFields(card, a);
    wireCard(card, a);
    return card;
  }

  // The row between the head and the body: confirm + test for runnable tiles,
  // or an "open folder" affordance for folders.
  function renderActionRow(card, a) {
    const row = card.querySelector('[data-bind="actionrow"]');
    if (a.kind === "folder") {
      const count = (a.tiles || []).length;
      row.innerHTML = `
        <button type="button" class="btn qa-open-folder" data-act="open-folder">${t("qa_editor.open_folder")}</button>
        <span class="qa-folder-count">${count === 1 ? t("qa_editor.folder_count_one", { count }) : t("qa_editor.folder_count_other", { count })}</span>
        <span class="qa-card-spacer"></span>
      `;
    } else {
      row.innerHTML = `
        <label class="qa-checkbox">
          <input type="checkbox" data-field="confirm"${a.confirm ? " checked" : ""}>
          <span>${t("qa_editor.confirm_before_run")}</span>
        </label>
        <span class="qa-card-spacer"></span>
        <button type="button" class="btn qa-test-btn" data-act="test">${t("qa_editor.test_button")}</button>
      `;
    }
  }

  function renderKindFields(card, a) {
    const body = card.querySelector('[data-bind="body"]');
    if (a.kind === "folder") {
      body.innerHTML = `<div class="qa-folder-hint">${t("qa_editor.folder_hint")}</div>`;
      return;
    }
    if (a.kind === "shell") {
      body.innerHTML = `
        <label class="settings-field">
          <span>${t("qa_editor.command_label")} <span class="hint">${t("qa_editor.command_hint")}</span></span>
          <textarea data-field="command" rows="3" class="qa-mono"
            placeholder="loginctl&#10;lock-session">${escapeAttr(a.command.join("\n"))}</textarea>
        </label>
      `;
    } else {
      const headersText = jsonToText(a.headers);
      const paramsText = jsonToText(a.params);
      const bodyText = jsonToText(a.json);
      const methodOpts = METHODS.map(
        (m) => `<option value="${m}"${a.method.toUpperCase() === m ? " selected" : ""}>${m}</option>`,
      ).join("");
      body.innerHTML = `
        <div class="settings-row">
          <label class="settings-field" style="grid-column: span 3">
            <span>URL</span>
            <input type="text" data-field="url" value="${escapeAttr(a.url)}"
                   placeholder="https://homeassistant.local:8123/api/...">
          </label>
          <label class="settings-field">
            <span>${t("qa_editor.method")}</span>
            <select data-field="method">${methodOpts}</select>
          </label>
        </div>
        <label class="settings-field">
          <span>${t("qa_editor.headers")} <span class="hint">${t("qa_editor.headers_hint")}</span></span>
          <textarea data-field="headers" rows="2" class="qa-mono"
            placeholder='{"Authorization":"Bearer …"}'>${escapeAttr(headersText)}</textarea>
        </label>
        <label class="settings-field">
          <span>${t("qa_editor.params")} <span class="hint">${t("qa_editor.params_hint")}</span></span>
          <textarea data-field="params" rows="2" class="qa-mono"
            placeholder='{"entity_id":"all"}'>${escapeAttr(paramsText)}</textarea>
        </label>
        <label class="settings-field">
          <span>${t("qa_editor.body")} <span class="hint">${t("qa_editor.body_hint")}</span></span>
          <textarea data-field="json" rows="3" class="qa-mono"
            placeholder='{"key":"value"}'>${escapeAttr(bodyText)}</textarea>
        </label>
      `;
      body.querySelector('.settings-row').style.gridTemplateColumns = "1fr 1fr 1fr auto";
    }
    // Append the optional live-status probe section (shell + http only).
    const statusWrap = document.createElement("div");
    statusWrap.dataset.bind = "status";
    body.appendChild(statusWrap);
    renderStatusSection(card, a);
  }

  // Live-status probe config: a toggle that reveals a small shell/http probe
  // form. The probe result drives the tile's on/off indicator.
  function renderStatusSection(card, a) {
    const wrap = card.querySelector('[data-bind="status"]');
    if (!wrap) return;
    const on = !!a.status;
    let fields = "";
    if (on) {
      const s = a.status;
      const kindOpts = `
        <option value="shell"${s.kind === "shell" ? " selected" : ""}>${t("qa_editor.kind.shell")}</option>
        <option value="http"${s.kind === "http" ? " selected" : ""}>${t("qa_editor.kind.http")}</option>`;
      let probe;
      if (s.kind === "shell") {
        probe = `
          <label class="settings-field">
            <span>${t("qa_editor.status_command")} <span class="hint">${t("qa_editor.status_command_hint")}</span></span>
            <textarea data-field="status_command" rows="2" class="qa-mono"
              placeholder="cat&#10;/sys/class/leds/.../brightness">${escapeAttr((s.command || []).join("\n"))}</textarea>
          </label>`;
      } else {
        const methodOpts = METHODS.map(
          (m) => `<option value="${m}"${(s.method || "GET").toUpperCase() === m ? " selected" : ""}>${m}</option>`,
        ).join("");
        probe = `
          <div class="settings-row" style="grid-template-columns: 1fr auto">
            <label class="settings-field">
              <span>URL</span>
              <input type="text" data-field="status_url" value="${escapeAttr(s.url || "")}"
                     placeholder="https://homeassistant.local:8123/api/states/...">
            </label>
            <label class="settings-field">
              <span>${t("qa_editor.method")}</span>
              <select data-field="status_method">${methodOpts}</select>
            </label>
          </div>
          <label class="settings-field">
            <span>${t("qa_editor.headers")} <span class="hint">${t("qa_editor.headers_hint")}</span></span>
            <textarea data-field="status_headers" rows="2" class="qa-mono"
              placeholder='{"Authorization":"Bearer …"}'>${escapeAttr(jsonToText(s.headers))}</textarea>
          </label>`;
      }
      fields = `
        <label class="settings-field">
          <span>${t("qa_editor.status_source")}</span>
          <select data-field="status_kind">${kindOpts}</select>
        </label>
        ${probe}
        <label class="settings-field">
          <span>${t("qa_editor.status_match")} <span class="hint">${t("qa_editor.status_match_hint")}</span></span>
          <input type="text" data-field="status_match" value="${escapeAttr(s.match || "")}" placeholder="on|true|1">
        </label>`;
    }
    wrap.className = "qa-status-section";
    wrap.innerHTML = `
      <label class="qa-checkbox qa-status-toggle">
        <input type="checkbox" data-field="status_on"${on ? " checked" : ""}>
        <span>${t("qa_editor.status_enable")}</span>
      </label>
      <div class="qa-status-fields">${fields}</div>
    `;
  }

  function wireCard(card, a) {
    // Generic text/checkbox/select inputs map directly to the action model.
    card.addEventListener("input", (e) => {
      const t = e.target;
      const field = t.dataset?.field;
      if (!field) return;
      if (field === "command") {
        a.command = t.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
      } else if (field === "headers" || field === "params") {
        const parsed = parseJsonOrNull(t.value);
        if (parsed === undefined) {
          t.classList.add("is-invalid");
        } else {
          t.classList.remove("is-invalid");
          a[field] = parsed || {};
        }
      } else if (field === "json") {
        if (t.value.trim() === "") {
          a.json = null;
          t.classList.remove("is-invalid");
        } else {
          const parsed = parseJsonOrNull(t.value);
          if (parsed === undefined) {
            t.classList.add("is-invalid");
          } else {
            t.classList.remove("is-invalid");
            a.json = parsed;
          }
        }
      } else if (field === "confirm") {
        a.confirm = t.checked;
      } else if (field === "color" || field === "text_color") {
        a[field] = t.value;
        t.removeAttribute("data-unset"); // picking a colour activates it
      } else if (field === "size") {
        return; // handled on `change`
      } else if (field === "status_command") {
        a.status.command = t.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
      } else if (field === "status_headers") {
        const parsed = parseJsonOrNull(t.value);
        if (parsed === undefined) {
          t.classList.add("is-invalid");
        } else {
          t.classList.remove("is-invalid");
          a.status.headers = parsed || {};
        }
      } else if (field === "status_url") {
        a.status.url = t.value;
      } else if (field === "status_match") {
        a.status.match = t.value;
      } else if (field === "status_on" || field === "status_kind" || field === "status_method") {
        return; // handled on `change`
      } else if (field === "id") {
        a.id = t.value.trim();
        card.dataset.id = a.id;
      } else {
        a[field] = t.value;
      }
      markDirty();
    });

    card.addEventListener("change", (e) => {
      const t = e.target;
      const field = t.dataset?.field;
      if (field === "kind") {
        a.kind = t.value;
        renderActionRow(card, a);
        renderKindFields(card, a);
        markDirty();
      } else if (field === "size") {
        const [w, h] = t.value.split("x").map((n) => clampSpan(n));
        a.w = w;
        a.h = h;
        markDirty();
      } else if (field === "status_on") {
        a.status = t.checked ? (a.status || normalizeStatus({})) : null;
        renderStatusSection(card, a);
        markDirty();
      } else if (field === "status_kind") {
        a.status.kind = t.value;
        renderStatusSection(card, a);
        markDirty();
      } else if (field === "status_method") {
        a.status.method = t.value;
        markDirty();
      }
    });

    card.addEventListener("click", async (e) => {
      const iconBtn = e.target.closest('.qa-icon-btn');
      if (iconBtn) {
        e.preventDefault();
        const next = await openIconPicker(iconBtn, a.icon || "");
        if (next === null) return; // cancelled
        a.icon = next;
        iconBtn.innerHTML = iconMarkup(next, { fallback: '<span class="qa-icon-empty">+</span>' });
        markDirty();
        return;
      }
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "open-folder") {
        openFolder(a);
        return;
      }
      if (act === "reset-color" || act === "reset-text_color") {
        const field = act === "reset-color" ? "color" : "text_color";
        a[field] = "";
        const input = card.querySelector(`input[data-field="${field}"]`);
        if (input) {
          input.value = field === "color" ? DEFAULT_TILE_BG : DEFAULT_TILE_FG;
          input.setAttribute("data-unset", "1");
        }
        markDirty();
        return;
      }
      if (act === "delete") {
        const label = a.label || a.id || t("qa_editor.delete_this_action");
        const ok = await confirmDialog(
          t("qa_editor.delete_confirm", { label }),
          { okLabel: t("common.delete"), danger: true },
        );
        if (!ok) return;
        const idx = actions.indexOf(a);
        if (idx >= 0) actions.splice(idx, 1);
        renderList();
        markDirty();
      } else if (act === "test") {
        await runTest(a);
      }
    });
  }

  async function runTest(a) {
    if (!a.id) {
      flashToast(t("qa_editor.test_needs_id"), true);
      return;
    }
    if (dirty) {
      flashToast(t("qa_editor.test_save_first"), true);
      return;
    }
    if (a.confirm) {
      const ok = await confirmDialog(
        t("qa_editor.test_run_confirm", { label: a.label || a.id }),
        {
          okLabel: t("common.run"),
          danger: /reboot|shutdown|poweroff|restart/i.test(`${a.id} ${a.label}`),
        },
      );
      if (!ok) return;
    }
    try {
      const r = await fetch(`/api/quick_actions/${encodeURIComponent(a.id)}/run`, { method: "POST" });
      const body = await r.json().catch(() => ({}));
      if (r.ok && body.ok) {
        flashToast(t("qa_editor.test_ran", { label: a.label || a.id }));
      } else {
        const msg = body.error
          || (body.exit_code != null ? `exit ${body.exit_code}` : "")
          || (body.status_code != null ? `HTTP ${body.status_code}` : `HTTP ${r.status}`);
        flashToast(t("qa_editor.failed", { reason: msg }), true);
      }
    } catch (err) {
      flashToast(t("qa_editor.network_error", { reason: err.message }), true);
    }
  }

  // ---- Drag-and-drop reorder via pointer events (mouse + touch) ----

  function setupDragReorder() {
    let dragCard = null;
    let dragAction = null;
    let pointerStartY = 0;
    let cardStartY = 0;
    let pointerId = null;

    listEl.addEventListener("pointerdown", (e) => {
      const handle = e.target.closest(".qa-drag");
      if (!handle) return;
      const card = handle.closest(".qa-card");
      if (!card) return;
      e.preventDefault();
      pointerId = e.pointerId;
      handle.setPointerCapture(pointerId);
      dragCard = card;
      const idx = Array.from(listEl.children).indexOf(card);
      dragAction = actions[idx];
      pointerStartY = e.clientY;
      cardStartY = card.getBoundingClientRect().top;
      card.classList.add("is-dragging");

      const onMove = (ev) => {
        if (!dragCard) return;
        const dy = ev.clientY - pointerStartY;
        dragCard.style.transform = `translateY(${dy}px)`;

        const draggedMid = cardStartY + dy + dragCard.offsetHeight / 2;
        const cards = Array.from(listEl.children);
        const curIdx = cards.indexOf(dragCard);

        // Move up?
        const prev = cards[curIdx - 1];
        if (prev) {
          const prevRect = prev.getBoundingClientRect();
          if (draggedMid < prevRect.top + prevRect.height / 2) {
            listEl.insertBefore(dragCard, prev);
            // Adjust cardStartY so the visual position stays continuous.
            cardStartY -= prevRect.height;
            return;
          }
        }
        // Move down?
        const next = cards[curIdx + 1];
        if (next) {
          const nextRect = next.getBoundingClientRect();
          if (draggedMid > nextRect.top + nextRect.height / 2) {
            listEl.insertBefore(next, dragCard);
            cardStartY += nextRect.height;
            return;
          }
        }
      };

      const onUp = () => {
        if (!dragCard) return;
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        handle.removeEventListener("pointercancel", onUp);
        dragCard.classList.remove("is-dragging");
        dragCard.style.transform = "";
        // Rebuild the current level from the new DOM order, mutating the array
        // in place so the parent folder keeps referencing the same array.
        const newOrder = Array.from(listEl.children)
          .map((el) => el.dataset.id)
          .map((id) => actions.find((x) => x.id === id) || dragAction)
          .filter(Boolean);
        actions.splice(0, actions.length, ...newOrder);
        dragCard = null;
        dragAction = null;
        pointerId = null;
        markDirty();
      };

      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
      handle.addEventListener("pointercancel", onUp);
    });
  }

  // ---- Bar buttons ----

  addBtn.addEventListener("click", () => {
    const next = emptyAction();
    next.id = `action-${Date.now().toString(36).slice(-5)}`;
    actions.push(next);
    renderList();
    markDirty();
    // Focus the new card's ID so the user can immediately rename.
    const cards = listEl.querySelectorAll(".qa-card");
    cards[cards.length - 1]?.querySelector('[data-field="id"]')?.focus();
  });

  resetBtn.addEventListener("click", () => {
    load();
  });

  // Validate the whole tree client-side for a friendlier message than a 400.
  // Returns an error string, or null when everything checks out.
  function validateTree(list, ids) {
    for (const a of list) {
      if (!a.id) return t("qa_editor.needs_id");
      if (ids.has(a.id)) return t("qa_editor.duplicate_id", { id: a.id });
      ids.add(a.id);
      if (a.kind === "shell" && a.command.filter(Boolean).length === 0) {
        return t("qa_editor.shell_empty", { id: a.id });
      }
      if (a.kind === "http" && !a.url) {
        return t("qa_editor.http_url_missing", { id: a.id });
      }
      if (a.status) {
        if (a.status.kind === "shell" && a.status.command.filter(Boolean).length === 0) {
          return t("qa_editor.status_shell_empty", { id: a.id });
        }
        if (a.status.kind === "http" && !a.status.url) {
          return t("qa_editor.status_url_missing", { id: a.id });
        }
      }
      if (a.kind === "folder") {
        const nested = validateTree(a.tiles || [], ids);
        if (nested) return nested;
      }
    }
    return null;
  }

  saveBtn.addEventListener("click", async () => {
    const err = validateTree(rootActions, new Set());
    if (err) {
      flashToast(err, true);
      return;
    }
    const payload = {
      actions: rootActions.map(serializeAction),
      timeout_seconds: timeoutSeconds,
      columns,
      rows,
    };
    saveBtn.disabled = true;
    try {
      const r = await fetch("/api/quick_actions/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(`HTTP ${r.status}: ${text}`);
      }
      flashToast(t("qa_editor.saved"));
      await load(); // re-load so server-side canonicalization is reflected
    } catch (err) {
      console.error("[qa-editor] save failed:", err);
      flashToast(t("common.save_failed_with_reason", { reason: err.message }), true);
    } finally {
      saveBtn.disabled = false;
    }
  });

  load();

  // Let the host re-sync the editor with the on-disk config when the sheet is
  // reopened — but never discard the user's unsaved edits.
  return {
    reload() {
      if (!dirty) load();
    },
  };
}
