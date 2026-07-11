// Tile editor — a focused modal to configure ONE deck tile, opened from the
// widget's edit mode (long-press a button → edit). Replaces the cumbersome
// scrolling card list in settings for everyday button creation/editing.
//
// openTileEditor(tile, opts) edits a working copy and, on "Übernehmen", writes
// the result back into `tile` in place (kind-consistent so the backend accepts
// it). Resolves "applied" | "deleted" | null(cancel). It never hits the network
// itself — the deck's edit-mode "Speichern" persists the whole tree.

import { t } from "../i18n.js";
import { iconMarkup } from "../lib/icon.js";
import { openIconPicker } from "../lib/icon_picker.js";

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];
const DEFAULT_BG = "#1b2733";
const DEFAULT_FG = "#e6edf3";

function escapeAttr(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}
function clampSpan(v) {
  return Math.min(Math.max(1, Math.round(Number(v) || 1)), 4);
}
function parseJsonOrNull(s) {
  const text = (s || "").trim();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (_) {
    return undefined; // "invalid"
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
function emptyStatus() {
  return { kind: "shell", command: [], url: "", method: "GET", headers: {}, match: "" };
}
function normalizeStatus(raw) {
  const s = { ...emptyStatus(), ...(raw || {}) };
  s.command = Array.isArray(s.command) ? [...s.command] : [];
  s.headers = s.headers && typeof s.headers === "object" ? { ...s.headers } : {};
  s.match = s.match || "";
  return s;
}

export function openTileEditor(tile, { onOpenFolder } = {}) {
  return new Promise((resolve) => {
    const isNew = !tile.__committed;
    // Working copy of the editable fields.
    const w = {
      label: tile.label || "",
      icon: tile.icon || "",
      kind: tile.kind || "shell",
      confirm: !!tile.confirm,
      color: tile.color || "",
      text_color: tile.text_color || "",
      w: clampSpan(tile.w),
      h: clampSpan(tile.h),
      command: Array.isArray(tile.command) ? [...tile.command] : [],
      detach: !!tile.detach,
      url: tile.url || "",
      method: (tile.method || "POST").toUpperCase(),
      headers: tile.headers && typeof tile.headers === "object" ? { ...tile.headers } : {},
      params: tile.params && typeof tile.params === "object" ? { ...tile.params } : {},
      json: tile.json ?? tile.json_body ?? null,
      status: tile.status ? normalizeStatus(tile.status) : null,
    };

    const overlay = document.createElement("div");
    overlay.className = "tile-editor-overlay";
    overlay.innerHTML = `
      <div class="tile-editor" role="dialog" aria-modal="true">
        <div class="tile-editor-head">
          <button type="button" class="qa-icon-btn" data-bind="iconbtn" aria-label="${t("qa_editor.icon_pick")}"></button>
          <input type="text" class="te-label" data-bind="label" placeholder="${t("qa_editor.label_placeholder")}">
          <select class="qa-kind-select" data-bind="kind">
            <option value="shell">${t("qa_editor.kind.shell")}</option>
            <option value="http">${t("qa_editor.kind.http")}</option>
            <option value="folder">${t("qa_editor.kind.folder")}</option>
          </select>
        </div>
        <div class="tile-editor-body" data-bind="body"></div>
        <div class="te-appearance">
          <label class="qa-appear-field">
            <span>${t("qa_editor.tile_bg")}</span>
            <span class="qa-color-wrap">
              <input type="color" data-bind="color">
              <button type="button" class="qa-color-reset" data-act="reset-color" title="${t("qa_editor.tile_color_default")}">↺</button>
            </span>
          </label>
          <label class="qa-appear-field">
            <span>${t("qa_editor.tile_fg")}</span>
            <span class="qa-color-wrap">
              <input type="color" data-bind="text_color">
              <button type="button" class="qa-color-reset" data-act="reset-text_color" title="${t("qa_editor.tile_color_default")}">↺</button>
            </span>
          </label>
          <label class="qa-appear-field">
            <span>${t("qa_editor.tile_size")}</span>
            <select data-bind="size">
              <option value="1x1">1×1</option>
              <option value="2x1">2×1</option>
              <option value="1x2">1×2</option>
              <option value="2x2">2×2</option>
            </select>
          </label>
        </div>
        <div class="tile-editor-foot">
          <button type="button" class="te-btn te-danger" data-act="delete">${t("common.delete")}</button>
          <span class="te-err" data-bind="err"></span>
          <span class="te-spacer"></span>
          <button type="button" class="te-btn" data-act="cancel">${t("common.cancel")}</button>
          <button type="button" class="te-btn is-primary" data-act="apply">${t("tile_editor.apply")}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const $ = (s) => overlay.querySelector(s);
    const iconBtn = $('[data-bind="iconbtn"]');
    const labelInput = $('[data-bind="label"]');
    const kindSel = $('[data-bind="kind"]');
    const bodyEl = $('[data-bind="body"]');
    const colorIn = $('[data-bind="color"]');
    const fgIn = $('[data-bind="text_color"]');
    const sizeSel = $('[data-bind="size"]');
    const errEl = $('[data-bind="err"]');

    let resolved = false;
    const close = (result) => {
      if (resolved) return;
      resolved = true;
      overlay.remove();
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onKey = (e) => {
      if (e.key === "Escape") close(null);
    };
    document.addEventListener("keydown", onKey);
    overlay.addEventListener("pointerdown", (e) => {
      if (e.target === overlay) close(null);
    });

    const paintIcon = () => {
      iconBtn.innerHTML = iconMarkup(w.icon, { fallback: '<span class="qa-icon-empty">+</span>' });
    };
    const paintColors = () => {
      colorIn.value = w.color || DEFAULT_BG;
      colorIn.toggleAttribute("data-unset", !w.color);
      fgIn.value = w.text_color || DEFAULT_FG;
      fgIn.toggleAttribute("data-unset", !w.text_color);
    };

    function renderBody() {
      if (w.kind === "folder") {
        bodyEl.innerHTML = `
          <div class="qa-folder-hint">${t("qa_editor.folder_hint")}</div>
          ${onOpenFolder ? `<button type="button" class="te-btn" data-act="open-folder">${t("qa_editor.open_folder")}</button>` : ""}
        `;
        const ob = bodyEl.querySelector('[data-act="open-folder"]');
        if (ob) ob.addEventListener("click", () => { applyToTile(); close("open-folder"); });
        return;
      }
      if (w.kind === "shell") {
        bodyEl.innerHTML = `
          <label class="settings-field">
            <span>${t("qa_editor.command_label")} <span class="hint">${t("qa_editor.command_hint")}</span></span>
            <textarea data-bind="command" rows="3" class="qa-mono" placeholder="loginctl&#10;lock-session">${escapeAttr(w.command.join("\n"))}</textarea>
          </label>
          <label class="qa-checkbox"><input type="checkbox" data-bind="detach"${w.detach ? " checked" : ""}><span>${t("tile_editor.detach")}</span></label>`;
        bodyEl.querySelector('[data-bind="command"]').addEventListener("input", (e) => {
          w.command = e.target.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
        });
        bodyEl.querySelector('[data-bind="detach"]').addEventListener("change", (e) => { w.detach = e.target.checked; });
      } else {
        const methodOpts = METHODS.map((m) => `<option value="${m}"${w.method === m ? " selected" : ""}>${m}</option>`).join("");
        bodyEl.innerHTML = `
          <div class="settings-row" style="grid-template-columns: 1fr auto">
            <label class="settings-field"><span>URL</span>
              <input type="text" data-bind="url" value="${escapeAttr(w.url)}" placeholder="https://homeassistant.local:8123/api/..."></label>
            <label class="settings-field"><span>${t("qa_editor.method")}</span>
              <select data-bind="method">${methodOpts}</select></label>
          </div>
          <label class="settings-field"><span>${t("qa_editor.headers")} <span class="hint">${t("qa_editor.headers_hint")}</span></span>
            <textarea data-bind="headers" rows="2" class="qa-mono" placeholder='{"Authorization":"Bearer …"}'>${escapeAttr(jsonToText(w.headers))}</textarea></label>
          <label class="settings-field"><span>${t("qa_editor.body")} <span class="hint">${t("qa_editor.body_hint")}</span></span>
            <textarea data-bind="json" rows="2" class="qa-mono" placeholder='{"key":"value"}'>${escapeAttr(jsonToText(w.json))}</textarea></label>`;
        bodyEl.querySelector('[data-bind="url"]').addEventListener("input", (e) => { w.url = e.target.value; });
        bodyEl.querySelector('[data-bind="method"]').addEventListener("change", (e) => { w.method = e.target.value; });
        bodyEl.querySelector('[data-bind="headers"]').addEventListener("input", (e) => {
          const p = parseJsonOrNull(e.target.value);
          e.target.classList.toggle("is-invalid", p === undefined);
          if (p !== undefined) w.headers = p || {};
        });
        bodyEl.querySelector('[data-bind="json"]').addEventListener("input", (e) => {
          if (e.target.value.trim() === "") { w.json = null; e.target.classList.remove("is-invalid"); return; }
          const p = parseJsonOrNull(e.target.value);
          e.target.classList.toggle("is-invalid", p === undefined);
          if (p !== undefined) w.json = p;
        });
      }
      // confirm + live-status (runnable tiles only)
      const extra = document.createElement("div");
      extra.className = "te-extra";
      extra.innerHTML = `
        <label class="qa-checkbox"><input type="checkbox" data-bind="confirm"${w.confirm ? " checked" : ""}><span>${t("qa_editor.confirm_before_run")}</span></label>
        <div class="qa-status-section" data-bind="status"></div>`;
      bodyEl.appendChild(extra);
      extra.querySelector('[data-bind="confirm"]').addEventListener("change", (e) => { w.confirm = e.target.checked; });
      renderStatus(extra.querySelector('[data-bind="status"]'));
    }

    function renderStatus(wrap) {
      const on = !!w.status;
      let fields = "";
      if (on) {
        const s = w.status;
        const kindOpts = `<option value="shell"${s.kind === "shell" ? " selected" : ""}>${t("qa_editor.kind.shell")}</option><option value="http"${s.kind === "http" ? " selected" : ""}>${t("qa_editor.kind.http")}</option>`;
        let probe;
        if (s.kind === "shell") {
          probe = `<label class="settings-field"><span>${t("qa_editor.status_command")} <span class="hint">${t("qa_editor.status_command_hint")}</span></span>
            <textarea data-bind="s_command" rows="2" class="qa-mono">${escapeAttr((s.command || []).join("\n"))}</textarea></label>`;
        } else {
          const methodOpts = METHODS.map((m) => `<option value="${m}"${(s.method || "GET").toUpperCase() === m ? " selected" : ""}>${m}</option>`).join("");
          probe = `<div class="settings-row" style="grid-template-columns:1fr auto">
            <label class="settings-field"><span>URL</span><input type="text" data-bind="s_url" value="${escapeAttr(s.url || "")}"></label>
            <label class="settings-field"><span>${t("qa_editor.method")}</span><select data-bind="s_method">${methodOpts}</select></label></div>
            <label class="settings-field"><span>${t("qa_editor.headers")}</span><textarea data-bind="s_headers" rows="2" class="qa-mono">${escapeAttr(jsonToText(s.headers))}</textarea></label>`;
        }
        fields = `
          <label class="settings-field"><span>${t("qa_editor.status_source")}</span><select data-bind="s_kind">${kindOpts}</select></label>
          ${probe}
          <label class="settings-field"><span>${t("qa_editor.status_match")} <span class="hint">${t("qa_editor.status_match_hint")}</span></span>
            <input type="text" data-bind="s_match" value="${escapeAttr(s.match || "")}" placeholder="on|true|1"></label>`;
      }
      wrap.innerHTML = `
        <label class="qa-checkbox"><input type="checkbox" data-bind="s_on"${on ? " checked" : ""}><span>${t("qa_editor.status_enable")}</span></label>
        <div class="qa-status-fields">${fields}</div>`;
      wrap.querySelector('[data-bind="s_on"]').addEventListener("change", (e) => {
        w.status = e.target.checked ? (w.status || emptyStatus()) : null;
        renderStatus(wrap);
      });
      const bind = (sel, fn) => { const el = wrap.querySelector(sel); if (el) el.addEventListener(el.tagName === "SELECT" ? "change" : "input", fn); };
      bind('[data-bind="s_kind"]', (e) => { w.status.kind = e.target.value; renderStatus(wrap); });
      bind('[data-bind="s_command"]', (e) => { w.status.command = e.target.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean); });
      bind('[data-bind="s_url"]', (e) => { w.status.url = e.target.value; });
      bind('[data-bind="s_method"]', (e) => { w.status.method = e.target.value; });
      bind('[data-bind="s_headers"]', (e) => { const p = parseJsonOrNull(e.target.value); e.target.classList.toggle("is-invalid", p === undefined); if (p !== undefined) w.status.headers = p || {}; });
      bind('[data-bind="s_match"]', (e) => { w.status.match = e.target.value; });
    }

    function applyToTile() {
      tile.label = w.label.trim();
      tile.icon = w.icon;
      tile.kind = w.kind;
      tile.w = w.w;
      tile.h = w.h;
      if (w.color) tile.color = w.color; else delete tile.color;
      if (w.text_color) tile.text_color = w.text_color; else delete tile.text_color;
      // reset kind-specific keys so the dict stays valid for its kind
      delete tile.command; delete tile.url; delete tile.method;
      delete tile.headers; delete tile.params; delete tile.json; delete tile.json_body;
      delete tile.detach;
      if (w.kind === "shell") {
        tile.command = w.command.filter(Boolean);
        if (w.detach) tile.detach = true;
        delete tile.tiles;
      } else if (w.kind === "http") {
        tile.url = w.url;
        if (w.method && w.method !== "POST") tile.method = w.method;
        if (Object.keys(w.headers).length) tile.headers = w.headers;
        if (w.json !== null && w.json !== undefined && w.json !== "") tile.json = w.json;
        delete tile.tiles;
      } else if (w.kind === "folder") {
        if (!Array.isArray(tile.tiles)) tile.tiles = [];
      }
      if (w.kind !== "folder" && w.confirm) tile.confirm = true; else delete tile.confirm;
      if (w.kind !== "folder" && w.status) {
        const s = { kind: w.status.kind };
        if (s.kind === "shell") s.command = (w.status.command || []).filter(Boolean);
        else { s.url = w.status.url || ""; if ((w.status.method || "GET").toUpperCase() !== "GET") s.method = w.status.method; if (Object.keys(w.status.headers).length) s.headers = w.status.headers; }
        if (w.status.match) s.match = w.status.match;
        tile.status = s;
      } else {
        delete tile.status;
      }
      tile.__committed = true;
    }

    function validate() {
      if (w.kind === "shell" && w.command.filter(Boolean).length === 0) return t("qa_editor.shell_empty", { id: w.label || "?" });
      if (w.kind === "http" && !w.url.trim()) return t("qa_editor.http_url_missing", { id: w.label || "?" });
      if (w.status) {
        if (w.status.kind === "shell" && w.status.command.filter(Boolean).length === 0) return t("qa_editor.status_shell_empty", { id: w.label || "?" });
        if (w.status.kind === "http" && !w.status.url) return t("qa_editor.status_url_missing", { id: w.label || "?" });
      }
      return null;
    }

    // ---- wiring ----
    kindSel.value = w.kind;
    sizeSel.value = `${w.w}x${w.h}`;
    paintIcon();
    paintColors();
    renderBody();

    iconBtn.addEventListener("click", async () => {
      const next = await openIconPicker(iconBtn, w.icon);
      if (next === null) return;
      w.icon = next;
      paintIcon();
    });
    labelInput.value = w.label;
    labelInput.addEventListener("input", () => { w.label = labelInput.value; });
    kindSel.addEventListener("change", () => { w.kind = kindSel.value; renderBody(); });
    sizeSel.addEventListener("change", () => { const [a, b] = sizeSel.value.split("x").map(clampSpan); w.w = a; w.h = b; });
    colorIn.addEventListener("input", () => { w.color = colorIn.value; colorIn.removeAttribute("data-unset"); });
    fgIn.addEventListener("input", () => { w.text_color = fgIn.value; fgIn.removeAttribute("data-unset"); });
    overlay.querySelector('[data-act="reset-color"]').addEventListener("click", () => { w.color = ""; paintColors(); });
    overlay.querySelector('[data-act="reset-text_color"]').addEventListener("click", () => { w.text_color = ""; paintColors(); });
    overlay.querySelector('[data-act="delete"]').addEventListener("click", () => close("deleted"));
    overlay.querySelector('[data-act="cancel"]').addEventListener("click", () => close(null));
    overlay.querySelector('[data-act="apply"]').addEventListener("click", () => {
      const err = validate();
      if (err) { errEl.textContent = err; return; }
      applyToTile();
      close("applied");
    });

    requestAnimationFrame(() => labelInput.focus());
  });
}
