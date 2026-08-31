// Quick Actions: a Stream-Deck-style deck of configurable touch tiles that
// fire backend-defined commands or HTTP requests, organised in folders.
// The frontend only knows opaque ids — the actual command/URL/headers live in
// the backend config.
//
// Display only: tiles are arranged and edited in the settings window (see
// gui/), not by long-pressing the deck. What that window saves arrives here
// as a fresh module payload, so the deck redraws on its own.
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

    this.navEl.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-nav]");
      if (!btn) return;
      const act = btn.dataset.nav;
      if (act === "prev") this._goto(this._page - 1);
      else if (act === "next") this._goto(this._page + 1);
      else if (act === "dot") this._goto(Number(btn.dataset.page));
      else if (act === "back") this._ascend();
    });

    this._ro = new ResizeObserver(() => this._render());
    this._ro.observe(this.gridEl);
  }

  update(data) {
    const actions = data?.actions || [];
    const key = `${data?.columns}x${data?.rows}|${treeKey(actions)}`;
    if (key === this._lastKey) return;
    this._lastKey = key;
    this._root = actions;
    this._cols = data?.columns || 4;
    this._rows = data?.rows || 3;
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

  destroy() {
    this._ro?.disconnect();
  }
}

registerWidget("quick_actions", QuickActionsWidget);

