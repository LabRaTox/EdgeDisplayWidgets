// Layout editor — visual grid editing for the dashboard.
//
// Edit mode adds drag (move) + bottom-right resize handles to every widget,
// plus a top-anchored toolbar with Save / Cancel / Add-Widget / Add-Page,
// and a per-page bar with title + grid controls + delete-page. Snapping is
// to grid cells defined by the page's `grid-template-columns/rows`.
//
// Surgical DOM updates: delete and add work on individual widget elements
// without a full re-render, so other widgets keep their internal state
// (sparkline buffers, intervals, etc.) and any unsaved drag/resize edits.
// Page-level mutations (add/remove) fall back to setPages() which
// renderPages()es from scratch — rare actions, simpler than diffing.
// Cancel restores the snapshot taken on enter().

import { confirmDialog } from "./confirm.js";
// Alias avoids clashes with the local `t` (toolbar/toast element) used in
// several methods below.
import { t as tr } from "./i18n.js";

// Count top-level tokens in a grid-template-columns/rows value, respecting
// parentheses. "1fr 1fr 1fr" → 3, "minmax(0, 1fr) minmax(0, 1fr)" → 2.
function countGridTokens(s) {
  let depth = 0;
  let count = 0;
  let inToken = false;
  for (const ch of String(s || "")) {
    if (ch === "(") {
      depth++;
      inToken = true;
    } else if (ch === ")") {
      depth = Math.max(0, depth - 1);
      inToken = true;
    } else if (/\s/.test(ch) && depth === 0) {
      if (inToken) count++;
      inToken = false;
    } else {
      inToken = true;
    }
  }
  if (inToken) count++;
  return count;
}

function uniformGrid(n) {
  return Array.from({ length: Math.max(1, n) }, () => "1fr").join(" ");
}

function escapeAttr(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

function trackSizes(pageEl) {
  const cs = getComputedStyle(pageEl);
  const cols = cs.gridTemplateColumns
    .split(/\s+/)
    .filter(Boolean)
    .map(parseFloat);
  const rows = cs.gridTemplateRows
    .split(/\s+/)
    .filter(Boolean)
    .map(parseFloat);
  return { cols, rows, cs };
}

// `bias` controls how columns/rows are picked at boundaries:
//   "nearest": gap midpoint = boundary  (smooth — better for drag)
//   "inside" : pointer must enter the next column to count (better for resize)
function cellFromPoint(pageEl, clientX, clientY, bias = "nearest") {
  const rect = pageEl.getBoundingClientRect();
  const { cols, rows, cs } = trackSizes(pageEl);
  const padL = parseFloat(cs.paddingLeft) || 0;
  const padT = parseFloat(cs.paddingTop) || 0;
  const colGap = parseFloat(cs.columnGap || cs.gap) || 0;
  const rowGap = parseFloat(cs.rowGap || cs.gap) || 0;

  const x = clientX - rect.left - padL;
  const y = clientY - rect.top - padT;

  const offset = bias === "inside" ? 0 : colGap / 2;
  const offsetY = bias === "inside" ? 0 : rowGap / 2;

  let col = cols.length;
  let acc = 0;
  for (let i = 0; i < cols.length; i++) {
    const limit = bias === "inside"
      ? acc + cols[i] + colGap
      : acc + cols[i] + offset;
    if (x < limit) {
      col = i + 1;
      break;
    }
    acc += cols[i] + colGap;
  }
  let row = rows.length;
  acc = 0;
  for (let i = 0; i < rows.length; i++) {
    const limit = bias === "inside"
      ? acc + rows[i] + rowGap
      : acc + rows[i] + offsetY;
    if (y < limit) {
      row = i + 1;
      break;
    }
    acc += rows[i] + rowGap;
  }
  return {
    col: Math.max(1, Math.min(cols.length, col)),
    row: Math.max(1, Math.min(rows.length, row)),
    cols: cols.length,
    rows: rows.length,
  };
}

export class LayoutEditor {
  constructor({
    pagesRoot,
    swiper,
    getPages,
    setPages,
    mountWidget,
    unmountWidget,
    onSave,
    onCancel,
  }) {
    this.pagesRoot = pagesRoot;
    this.swiper = swiper;
    this.getPages = getPages;
    this.setPages = setPages;
    this.mountWidget = mountWidget;
    this.unmountWidget = unmountWidget;
    this.onSave = onSave;
    this.onCancel = onCancel;
    this._active = false;
    this._snapshot = null;
    this._toolbar = null;
    this._toast = null;
    this._availableWidgets = [];
  }

  get active() {
    return this._active;
  }

  async enter() {
    if (this._active) return;
    this._active = true;
    this._snapshot = JSON.parse(JSON.stringify(this.getPages()));
    document.body.dataset.edit = "true";

    try {
      const r = await fetch("/api/widgets");
      if (r.ok) this._availableWidgets = (await r.json()).widgets || [];
    } catch (_) {
      this._availableWidgets = [];
    }

    this._buildToolbar();
    this._attachWidgetHandles();
    this._attachPageHandles();
  }

  exit({ revert = false } = {}) {
    if (!this._active) return;
    this._active = false;
    document.body.removeAttribute("data-edit");
    if (this._toolbar) {
      this._toolbar.remove();
      this._toolbar = null;
    }
    // Detach the toast from the editor without removing it — its own
    // setTimeout will retire it shortly after exit, so the user gets the
    // success/error feedback even after the toolbar is gone.
    this._toast = null;
    // Strip per-widget edit decorations
    for (const wEl of this.pagesRoot.querySelectorAll(".widget")) {
      delete wEl.dataset.editAttached;
      for (const el of wEl.querySelectorAll(".edit-handle, .edit-info")) {
        el.remove();
      }
    }
    // Strip per-page edit decorations
    for (const pEl of this.pagesRoot.querySelectorAll(".page")) {
      delete pEl.dataset.editAttached;
      for (const bar of pEl.querySelectorAll(".edit-page-bar")) bar.remove();
    }
    if (revert && this._snapshot) {
      this.setPages(this._snapshot);
    }
    this._snapshot = null;
  }

  refreshHandles() {
    if (!this._active) return;
    this._attachWidgetHandles();
    this._attachPageHandles();
  }

  _buildToolbar() {
    const t = document.createElement("div");
    t.id = "edit-toolbar";
    t.innerHTML = `
      <span class="edit-title">${tr("editor.title")}</span>
      <button class="btn" type="button" data-act="add">${tr("editor.add_widget")}</button>
      <button class="btn" type="button" data-act="add-page">${tr("editor.add_page")}</button>
      <span class="edit-spacer"></span>
      <button class="btn" type="button" data-act="cancel">${tr("editor.cancel")}</button>
      <button class="btn btn-primary" type="button" data-act="save">${tr("editor.save")}</button>
    `;
    document.body.appendChild(t);
    this._toolbar = t;
    t.querySelector('[data-act="add"]').addEventListener("click", () => this._showAddPicker());
    t.querySelector('[data-act="add-page"]').addEventListener("click", () => this._addPage());
    t.querySelector('[data-act="cancel"]').addEventListener("click", () => {
      this.exit({ revert: true });
      this.onCancel?.();
    });
    t.querySelector('[data-act="save"]').addEventListener("click", () => this._save());
  }

  _showToast(message, kind = "ok") {
    this._toast?.remove();
    const t = document.createElement("div");
    t.id = "edit-toast";
    t.className = kind === "error" ? "is-error" : "";
    t.textContent = message;
    document.body.appendChild(t);
    this._toast = t;
    setTimeout(() => {
      t.remove();
      if (this._toast === t) this._toast = null;
    }, 2500);
  }

  async _save() {
    const titleEl = this._toolbar?.querySelector(".edit-title");
    if (titleEl) titleEl.textContent = tr("editor.saving");
    try {
      await this.onSave?.(JSON.parse(JSON.stringify(this.getPages())));
      this._showToast(tr("editor.saved"));
      this.exit({ revert: false });
    } catch (err) {
      console.error("[editor] save failed:", err);
      this._showToast(tr("editor.save_failed_console"), "error");
      if (titleEl) titleEl.textContent = tr("editor.title");
    }
  }

  _attachWidgetHandles() {
    for (const wEl of this.pagesRoot.querySelectorAll(".widget")) {
      if (wEl.dataset.editAttached === "1") {
        // Already attached — just refresh the position label
        this._refreshInfoLabel(wEl);
        continue;
      }
      wEl.dataset.editAttached = "1";

      const resize = document.createElement("div");
      resize.className = "edit-handle edit-resize";
      resize.dataset.role = "resize";
      wEl.appendChild(resize);

      const del = document.createElement("button");
      del.className = "edit-handle edit-delete";
      del.type = "button";
      del.dataset.role = "delete";
      del.setAttribute("aria-label", tr("editor.widget_remove"));
      del.textContent = "×";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        this._deleteWidget(wEl);
      });
      wEl.appendChild(del);

      const info = document.createElement("span");
      info.className = "edit-info";
      info.dataset.role = "info";
      wEl.appendChild(info);
      this._refreshInfoLabel(wEl);

      wEl.addEventListener("pointerdown", (e) => this._onPointerDown(e, wEl));
    }
  }

  _attachPageHandles() {
    for (const pageEl of this.pagesRoot.querySelectorAll(".page")) {
      if (pageEl.dataset.editAttached === "1") continue;
      pageEl.dataset.editAttached = "1";
      const pageCfg = this._findPageByEl(pageEl);
      if (!pageCfg) continue;

      const bar = document.createElement("div");
      bar.className = "edit-page-bar";
      bar.innerHTML = `
        <input type="text" class="edit-page-title" data-field="title"
               value="${escapeAttr(pageCfg.title || "")}" placeholder="${tr("editor.page_title_placeholder")}">
        <div class="edit-grid-group" data-field="columns">
          <span class="edit-grid-lbl">${tr("editor.page_columns")}</span>
          <button class="edit-grid-btn" type="button" data-act="col-dec">−</button>
          <input type="number" min="1" max="20" class="edit-grid-count" value="${countGridTokens(pageCfg.grid.columns)}">
          <button class="edit-grid-btn" type="button" data-act="col-inc">+</button>
          <input type="text" class="edit-grid-raw" hidden value="${escapeAttr(pageCfg.grid.columns)}">
        </div>
        <div class="edit-grid-group" data-field="rows">
          <span class="edit-grid-lbl">${tr("editor.page_rows")}</span>
          <button class="edit-grid-btn" type="button" data-act="row-dec">−</button>
          <input type="number" min="1" max="20" class="edit-grid-count" value="${countGridTokens(pageCfg.grid.rows)}">
          <button class="edit-grid-btn" type="button" data-act="row-inc">+</button>
          <input type="text" class="edit-grid-raw" hidden value="${escapeAttr(pageCfg.grid.rows)}">
        </div>
        <button class="edit-grid-advanced" type="button" data-act="advanced"
                title="${tr("editor.show_raw_css")}" aria-label="${tr("editor.advanced_input")}">⌄</button>
        <span class="edit-page-spacer"></span>
        <button class="edit-page-move" type="button" data-act="move-left"
                title="${tr("editor.page_move_left")}" aria-label="${tr("editor.page_move_left")}">‹</button>
        <button class="edit-page-move" type="button" data-act="move-right"
                title="${tr("editor.page_move_right")}" aria-label="${tr("editor.page_move_right")}">›</button>
        <button class="edit-page-delete" type="button" data-act="delete-page"
                aria-label="${tr("editor.page_delete")}" title="${tr("editor.page_delete")}">×</button>
      `;
      pageEl.appendChild(bar);
      this._wirePageBar(bar, pageEl, pageCfg);
    }
  }

  _wirePageBar(bar, pageEl, pageCfg) {
    const titleInp = bar.querySelector('[data-field="title"]');
    titleInp.addEventListener("input", () => {
      pageCfg.title = titleInp.value;
    });

    const groups = bar.querySelectorAll(".edit-grid-group");
    for (const group of groups) {
      const field = group.dataset.field; // "columns" | "rows"
      const countInp = group.querySelector(".edit-grid-count");
      const rawInp = group.querySelector(".edit-grid-raw");
      const dec = group.querySelector('[data-act$="-dec"]');
      const inc = group.querySelector('[data-act$="-inc"]');

      const applyCount = (n) => {
        const clamped = Math.max(1, Math.min(20, Math.floor(n)));
        countInp.value = String(clamped);
        const newVal = uniformGrid(clamped);
        pageCfg.grid[field] = newVal;
        rawInp.value = newVal;
        this._applyGridToPage(pageEl, pageCfg);
        this._clampWidgetsToGrid(pageEl, pageCfg);
      };

      dec.addEventListener("click", () => applyCount((parseInt(countInp.value, 10) || 1) - 1));
      inc.addEventListener("click", () => applyCount((parseInt(countInp.value, 10) || 1) + 1));
      countInp.addEventListener("change", () => applyCount(parseInt(countInp.value, 10) || 1));

      rawInp.addEventListener("change", () => {
        const v = rawInp.value.trim();
        if (!v) {
          rawInp.value = pageCfg.grid[field];
          return;
        }
        pageCfg.grid[field] = v;
        countInp.value = String(countGridTokens(v));
        this._applyGridToPage(pageEl, pageCfg);
        this._clampWidgetsToGrid(pageEl, pageCfg);
      });
    }

    bar.querySelector('[data-act="advanced"]').addEventListener("click", () => {
      const open = bar.classList.toggle("is-advanced");
      for (const group of groups) {
        const count = group.querySelector(".edit-grid-count");
        const raw = group.querySelector(".edit-grid-raw");
        const btns = group.querySelectorAll(".edit-grid-btn");
        if (open) {
          count.hidden = true;
          btns.forEach((b) => { b.hidden = true; });
          raw.hidden = false;
        } else {
          // Sync raw → count when returning to simple mode.
          const v = raw.value.trim();
          if (v) pageCfg.grid[group.dataset.field] = v;
          count.value = String(countGridTokens(pageCfg.grid[group.dataset.field]));
          count.hidden = false;
          btns.forEach((b) => { b.hidden = false; });
          raw.hidden = true;
        }
      }
    });

    const updateMoveButtons = () => {
      const pages = this.getPages();
      const idx = pages.indexOf(pageCfg);
      bar.querySelector('[data-act="move-left"]').disabled = idx <= 0;
      bar.querySelector('[data-act="move-right"]').disabled = idx < 0 || idx >= pages.length - 1;
    };
    updateMoveButtons();
    bar.querySelector('[data-act="move-left"]').addEventListener("click", () => {
      this._movePage(pageCfg, -1);
    });
    bar.querySelector('[data-act="move-right"]').addEventListener("click", () => {
      this._movePage(pageCfg, +1);
    });
    bar.querySelector('[data-act="delete-page"]').addEventListener("click", async () => {
      const widgetCount = pageCfg.widgets.length;
      const label = pageCfg.title || pageCfg.id;
      let msg;
      if (widgetCount === 0) {
        msg = tr("editor.page_delete_confirm", { label });
      } else if (widgetCount === 1) {
        msg = tr("editor.page_delete_confirm_with_widget", { label, count: 1 });
      } else {
        msg = tr("editor.page_delete_confirm_with_widgets", { label, count: widgetCount });
      }
      const ok = await confirmDialog(msg, { okLabel: tr("common.delete"), danger: true });
      if (!ok) return;
      this._deletePage(pageCfg);
    });
  }

  _applyGridToPage(pageEl, pageCfg) {
    pageEl.style.gridTemplateColumns = pageCfg.grid.columns;
    pageEl.style.gridTemplateRows = pageCfg.grid.rows;
  }

  // After a grid shrink, push widgets back inside the new bounds so they
  // don't end up on auto-created tracks the user can't see.
  _clampWidgetsToGrid(pageEl, pageCfg) {
    const cols = countGridTokens(pageCfg.grid.columns);
    const rows = countGridTokens(pageCfg.grid.rows);
    for (const placement of pageCfg.widgets) {
      const before = { col: placement.col, row: placement.row, cs: placement.colspan, rs: placement.rowspan };
      placement.col = Math.max(1, Math.min(cols, placement.col || 1));
      placement.row = Math.max(1, Math.min(rows, placement.row || 1));
      placement.colspan = Math.max(1, Math.min(cols - placement.col + 1, placement.colspan || 1));
      placement.rowspan = Math.max(1, Math.min(rows - placement.row + 1, placement.rowspan || 1));
      if (
        before.col !== placement.col || before.row !== placement.row
        || before.cs !== placement.colspan || before.rs !== placement.rowspan
      ) {
        const wEl = Array.from(pageEl.querySelectorAll(".widget")).find((el) => {
          const id = el.className.match(/\bwidget-([\w-]+)\b/)?.[1];
          if (id !== placement.id) return false;
          // For multi-instance widgets use the snapshot of style before mutation
          const sc = parseInt(el.style.gridColumn, 10);
          const sr = parseInt(el.style.gridRow, 10);
          return sc === before.col && sr === before.row;
        });
        if (wEl) {
          wEl.style.gridColumn = `${placement.col} / span ${placement.colspan}`;
          wEl.style.gridRow = `${placement.row} / span ${placement.rowspan}`;
          this._refreshInfoLabel(wEl);
        }
      }
    }
  }

  _addPage() {
    const pages = this.getPages();
    const id = `page-${Date.now().toString(36).slice(-5)}`;
    const newPage = {
      id,
      title: tr("editor.new_page_title"),
      grid: { columns: "1fr 1fr", rows: "1fr 1fr", areas: [] },
      widgets: [],
    };
    // Insert after the currently visible page so the user can swipe right to it.
    const idx = this.swiper?.activeIndex ?? pages.length - 1;
    pages.splice(idx + 1, 0, newPage);
    this.setPages(pages);
    // Wait one tick so the new DOM is in place, then snap to it.
    requestAnimationFrame(() => this.swiper?.goTo(idx + 1));
  }

  _movePage(pageCfg, direction) {
    const pages = this.getPages();
    const from = pages.indexOf(pageCfg);
    const to = from + Math.sign(direction);
    if (from < 0 || to < 0 || to >= pages.length) return;
    pages.splice(to, 0, pages.splice(from, 1)[0]);
    this.setPages(pages);
    requestAnimationFrame(() => this.swiper?.goTo(to));
  }

  _deletePage(pageCfg) {
    const pages = this.getPages();
    if (pages.length <= 1) {
      this._showToast(tr("editor.page_must_remain"), "error");
      return;
    }
    const idx = pages.indexOf(pageCfg);
    if (idx < 0) return;
    pages.splice(idx, 1);
    this.setPages(pages);
    const target = Math.min(idx, pages.length - 1);
    requestAnimationFrame(() => this.swiper?.goTo(target));
  }

  _refreshInfoLabel(wEl) {
    const info = wEl.querySelector(".edit-info");
    if (!info) return;
    const { placement } = this._placementFor(wEl);
    if (!placement) return;
    info.textContent = `${placement.col},${placement.row} · ${placement.colspan || 1}×${placement.rowspan || 1}`;
  }

  _onPointerDown(e, wEl) {
    if (!this._active) return;
    const role = e.target.closest("[data-role]")?.dataset.role;
    if (role === "delete" || role === "info") return;
    e.stopPropagation();
    if (role === "resize") {
      this._startResize(e, wEl);
    } else {
      this._startDrag(e, wEl);
    }
  }

  _placementFor(wEl) {
    const pageEl = wEl.closest(".page");
    if (!pageEl) return { pageEl: null, pageCfg: null, placement: null };
    const widgetId = wEl.className.match(/\bwidget-([\w-]+)\b/)?.[1];
    const pageCfg = this._findPageByEl(pageEl);
    if (!pageCfg) return { pageEl, pageCfg: null, placement: null };
    // If same id appears multiple times on a page, pick the one bound to this DOM
    const matches = pageCfg.widgets.filter((w) => w.id === widgetId);
    let placement;
    if (matches.length === 1) {
      placement = matches[0];
    } else {
      // Disambiguate by current grid coordinates from inline style
      const styleCol = parseInt(wEl.style.gridColumn, 10);
      const styleRow = parseInt(wEl.style.gridRow, 10);
      placement = matches.find(
        (w) => w.col === styleCol && w.row === styleRow,
      ) ?? matches[0];
    }
    return { pageEl, pageCfg, placement };
  }

  _startDrag(e, wEl) {
    const { pageEl, placement } = this._placementFor(wEl);
    if (!placement || !pageEl) return;
    wEl.setPointerCapture(e.pointerId);
    wEl.classList.add("is-dragging");

    const onMove = (ev) => {
      const cell = cellFromPoint(pageEl, ev.clientX, ev.clientY, "nearest");
      const colspan = placement.colspan || 1;
      const rowspan = placement.rowspan || 1;
      placement.col = Math.max(1, Math.min(cell.cols - colspan + 1, cell.col));
      placement.row = Math.max(1, Math.min(cell.rows - rowspan + 1, cell.row));
      wEl.style.gridColumn = `${placement.col} / span ${colspan}`;
      wEl.style.gridRow = `${placement.row} / span ${rowspan}`;
      this._refreshInfoLabel(wEl);
    };
    const onUp = () => {
      wEl.classList.remove("is-dragging");
      wEl.removeEventListener("pointermove", onMove);
      wEl.removeEventListener("pointerup", onUp);
      wEl.removeEventListener("pointercancel", onUp);
    };
    wEl.addEventListener("pointermove", onMove);
    wEl.addEventListener("pointerup", onUp);
    wEl.addEventListener("pointercancel", onUp);
  }

  _startResize(e, wEl) {
    const { pageEl, placement } = this._placementFor(wEl);
    if (!placement || !pageEl) return;
    wEl.setPointerCapture(e.pointerId);
    wEl.classList.add("is-resizing");

    // 'inside' bias means: the pointer must clearly be inside the next cell to
    // bump colspan. Avoids accidental colspan jumps on narrow middle columns.
    const onMove = (ev) => {
      const cell = cellFromPoint(pageEl, ev.clientX, ev.clientY, "inside");
      const newColspan = Math.max(1, cell.col - placement.col + 1);
      const newRowspan = Math.max(1, cell.row - placement.row + 1);
      placement.colspan = Math.min(cell.cols - placement.col + 1, newColspan);
      placement.rowspan = Math.min(cell.rows - placement.row + 1, newRowspan);
      wEl.style.gridColumn = `${placement.col} / span ${placement.colspan}`;
      wEl.style.gridRow = `${placement.row} / span ${placement.rowspan}`;
      this._refreshInfoLabel(wEl);
    };
    const onUp = () => {
      wEl.classList.remove("is-resizing");
      wEl.removeEventListener("pointermove", onMove);
      wEl.removeEventListener("pointerup", onUp);
      wEl.removeEventListener("pointercancel", onUp);
    };
    wEl.addEventListener("pointermove", onMove);
    wEl.addEventListener("pointerup", onUp);
    wEl.addEventListener("pointercancel", onUp);
  }

  _findPageByEl(pageEl) {
    const id = pageEl.dataset.pageId;
    return this.getPages().find((p) => p.id === id);
  }

  _deleteWidget(wEl) {
    const { pageEl, pageCfg, placement } = this._placementFor(wEl);
    if (!pageCfg || !placement) return;
    // Remove from the live config object (mutate in place, no array swap so
    // other placement object references stay valid for any in-flight handlers)
    const idx = pageCfg.widgets.indexOf(placement);
    if (idx >= 0) pageCfg.widgets.splice(idx, 1);
    if (this.unmountWidget) {
      this.unmountWidget(wEl);
    } else {
      wEl.remove();
    }
  }

  _showAddPicker() {
    const placedIds = new Set();
    for (const page of this.getPages()) {
      for (const w of page.widgets) placedIds.add(w.id);
    }
    const candidates = this._availableWidgets.length
      ? this._availableWidgets
      : ["clock", "heartbeat", "cpu", "gpu", "ram", "network", "weather", "sensors", "media"];
    // Allow the same widget to be added on different pages — only filter from
    // the active picker if it's already on the *current* page.
    const idx = this.swiper?.activeIndex ?? 0;
    const currentPage = this.getPages()[idx];
    const onCurrent = new Set((currentPage?.widgets || []).map((w) => w.id));
    const available = candidates.filter((n) => !onCurrent.has(n));

    const picker = document.createElement("div");
    picker.id = "edit-picker";
    picker.innerHTML = `
      <div class="picker-backdrop"></div>
      <div class="picker-panel">
        <h3>${tr("editor.add_widget_title")}</h3>
        <div class="picker-grid"></div>
        <div class="picker-actions">
          <button class="btn" type="button" data-act="cancel">${tr("common.cancel")}</button>
        </div>
      </div>
    `;
    document.body.appendChild(picker);
    const close = () => picker.remove();
    picker.querySelector(".picker-backdrop").addEventListener("click", close);
    picker.querySelector('[data-act="cancel"]').addEventListener("click", close);

    const grid = picker.querySelector(".picker-grid");
    if (available.length === 0) {
      grid.innerHTML = `<div class="picker-empty">${tr("editor.picker_empty")}</div>`;
      return;
    }
    for (const name of available) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "picker-item";
      btn.textContent = name;
      btn.addEventListener("click", async () => {
        await this._addWidget(name);
        close();
      });
      grid.appendChild(btn);
    }
  }

  async _addWidget(name) {
    try {
      await import(`./widgets/${name}.js`);
    } catch (err) {
      console.error(`[editor] failed to load widget '${name}':`, err);
      this._showToast(tr("editor.widget_load_failed", { name }), "error");
      return;
    }
    const idx = this.swiper?.activeIndex ?? 0;
    const pages = this.getPages();
    const page = pages[idx];
    if (!page) return;
    const placement = {
      id: name,
      col: 1,
      row: 1,
      colspan: 1,
      rowspan: 1,
    };
    page.widgets.push(placement);
    const pageEl = this.pagesRoot.children[idx];
    const wEl = this.mountWidget?.(pageEl, placement);
    if (wEl) {
      this._attachWidgetHandles();
    }
  }
}
