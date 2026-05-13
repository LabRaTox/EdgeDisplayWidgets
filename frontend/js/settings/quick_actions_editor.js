// Quick Actions editor — GUI for the "Aktionen" tab in the Settings sheet.
//
// Buffers edits in a JS model, posts the full list to
// /api/quick_actions/config on Save. Drag-and-drop reorder uses pointer
// events so it works on mouse + touch.

import { confirmDialog } from "../confirm.js";
import { t } from "../i18n.js";

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
    command: [],
    url: "",
    method: "POST",
    headers: {},
    params: {},
    json: null,
  };
}

function normalizeAction(raw) {
  // Merge a server-supplied action with the editor's expected shape so
  // every field exists (including the kind-specific defaults that the
  // server omits via exclude_defaults).
  const a = { ...emptyAction(), ...(raw || {}) };
  a.command = Array.isArray(a.command) ? [...a.command] : [];
  a.headers = a.headers && typeof a.headers === "object" ? { ...a.headers } : {};
  a.params = a.params && typeof a.params === "object" ? { ...a.params } : {};
  return a;
}

// Convert the editor's action shape back to the server-side schema.
// Strips empty/default values so config.local.yaml stays readable.
function serializeAction(a) {
  const out = { id: a.id, kind: a.kind };
  if (a.label) out.label = a.label;
  if (a.icon) out.icon = a.icon;
  if (a.confirm) out.confirm = true;
  if (a.kind === "shell") {
    out.command = a.command.filter((arg) => arg.length > 0);
  } else if (a.kind === "http") {
    out.url = a.url || "";
    if (a.method && a.method.toUpperCase() !== "POST") out.method = a.method.toUpperCase();
    if (a.headers && Object.keys(a.headers).length) out.headers = a.headers;
    if (a.params && Object.keys(a.params).length) out.params = a.params;
    if (a.json !== null && a.json !== undefined && a.json !== "") out.json = a.json;
  }
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

// --- Icon picker --------------------------------------------------------
//
// emoji-picker-element is a Web Component with built-in search + categories.
// Self-hosted under /vendor/ so the dashboard has no external supply-chain
// dependency — picker code AND emoji data are served from our own origin.

const EMOJI_PICKER_URL = "/vendor/emoji-picker-element/picker.js";
const EMOJI_DATA_URL = "/vendor/emoji-picker-element/data.json";

let _emojiLoadPromise = null;
function loadEmojiPickerElement() {
  if (window.customElements?.get("emoji-picker")) return Promise.resolve(true);
  if (!_emojiLoadPromise) {
    _emojiLoadPromise = import(EMOJI_PICKER_URL)
      .then(() => true)
      .catch((err) => {
        console.warn("[qa-editor] emoji-picker failed to load:", err);
        _emojiLoadPromise = null; // allow retry on next open
        return false;
      });
  }
  return _emojiLoadPromise;
}

// Returns a Promise<string|null>:
//   string  -> the chosen emoji (or "" to clear the icon)
//   null    -> picker was cancelled, leave the icon untouched
async function openIconPicker(target) {
  const ok = await loadEmojiPickerElement();
  if (!ok) {
    const cur = target.textContent.trim().replace(/^\+$/, "");
    const v = window.prompt(t("qa_editor.icon_prompt"), cur);
    return v == null ? null : v;
  }
  return new Promise((resolve) => {
    const popover = document.createElement("div");
    popover.className = "qa-emoji-popover";
    popover.innerHTML = `
      <div class="qa-emoji-toolbar">
        <button type="button" class="btn" data-act="clear">${t("qa_editor.icon_none")}</button>
        <button type="button" class="btn" data-act="cancel">${t("common.cancel")}</button>
      </div>
      <emoji-picker class="dark" data-source="${EMOJI_DATA_URL}"></emoji-picker>
    `;
    document.body.appendChild(popover);

    const place = () => {
      const r = target.getBoundingClientRect();
      const pr = popover.getBoundingClientRect();
      let top = r.bottom + 6;
      let left = r.left;
      if (top + pr.height > window.innerHeight - 8) {
        top = Math.max(8, r.top - pr.height - 6);
      }
      if (left + pr.width > window.innerWidth - 8) {
        left = Math.max(8, window.innerWidth - pr.width - 8);
      }
      popover.style.top = `${top}px`;
      popover.style.left = `${left}px`;
    };
    requestAnimationFrame(place);
    window.addEventListener("resize", place);

    let resolved = false;
    const close = (value) => {
      if (resolved) return;
      resolved = true;
      popover.remove();
      document.removeEventListener("pointerdown", onDocPointer, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", place);
      resolve(value);
    };
    const onDocPointer = (e) => {
      if (popover.contains(e.target) || target.contains(e.target)) return;
      close(null);
    };
    const onKey = (e) => {
      if (e.key === "Escape") close(null);
    };
    // Defer so the click that opened us doesn't immediately close us.
    setTimeout(() => {
      document.addEventListener("pointerdown", onDocPointer, true);
      document.addEventListener("keydown", onKey);
    }, 0);

    popover.querySelector("emoji-picker").addEventListener("emoji-click", (e) => {
      close(e.detail.unicode || "");
    });
    popover.querySelector('[data-act="clear"]').addEventListener("click", () => close(""));
    popover.querySelector('[data-act="cancel"]').addEventListener("click", () => close(null));
  });
}

/**
 * Mount the Quick Actions editor into `rootEl`.
 *
 * @param {HTMLElement} rootEl
 * @param {{flashToast: (msg: string, isError?: boolean) => void}} opts
 */
export function mountQuickActionsEditor(rootEl, { flashToast }) {
  // Editor state — a buffer of actions. Saved only when the user clicks
  // "Speichern" so changes can be discarded by closing the sheet.
  let actions = [];
  let timeoutSeconds = 30.0;
  let dirty = false;

  rootEl.innerHTML = `
    <div class="qa-editor">
      <div class="qa-editor-bar">
        <button class="btn" type="button" data-act="add">${t("qa_editor.add")}</button>
        <span class="qa-editor-meta" data-bind="meta"></span>
        <span class="qa-editor-spacer"></span>
        <button class="btn" type="button" data-act="reset" hidden>${t("common.discard")}</button>
        <button class="btn btn-primary" type="button" data-act="save">${t("common.save")}</button>
      </div>
      <div class="qa-editor-list" data-bind="list">
        <div class="settings-empty">${t("common.loading")}</div>
      </div>
    </div>
  `;

  const listEl = rootEl.querySelector('[data-bind="list"]');
  const metaEl = rootEl.querySelector('[data-bind="meta"]');
  const resetBtn = rootEl.querySelector('[data-act="reset"]');
  const addBtn = rootEl.querySelector('[data-act="add"]');
  const saveBtn = rootEl.querySelector('[data-act="save"]');

  function markDirty() {
    dirty = true;
    resetBtn.hidden = false;
    metaEl.textContent = t("common.unsaved");
  }
  function markClean() {
    dirty = false;
    resetBtn.hidden = true;
    metaEl.textContent = actions.length === 1
      ? t("qa_editor.action_count_one", { count: actions.length })
      : t("qa_editor.action_count_other", { count: actions.length });
  }

  async function load() {
    listEl.innerHTML = `<div class="settings-empty">${t("common.loading")}</div>`;
    try {
      const r = await fetch("/api/quick_actions/config");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      actions = (body.actions || []).map(normalizeAction);
      timeoutSeconds = body.timeout_seconds ?? 30.0;
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
                aria-label="${t("qa_editor.icon_pick")}">${a.icon ? escapeAttr(a.icon) : '<span class="qa-icon-empty">+</span>'}</button>
        <input type="text" class="qa-label-input" data-field="label"
               value="${escapeAttr(a.label)}" placeholder="${t("qa_editor.label_placeholder")}">
        <input type="text" class="qa-id-input" data-field="id"
               value="${escapeAttr(a.id)}" placeholder="action-id" maxlength="64">
        <select class="qa-kind-select" data-field="kind">
          <option value="shell"${a.kind === "shell" ? " selected" : ""}>${t("qa_editor.kind.shell")}</option>
          <option value="http"${a.kind === "http" ? " selected" : ""}>${t("qa_editor.kind.http")}</option>
        </select>
        <button type="button" class="qa-delete" aria-label="${t("common.delete")}" data-act="delete">×</button>
      </div>
      <div class="qa-card-row">
        <label class="qa-checkbox">
          <input type="checkbox" data-field="confirm"${a.confirm ? " checked" : ""}>
          <span>${t("qa_editor.confirm_before_run")}</span>
        </label>
        <span class="qa-card-spacer"></span>
        <button type="button" class="btn qa-test-btn" data-act="test">${t("qa_editor.test_button")}</button>
      </div>
      <div class="qa-card-body" data-bind="body"></div>
    `;

    renderKindFields(card, a);
    wireCard(card, a);
    return card;
  }

  function renderKindFields(card, a) {
    const body = card.querySelector('[data-bind="body"]');
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
      if (t.dataset?.field === "kind") {
        a.kind = t.value;
        renderKindFields(card, a);
        markDirty();
      }
    });

    card.addEventListener("click", async (e) => {
      const iconBtn = e.target.closest('.qa-icon-btn');
      if (iconBtn) {
        e.preventDefault();
        const next = await openIconPicker(iconBtn);
        if (next === null) return; // cancelled
        a.icon = next;
        iconBtn.innerHTML = next ? escapeAttr(next) : '<span class="qa-icon-empty">+</span>';
        markDirty();
        return;
      }
      const act = e.target.closest("[data-act]")?.dataset.act;
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
        // Rebuild the actions array from the new DOM order.
        const newOrder = Array.from(listEl.children)
          .map((el) => el.dataset.id)
          .map((id) => actions.find((x) => x.id === id) || dragAction);
        // Filter out any stale references in case of empty ids.
        actions = newOrder.filter(Boolean);
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

  saveBtn.addEventListener("click", async () => {
    // Pre-check IDs client-side for a friendlier error than 400 from server.
    const ids = new Set();
    for (const a of actions) {
      if (!a.id) {
        flashToast(t("qa_editor.needs_id"), true);
        return;
      }
      if (ids.has(a.id)) {
        flashToast(t("qa_editor.duplicate_id", { id: a.id }), true);
        return;
      }
      ids.add(a.id);
      if (a.kind === "shell" && a.command.filter(Boolean).length === 0) {
        flashToast(t("qa_editor.shell_empty", { id: a.id }), true);
        return;
      }
      if (a.kind === "http" && !a.url) {
        flashToast(t("qa_editor.http_url_missing", { id: a.id }), true);
        return;
      }
    }
    const payload = {
      actions: actions.map(serializeAction),
      timeout_seconds: timeoutSeconds,
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
}
