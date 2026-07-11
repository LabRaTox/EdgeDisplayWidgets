// Quick Actions: a Stream-Deck-style deck of configurable touch tiles that
// fire backend-defined commands or HTTP requests, organised in folders.
// The frontend only knows opaque ids — the actual command/URL/headers live in
// the backend config.
//
// Layout: a *fixed* `columns`×`rows` grid (from config). Tiles sit at explicit
// (page, x, y) cell coordinates with a w×h span; tiles without coordinates are
// auto-flowed into free cells. The grid scales (square cells, centered) to the
// widget's current size and paginates the overflow. A `folder` tile opens a
// nested sub-deck; tiles with a status probe show a live on/off indicator.

import { registerWidget } from "../registry.js";
import { confirmDialog } from "../confirm.js";
import { t } from "../i18n.js";
import { iconMarkup } from "../lib/icon.js";
import { openTileEditor } from "./tile_editor.js";

const GAP = 8;
const MIN_CELL = 44; // px — never shrink tiles below this
const NAV_HEIGHT = 24; // px reserved for the pager/back strip

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

function safeColor(c) {
  return typeof c === "string" && /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(c) ? c : null;
}

function isDestructive(action) {
  const haystack = `${action.id} ${action.label || ""}`.toLowerCase();
  return /reboot|shutdown|poweroff|restart|neustart|herunterfahren|delete|löschen/.test(haystack);
}

function treeKey(tiles) {
  return (tiles || [])
    .map((a) => {
      const pos = `${a.page}/${a.x}/${a.y}/${a.w}/${a.h}`;
      return a.kind === "folder"
        ? `F:${a.id}:${a.label}:${a.icon}:${a.color}:${a.text_color}:${pos}:${a.back_x}/${a.back_y}(${treeKey(a.tiles)})`
        : `${a.id}:${a.label}:${a.icon}:${a.confirm}:${a.color}:${a.text_color}:${pos}:${a.state}`;
    })
    .join("|");
}

// Assign every tile a concrete (page, x, y) on a `cols`×`rows` grid: honour
// explicit coordinates, then auto-flow the rest into free cells. `reserved`
// cells (e.g. the folder back tile) are blocked on *every* page.
function assignPlacements(tiles, cols, rows, reserved = []) {
  const grids = new Map(); // page -> rows×cols occupancy
  const ensure = (p) => {
    if (!grids.has(p)) {
      const g = Array.from({ length: rows }, () => new Array(cols).fill(false));
      for (const c of reserved) {
        if (c.y >= 0 && c.y < rows && c.x >= 0 && c.x < cols) g[c.y][c.x] = true;
      }
      grids.set(p, g);
    }
    return grids.get(p);
  };
  const span = (v, max) => Math.min(Math.max(1, v || 1), max);
  const fits = (g, x, y, w, h) => {
    if (x + w > cols || y + h > rows) return false;
    for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) if (g[j][i]) return false;
    return true;
  };
  const mark = (g, x, y, w, h) => {
    for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) g[j][i] = true;
  };
  const findFree = (g, w, h) => {
    for (let y = 0; y <= rows - h; y++) for (let x = 0; x <= cols - w; x++) if (fits(g, x, y, w, h)) return { x, y };
    return null;
  };

  const placements = [];
  const isPos = (t) => Number.isInteger(t.x) && Number.isInteger(t.y);

  for (const t of tiles.filter(isPos)) {
    const w = span(t.w, cols);
    const h = span(t.h, rows);
    const p = t.page || 0;
    const g = ensure(p);
    let x = Math.max(0, Math.min(t.x, cols - w));
    let y = Math.max(0, Math.min(t.y, rows - h));
    if (!fits(g, x, y, w, h)) {
      const slot = findFree(g, w, h);
      if (slot) ({ x, y } = slot);
    }
    mark(g, x, y, w, h);
    placements.push({ tile: t, page: p, x, y, w, h });
  }

  let p = 0;
  for (const t of tiles.filter((x) => !isPos(x))) {
    const w = span(t.w, cols);
    const h = span(t.h, rows);
    let slot = null;
    while (!(slot = findFree(ensure(p), w, h))) p++;
    mark(ensure(p), slot.x, slot.y, w, h);
    placements.push({ tile: t, page: p, x: slot.x, y: slot.y, w, h });
  }

  const pages = placements.reduce((m, pl) => Math.max(m, pl.page + 1), 1);
  return { placements, pages };
}

class QuickActionsWidget {
  static modules = ["quick_actions"];

  mount(el) {
    this.el = el;
    el.classList.add("quick-actions-widget");
    el.innerHTML = `
      <div class="qa-deck" data-bind="deck">
        <div class="qa-deck-grid" data-bind="grid"></div>
        <div class="qa-deck-nav" data-bind="nav" hidden></div>
      </div>
    `;
    this.gridEl = el.querySelector('[data-bind="grid"]');
    this.navEl = el.querySelector('[data-bind="nav"]');
    this._root = [];
    this._cols = 4;
    this._rows = 3;
    this._path = []; // folder ids from the root to the open level
    this._page = 0;
    this._pages = 1;
    this._editing = false;

    this.navEl.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-nav]");
      if (!btn) return;
      const act = btn.dataset.nav;
      if (this._editing) {
        if (act === "edit-done") this._exitEdit(true);
        else if (act === "edit-cancel") this._exitEdit(false);
        else if (act === "prev") this._editGoto(this._editPage - 1);
        else if (act === "next") this._editGoto(this._editPage + 1);
        else if (act === "back") this._editAscend();
        return;
      }
      if (act === "prev") this._goto(this._page - 1);
      else if (act === "next") this._goto(this._page + 1);
      else if (act === "dot") this._goto(Number(btn.dataset.page));
      else if (act === "back") this._ascend();
    });

    this._wireLongPress();

    this._ro = new ResizeObserver(() => (this._editing ? this._renderEdit() : this._render()));
    this._ro.observe(this.gridEl);
  }

  // Long-press anywhere on the deck enters edit mode.
  _wireLongPress() {
    let timer = null;
    let start = null;
    const clear = () => {
      if (timer) clearTimeout(timer);
      timer = null;
      start = null;
    };
    this.gridEl.addEventListener("pointerdown", (e) => {
      if (this._editing) return;
      start = { x: e.clientX, y: e.clientY };
      // Remember which tile was pressed, so a long-press on a button edits it.
      const tileEl = e.target.closest(".qa-tile");
      const pressedId = tileEl?.dataset.id || null;
      timer = setTimeout(() => {
        timer = null;
        this._suppressClick = true;
        this._enterEdit(pressedId);
      }, 550);
    });
    this.gridEl.addEventListener("pointermove", (e) => {
      if (timer && start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 8) clear();
    });
    this.gridEl.addEventListener("pointerup", clear);
    this.gridEl.addEventListener("pointercancel", clear);
    // Swallow the click that would otherwise fire a tile after a long-press.
    this.gridEl.addEventListener(
      "click",
      (e) => {
        if (this._suppressClick) {
          e.stopPropagation();
          e.preventDefault();
          this._suppressClick = false;
        }
      },
      true,
    );
  }

  update(data) {
    const actions = data?.actions || [];
    const key = `${data?.columns}x${data?.rows}|${treeKey(actions)}`;
    if (key === this._lastKey) return;
    this._lastKey = key;
    this._root = actions;
    this._cols = data?.columns || 4;
    this._rows = data?.rows || 3;
    if (this._editing) return; // don't clobber an in-progress edit session
    this._render();
  }

  _currentTiles() {
    let list = this._root;
    let folder = null;
    const valid = [];
    for (const id of this._path) {
      const f = list.find((a) => a.id === id && a.kind === "folder");
      if (!f) break;
      valid.push(id);
      folder = f;
      list = f.tiles || [];
    }
    this._path = valid;
    this._currentFolder = folder; // the folder we're inside (null at root)
    return list;
  }

  // Where the back tile sits in the current folder (clamped to the grid).
  _backCell() {
    const f = this._currentFolder;
    if (!f) return null;
    return {
      x: Math.min(Math.max(0, f.back_x || 0), this._cols - 1),
      y: Math.min(Math.max(0, f.back_y || 0), this._rows - 1),
    };
  }

  _render() {
    const tiles = this._currentTiles();
    const cols = this._cols;
    const rows = this._rows;
    const back = this._backCell();
    const { placements, pages } = assignPlacements(tiles, cols, rows, back ? [back] : []);
    this._pages = pages;
    if (this._page >= pages) this._page = pages - 1;
    if (this._page < 0) this._page = 0;

    if (!tiles.length && !this._path.length) {
      this.gridEl.style.cssText = "";
      this.gridEl.innerHTML = `<div class="qa-empty">${t("widget.quick_actions.empty")}</div>`;
      this.navEl.hidden = true;
      return;
    }

    // Square cells that fit the available area, grid centered.
    const W = this.gridEl.clientWidth;
    const H = this.gridEl.clientHeight;
    const cell = Math.max(
      MIN_CELL,
      Math.floor(Math.min((W - (cols - 1) * GAP) / cols, (H - (rows - 1) * GAP) / rows)),
    );
    this.gridEl.style.gridTemplateColumns = `repeat(${cols}, ${cell}px)`;
    this.gridEl.style.gridTemplateRows = `repeat(${rows}, ${cell}px)`;
    this.gridEl.innerHTML = "";
    if (back) this.gridEl.appendChild(this._renderBackTile(back));
    for (const pl of placements) {
      if (pl.page !== this._page) continue;
      this.gridEl.appendChild(this._renderTile(pl));
    }
    this._renderNav();
  }

  _renderBackTile({ x, y }) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "qa-tile qa-tile-back";
    btn.style.gridColumn = `${x + 1}`;
    btn.style.gridRow = `${y + 1}`;
    btn.innerHTML = `
      <div class="qa-tile-icon">${iconMarkup("ti:arrow-back-up", { fallback: "‹" })}</div>
      <div class="qa-tile-label">${t("widget.quick_actions.back")}</div>
    `;
    btn.addEventListener("click", () => this._ascend());
    return btn;
  }

  _renderTile({ tile, x, y, w, h }) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "qa-tile";
    btn.dataset.id = tile.id;
    btn.style.gridColumn = `${x + 1} / span ${w}`;
    btn.style.gridRow = `${y + 1} / span ${h}`;
    if (tile.kind === "folder") btn.classList.add("qa-tile-folder");
    if (tile.confirm) btn.classList.add("has-confirm");
    const bg = safeColor(tile.color);
    const fg = safeColor(tile.text_color);
    const styles = [];
    if (bg) styles.push(`--qa-tile-bg:${bg}`);
    if (fg) styles.push(`--qa-tile-fg:${fg}`);
    if (styles.length) btn.style.cssText += ";" + styles.join(";");

    const statusDot =
      tile.has_status && (tile.state === "on" || tile.state === "off")
        ? `<span class="qa-tile-status is-${tile.state}" aria-hidden="true"></span>`
        : "";
    const folderBadge = tile.kind === "folder" ? `<span class="qa-tile-folder-badge" aria-hidden="true"></span>` : "";
    btn.innerHTML = `
      ${statusDot}${folderBadge}
      <div class="qa-tile-icon">${iconMarkup(tile.icon, { fallback: tile.kind === "folder" ? "▸" : "•" })}</div>
      <div class="qa-tile-label">${escapeHtml(tile.label || tile.id)}</div>
    `;

    if (tile.kind === "folder") {
      btn.addEventListener("click", () => this._descend(tile.id));
    } else {
      btn.addEventListener("click", () => this._run(tile, btn));
    }
    return btn;
  }

  _renderNav() {
    // The back affordance is now a grid tile; the nav strip is just the pager.
    if (this._pages <= 1) {
      this.navEl.hidden = true;
      this.navEl.innerHTML = "";
      return;
    }
    this.navEl.hidden = false;
    const dots = Array.from({ length: this._pages }, (_, i) =>
      `<button type="button" class="qa-deck-dot${i === this._page ? " is-active" : ""}" data-nav="dot" data-page="${i}" aria-label="${t("widget.quick_actions.page", { n: i + 1 })}"></button>`,
    ).join("");
    this.navEl.innerHTML = `
      <button type="button" class="qa-deck-arrow" data-nav="prev" aria-label="${t("common.prev")}" ${this._page === 0 ? "disabled" : ""}>‹</button>
      <div class="qa-deck-dots">${dots}</div>
      <button type="button" class="qa-deck-arrow" data-nav="next" aria-label="${t("common.next")}" ${this._page === this._pages - 1 ? "disabled" : ""}>›</button>`;
  }

  _descend(folderId) {
    this._path = [...this._path, folderId];
    this._page = 0;
    this._render();
  }

  _ascend() {
    this._path = this._path.slice(0, -1);
    this._page = 0;
    this._render();
  }

  _goto(page) {
    const next = Math.min(Math.max(0, page), this._pages - 1);
    if (next === this._page) return;
    this._page = next;
    this._render();
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
      if (action.has_status && (body.state === "on" || body.state === "off")) {
        action.state = body.state;
        this._lastKey = ""; // force re-render even if next poll is identical
        this._render();
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

  // ====================================================================
  // In-widget edit mode: drag tiles onto cells, resize, remove, quick-add.
  // Works on the *full* config (fetched fresh) so commands/URLs round-trip.
  // ====================================================================

  async _enterEdit(pressedId = null) {
    let body;
    try {
      const r = await fetch("/api/quick_actions/config");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      body = await r.json();
    } catch (err) {
      console.error("[quick_actions] edit load failed:", err);
      this._suppressClick = false;
      return;
    }
    this._editTree = Array.isArray(body.actions) ? body.actions : [];
    this._editCols = body.columns || this._cols;
    this._editRows = body.rows || this._rows;
    this._editPath = [...this._path];
    this._editPage = this._page;
    this._editing = true;
    // Mark loaded tiles as committed so the editor treats them as existing.
    for (const tile of this._walkEdit(this._editTree)) tile.__committed = true;
    // Materialise auto-flow positions so moving one tile can't shuffle others.
    this._materialize(this._editTree);
    this.el.classList.add("qa-editing");
    this._renderEdit();
    // Long-press directly on a button jumps straight into editing it.
    if (pressedId) {
      const tile = this._editLevel().find((tl) => tl.id === pressedId);
      if (tile) this._editTile(tile, false);
    }
  }

  *_walkEdit(list) {
    for (const tile of list) {
      yield tile;
      if (tile.kind === "folder") yield* this._walkEdit(tile.tiles || []);
    }
  }

  // Open the focused tile editor; apply/delete/open-folder/cancel.
  async _editTile(tile, isNew) {
    const res = await openTileEditor(tile, { onOpenFolder: () => {} });
    if (res === "deleted") {
      const list = this._editLevel();
      const i = list.indexOf(tile);
      if (i >= 0) list.splice(i, 1);
    } else if (res === "open-folder") {
      this._editPath = [...this._editPath, tile.id];
      this._editPage = 0;
    } else if (res === null && isNew) {
      const list = this._editLevel();
      const i = list.indexOf(tile);
      if (i >= 0) list.splice(i, 1);
    }
    this._renderEdit();
  }

  _materialize(tiles) {
    const { placements } = assignPlacements(tiles, this._editCols, this._editRows);
    for (const pl of placements) {
      pl.tile.x = pl.x;
      pl.tile.y = pl.y;
      pl.tile.page = pl.page;
      if (!pl.tile.w) pl.tile.w = pl.w;
      if (!pl.tile.h) pl.tile.h = pl.h;
    }
    for (const t of tiles) if (t.kind === "folder") this._materialize(t.tiles || (t.tiles = []));
  }

  _editLevel() {
    let list = this._editTree;
    let folder = null;
    for (const id of this._editPath) {
      const f = list.find((a) => a.id === id && a.kind === "folder");
      if (!f) break;
      folder = f;
      list = f.tiles || (f.tiles = []);
    }
    this._editFolderObj = folder; // the folder being edited (null at root)
    return list;
  }

  _editBackCell() {
    const f = this._editFolderObj;
    if (!f) return null;
    return {
      x: Math.min(Math.max(0, f.back_x || 0), this._editCols - 1),
      y: Math.min(Math.max(0, f.back_y || 0), this._editRows - 1),
    };
  }

  async _exitEdit(save) {
    if (save) {
      try {
        // Drop transient editor-only keys (e.g. __committed) — the backend
        // model forbids unknown fields.
        const cleanActions = JSON.parse(
          JSON.stringify(this._editTree, (k, v) => (k.startsWith("_") ? undefined : v)),
        );
        const r = await fetch("/api/quick_actions/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            actions: cleanActions,
            columns: this._editCols,
            rows: this._editRows,
          }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
        // Reflect the saved tree immediately; the WS poll refreshes states later.
        this._root = this._editTree;
        this._cols = this._editCols;
        this._rows = this._editRows;
        this._path = this._editPath.slice();
        this._lastKey = "";
      } catch (err) {
        console.error("[quick_actions] edit save failed:", err);
        return; // stay in edit mode so the user can retry
      }
    }
    this._editing = false;
    this.el.classList.remove("qa-editing");
    this._editTree = null;
    this._render();
  }

  _editGoto(page) {
    const max = this._editPagesCount() - 1;
    this._editPage = Math.min(Math.max(0, page), max);
    this._renderEdit();
  }

  _editAscend() {
    this._editPath = this._editPath.slice(0, -1);
    this._editPage = 0;
    this._renderEdit();
  }

  _editPagesCount() {
    const tiles = this._editLevel();
    return Math.max(1, tiles.reduce((m, t) => Math.max(m, (t.page || 0) + 1), 1));
  }

  _cellMetrics() {
    const cols = this._editCols;
    const rows = this._editRows;
    const W = this.gridEl.clientWidth;
    const H = this.gridEl.clientHeight;
    const cell = Math.max(
      MIN_CELL,
      Math.floor(Math.min((W - (cols - 1) * GAP) / cols, (H - (rows - 1) * GAP) / rows)),
    );
    const gridW = cols * cell + (cols - 1) * GAP;
    const gridH = rows * cell + (rows - 1) * GAP;
    const rect = this.gridEl.getBoundingClientRect();
    return {
      cols, rows, cell,
      originX: rect.left + Math.max(0, (rect.width - gridW) / 2),
      originY: rect.top + Math.max(0, (rect.height - gridH) / 2),
    };
  }

  _areaFree(x, y, w, h, except) {
    const tiles = this._editLevel();
    for (const t of tiles) {
      if (t === except || (t.page || 0) !== this._editPage) continue;
      const tw = t.w || 1;
      const th = t.h || 1;
      if (x < (t.x || 0) + tw && x + w > (t.x || 0) && y < (t.y || 0) + th && y + h > (t.y || 0)) return false;
    }
    return x + w <= this._editCols && y + h <= this._editRows && x >= 0 && y >= 0;
  }

  _renderEdit() {
    const { cols, rows, cell } = this._cellMetrics();
    const tiles = this._editLevel();
    const pageTiles = tiles.filter((t) => (t.page || 0) === this._editPage);
    const back = this._editBackCell();

    this.gridEl.style.gridTemplateColumns = `repeat(${cols}, ${cell}px)`;
    this.gridEl.style.gridTemplateRows = `repeat(${rows}, ${cell}px)`;
    this.gridEl.innerHTML = "";

    // Occupancy of the current page → render "+" placeholders on free cells.
    const occ = Array.from({ length: rows }, () => new Array(cols).fill(false));
    for (const t of pageTiles) {
      const w = t.w || 1;
      const h = t.h || 1;
      for (let j = t.y || 0; j < (t.y || 0) + h; j++)
        for (let i = t.x || 0; i < (t.x || 0) + w; i++) if (occ[j]?.[i] !== undefined) occ[j][i] = true;
    }
    if (back) occ[back.y][back.x] = true;
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        if (occ[y][x]) continue;
        const add = document.createElement("button");
        add.type = "button";
        add.className = "qa-edit-cell";
        add.style.gridColumn = `${x + 1}`;
        add.style.gridRow = `${y + 1}`;
        add.textContent = "+";
        add.addEventListener("click", () => this._openAddMenu(x, y));
        this.gridEl.appendChild(add);
      }
    }
    if (back) this.gridEl.appendChild(this._renderEditBackTile(back));
    for (const t of pageTiles) this.gridEl.appendChild(this._renderEditTile(t));
    this._renderEditToolbar();
  }

  _renderEditBackTile({ x, y }) {
    const folder = this._editFolderObj;
    const el = document.createElement("div");
    el.className = "qa-tile qa-tile-back qa-tile-edit qa-tile-back-edit";
    el.style.gridColumn = `${x + 1}`;
    el.style.gridRow = `${y + 1}`;
    el.innerHTML = `
      <div class="qa-tile-icon">${iconMarkup("ti:arrow-back-up", { fallback: "‹" })}</div>
      <div class="qa-tile-label">${t("widget.quick_actions.back")}</div>
    `;
    // Drag to reposition (updates the folder's back cell); a clean tap ascends.
    el.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      el.setPointerCapture(e.pointerId);
      el.classList.add("is-grabbing");
      const startX = folder.back_x || 0;
      const startY = folder.back_y || 0;
      let moved = false;
      let nx = startX;
      let ny = startY;
      const move = (ev) => {
        const m = this._cellMetrics();
        const cx = Math.round((ev.clientX - m.originX - m.cell / 2) / (m.cell + GAP));
        const cy = Math.round((ev.clientY - m.originY - m.cell / 2) / (m.cell + GAP));
        nx = Math.min(Math.max(0, cx), m.cols - 1);
        ny = Math.min(Math.max(0, cy), m.rows - 1);
        moved = moved || nx !== startX || ny !== startY;
        el.style.gridColumn = `${nx + 1}`;
        el.style.gridRow = `${ny + 1}`;
      };
      const up = () => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up);
        el.removeEventListener("pointercancel", up);
        el.classList.remove("is-grabbing");
        if (!moved) {
          this._editAscend();
          return;
        }
        if (this._areaFree(nx, ny, 1, 1, null)) {
          folder.back_x = nx;
          folder.back_y = ny;
        }
        this._renderEdit();
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
      el.addEventListener("pointercancel", up);
    });
    return el;
  }

  _renderEditTile(tile) {
    const w = tile.w || 1;
    const h = tile.h || 1;
    const btn = document.createElement("div");
    btn.className = "qa-tile qa-tile-edit";
    if (tile.kind === "folder") btn.classList.add("qa-tile-folder");
    btn.style.gridColumn = `${(tile.x || 0) + 1} / span ${w}`;
    btn.style.gridRow = `${(tile.y || 0) + 1} / span ${h}`;
    const bg = safeColor(tile.color);
    const fg = safeColor(tile.text_color);
    const styles = [];
    if (bg) styles.push(`--qa-tile-bg:${bg}`);
    if (fg) styles.push(`--qa-tile-fg:${fg}`);
    if (styles.length) btn.style.cssText += ";" + styles.join(";");
    const folderBadge = tile.kind === "folder" ? `<span class="qa-tile-folder-badge" aria-hidden="true"></span>` : "";
    btn.innerHTML = `
      <button type="button" class="qa-edit-remove" aria-label="${t("widget.quick_actions.remove")}">×</button>
      ${folderBadge}
      <div class="qa-tile-icon">${iconMarkup(tile.icon, { fallback: tile.kind === "folder" ? "▸" : "•" })}</div>
      <div class="qa-tile-label">${escapeHtml(tile.label || tile.id)}</div>
      <span class="qa-edit-resize" aria-label="resize"></span>
    `;
    btn.querySelector(".qa-edit-remove").addEventListener("click", (e) => {
      e.stopPropagation();
      const list = this._editLevel();
      const i = list.indexOf(tile);
      if (i >= 0) list.splice(i, 1);
      this._renderEdit();
    });
    btn.querySelector(".qa-edit-resize").addEventListener("pointerdown", (e) => this._beginResize(e, tile, btn));
    btn.addEventListener("pointerdown", (e) => this._beginMove(e, tile, btn));
    return btn;
  }

  _beginMove(e, tile, el) {
    if (e.target.closest(".qa-edit-remove, .qa-edit-resize")) return;
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    el.classList.add("is-grabbing");
    const startX = tile.x || 0;
    const startY = tile.y || 0;
    const w = tile.w || 1;
    const h = tile.h || 1;
    let moved = false;
    let nx = startX;
    let ny = startY;
    const move = (ev) => {
      const { cols, rows, cell, originX, originY } = this._cellMetrics();
      const cx = Math.round((ev.clientX - originX - (w * (cell + GAP)) / 2 + cell / 2) / (cell + GAP));
      const cy = Math.round((ev.clientY - originY - (h * (cell + GAP)) / 2 + cell / 2) / (cell + GAP));
      nx = Math.min(Math.max(0, cx), cols - w);
      ny = Math.min(Math.max(0, cy), rows - h);
      moved = moved || nx !== startX || ny !== startY;
      el.style.gridColumn = `${nx + 1} / span ${w}`;
      el.style.gridRow = `${ny + 1} / span ${h}`;
    };
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      el.classList.remove("is-grabbing");
      if (!moved) {
        // A clean tap opens the focused tile editor.
        this._editTile(tile, false);
        return;
      }
      if (this._areaFree(nx, ny, w, h, tile)) {
        tile.x = nx;
        tile.y = ny;
      }
      this._renderEdit();
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  }

  _beginResize(e, tile, el) {
    e.preventDefault();
    e.stopPropagation();
    el.setPointerCapture(e.pointerId);
    const x = tile.x || 0;
    const y = tile.y || 0;
    let nw = tile.w || 1;
    let nh = tile.h || 1;
    const move = (ev) => {
      const { cols, rows, cell, originX, originY } = this._cellMetrics();
      nw = Math.min(Math.max(1, Math.round((ev.clientX - originX - x * (cell + GAP)) / (cell + GAP))), Math.min(4, cols - x));
      nh = Math.min(Math.max(1, Math.round((ev.clientY - originY - y * (cell + GAP)) / (cell + GAP))), Math.min(4, rows - y));
      el.style.gridColumn = `${x + 1} / span ${nw}`;
      el.style.gridRow = `${y + 1} / span ${nh}`;
    };
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      if (this._areaFree(x, y, nw, nh, tile)) {
        tile.w = nw;
        tile.h = nh;
      }
      this._renderEdit();
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  }

  _renderEditToolbar() {
    this.navEl.hidden = false;
    const pages = this._editPagesCount();
    const pager = pages > 1
      ? `<button type="button" class="qa-deck-arrow" data-nav="prev" ${this._editPage === 0 ? "disabled" : ""}>‹</button>
         <span class="qa-edit-pageno">${this._editPage + 1}/${pages}</span>
         <button type="button" class="qa-deck-arrow" data-nav="next" ${this._editPage === pages - 1 ? "disabled" : ""}>›</button>`
      : "";
    this.navEl.innerHTML = `
      <button type="button" class="qa-edit-btn" data-nav="edit-cancel">${t("common.cancel")}</button>
      <span class="qa-deck-nav-spacer"></span>
      ${pager}
      <span class="qa-deck-nav-spacer"></span>
      <button type="button" class="qa-edit-btn is-primary" data-nav="edit-done">${t("common.save")}</button>
    `;
  }

  // ---- Quick-add: presets + folder + blank ----
  _openAddMenu(x, y) {
    const existing = this.el.querySelector(".qa-add-menu");
    if (existing) existing.remove();
    const menu = document.createElement("div");
    menu.className = "qa-add-menu";
    menu.innerHTML = `
      <button type="button" class="qa-add-item qa-add-custom" data-i="custom">
        <span class="qa-add-icon">${iconMarkup("ti:square-rounded-plus", { fallback: "+" })}</span>
        <span>${t("qa_preset.custom")}</span>
      </button>
      <button type="button" class="qa-add-item qa-add-custom" data-i="app">
        <span class="qa-add-icon">${iconMarkup("ti:apps", { fallback: "▦" })}</span>
        <span>${t("qa_preset.launch")}</span>
      </button>
      ${PRESETS.map(
        (p, i) =>
          `<button type="button" class="qa-add-item" data-i="${i}">
             <span class="qa-add-icon">${iconMarkup(p.icon, { fallback: "•" })}</span>
             <span>${t(p.labelKey)}</span>
           </button>`,
      ).join("")}`;
    this.el.appendChild(menu);
    const close = () => {
      menu.remove();
      document.removeEventListener("pointerdown", onDoc, true);
    };
    const onDoc = (e) => {
      if (!menu.contains(e.target)) close();
    };
    setTimeout(() => document.addEventListener("pointerdown", onDoc, true), 0);
    menu.addEventListener("click", (e) => {
      const item = e.target.closest(".qa-add-item");
      if (!item) return;
      close();
      if (item.dataset.i === "custom") this._addCustom(x, y);
      else if (item.dataset.i === "app") this._openAppPicker(x, y);
      else this._addPreset(PRESETS[Number(item.dataset.i)], x, y);
    });
  }

  // Pick an installed program → drop a launch button on the deck.
  async _openAppPicker(x, y) {
    let apps = [];
    try {
      const r = await fetch("/api/apps");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      apps = (await r.json()).apps || [];
    } catch (err) {
      console.error("[quick_actions] app list failed:", err);
      return;
    }
    const overlay = document.createElement("div");
    overlay.className = "qa-app-overlay";
    overlay.innerHTML = `
      <div class="qa-app-picker" role="dialog" aria-modal="true">
        <input type="search" class="qa-app-search" placeholder="${t("qa_preset.launch_search")}" autocomplete="off">
        <div class="qa-app-list" data-bind="list"></div>
      </div>`;
    document.body.appendChild(overlay);
    const listEl = overlay.querySelector('[data-bind="list"]');
    const search = overlay.querySelector(".qa-app-search");

    let matches = apps;
    const render = (q) => {
      const ql = q.trim().toLowerCase();
      matches = ql ? apps.filter((a) => a.name.toLowerCase().includes(ql)) : apps;
      listEl.innerHTML = matches.length
        ? matches.map((a, i) => {
            const ico = a.icon
              ? `<img class="qa-app-ico" src="/api/apps/icon/${encodeURIComponent(a.icon)}" alt="">`
              : `<span class="qa-app-ico qa-app-ico-ph">${iconMarkup("ti:app-window")}</span>`;
            return `<button type="button" class="qa-app-item" data-i="${i}">${ico}<span class="qa-app-name">${escapeHtml(a.name)}</span></button>`;
          }).join("")
        : `<div class="qa-app-empty">—</div>`;
    };
    // Broken theme icons just collapse to nothing (error doesn't bubble → capture).
    listEl.addEventListener("error", (e) => {
      if (e.target.classList?.contains("qa-app-ico")) e.target.style.visibility = "hidden";
    }, true);
    render("");

    const close = () => {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
    };
    const onKey = (e) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    overlay.addEventListener("pointerdown", (e) => {
      if (e.target === overlay) close();
    });
    search.addEventListener("input", () => render(search.value));
    listEl.addEventListener("click", (e) => {
      const btn = e.target.closest(".qa-app-item");
      if (!btn) return;
      const app = matches[Number(btn.dataset.i)];
      if (app) {
        close();
        this._addApp(app, x, y);
      }
    });
    requestAnimationFrame(() => search.focus());
  }

  _addApp(app, x, y) {
    // Use the real app icon when we resolved one, else a generic Tabler glyph.
    const icon = app.icon && /^[A-Za-z0-9._+-]+$/.test(app.icon) ? `app:${app.icon}` : "ti:app-window";
    const tile = {
      id: this._uniqueId("launch"),
      kind: "shell",
      label: app.name,
      icon,
      command: app.exec,
      detach: true,
      page: this._editPage,
      x, y, w: 1, h: 1,
      __committed: true,
    };
    this._editLevel().push(tile);
    this._renderEdit();
  }

  _uniqueId(base) {
    const ids = new Set();
    for (const tile of this._walkEdit(this._editTree)) ids.add(tile.id);
    let id = base || "tile";
    let n = 1;
    while (ids.has(id)) id = `${base}-${n++}`;
    return id;
  }

  _addPreset(preset, x, y) {
    const tile = { ...preset.build(), id: this._uniqueId(preset.id || "tile"), page: this._editPage, x, y, w: 1, h: 1, __committed: true };
    this._editLevel().push(tile);
    this._renderEdit();
  }

  // Blank tile + open the editor right away; cancel removes it.
  _addCustom(x, y) {
    const tile = { id: this._uniqueId("button"), kind: "shell", label: "", icon: "", command: ["true"], page: this._editPage, x, y, w: 1, h: 1 };
    this._editLevel().push(tile);
    this._renderEdit();
    this._editTile(tile, true);
  }

  destroy() {
    this._ro?.disconnect();
  }
}

// Quick-add presets. Commands target a typical Linux desktop session; the user
// can fine-tune them in the settings editor afterwards.
const PRESETS = [
  { id: "lock", icon: "ti:lock", labelKey: "qa_preset.lock",
    build: () => ({ kind: "shell", label: "Sperren", icon: "ti:lock", command: ["loginctl", "lock-session"] }) },
  { id: "reboot", icon: "ti:refresh", labelKey: "qa_preset.reboot",
    build: () => ({ kind: "shell", label: "Reboot", icon: "ti:refresh", command: ["systemctl", "reboot"], confirm: true, color: "#7c3aed", text_color: "#ffffff" }) },
  { id: "vol-up", icon: "ti:volume", labelKey: "qa_preset.vol_up",
    build: () => ({ kind: "shell", label: "Lauter", icon: "ti:volume", command: ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"] }) },
  { id: "vol-down", icon: "ti:volume-3", labelKey: "qa_preset.vol_down",
    build: () => ({ kind: "shell", label: "Leiser", icon: "ti:volume-3", command: ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"] }) },
  { id: "folder", icon: "ti:folder", labelKey: "qa_preset.folder",
    build: () => ({ kind: "folder", label: "Ordner", icon: "ti:folder", tiles: [], color: "#2563eb", text_color: "#ffffff" }) },
  { id: "blank", icon: "ti:square-plus", labelKey: "qa_preset.blank",
    build: () => ({ kind: "shell", label: "Neu", icon: "", command: ["true"] }) },
];

registerWidget("quick_actions", QuickActionsWidget);
