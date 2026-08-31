import { useState } from "react";
import type { DragEvent } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useDraft } from "../lib/useDraft";
import { useStore } from "../store";
import type { QuickAction, QuickActionsConfig } from "../types";
import { Icon } from "./Icon";
import { IconPicker } from "./IconPicker";
import { SaveBar } from "./SaveBar";

/**
 * The quick-action deck.
 *
 * On the kiosk this was a long-press edit mode on the widget itself: fine for
 * moving a tile with a finger, painful for typing an argv list or a header.
 * Here the deck stays as the map — click a cell, edit the tile beside it — but
 * the fields get room, and the parts the touch editor could not show at all
 * (status probes, HTTP headers) are editable for the first time.
 */
export function ActionsView() {
  const { t } = useTranslation();
  const upstream = useStore((s) => s.quickActions);
  const saveQuickActions = useStore((s) => s.saveQuickActions);
  const { draft, dirty, state, edit, reset, save } = useDraft(upstream);

  /** Ids of the folders we descended into — empty means the top deck. */
  const [path, setPath] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  /** Cell the pointer is currently over while dragging, for the drop hint. */
  const [dropCell, setDropCell] = useState<string | null>(null);
  const [runState, setRunState] = useState<string | null>(null);

  if (!draft) {
    return (
      <div className="view">
        <div className="view-head">
          <h2>{t("actions.title")}</h2>
          <p className="muted">{t("common.loading")}</p>
        </div>
      </div>
    );
  }

  // The list currently on screen: the root actions, or the tiles of the
  // folder we walked into.
  const tilesAt = (actions: QuickAction[], walk: string[]): QuickAction[] => {
    let current = actions;
    for (const id of walk) {
      const folder = current.find((a) => a.id === id);
      if (!folder?.tiles) return [];
      current = folder.tiles;
    }
    return current;
  };

  /** Apply an update to the list at the current path, rebuilding the tree. */
  const editTiles = (update: (tiles: QuickAction[]) => QuickAction[]) =>
    edit((config) => {
      const rebuild = (tiles: QuickAction[], walk: string[]): QuickAction[] => {
        if (walk.length === 0) return update(tiles);
        const [head, ...rest] = walk;
        return tiles.map((tile) =>
          tile.id === head
            ? { ...tile, tiles: rebuild(tile.tiles ?? [], rest) }
            : tile,
        );
      };
      return { ...config, actions: rebuild(config.actions, path) };
    });

  const tiles = tilesAt(draft.actions, path);
  const selected = tiles.find((tile) => tile.id === selectedId) ?? null;
  const columns = Math.min(Math.max(draft.columns, 1), 8);
  const rows = Math.min(Math.max(draft.rows, 1), 8);

  /** Every id in the tree — new tiles must not collide with any of them. */
  const allIds = (tiles: QuickAction[]): string[] =>
    tiles.flatMap((tile) => [tile.id, ...allIds(tile.tiles ?? [])]);

  /**
   * Add a tile, optionally pinned to a cell.
   *
   * `at` is what the "+" in an empty cell passes: a tile created there gets
   * that cell explicitly, so it stays where it was clicked instead of
   * flowing into the first free spot.
   */
  const addTile = (kind: QuickAction["kind"], at?: { x: number; y: number }) => {
    const taken = new Set(allIds(draft.actions));
    let id = kind === "folder" ? "folder" : "action";
    for (let n = 1; taken.has(id); n += 1) id = `${kind === "folder" ? "folder" : "action"}-${n}`;
    const base: QuickAction =
      kind === "folder"
        ? { id, kind: "folder", label: id, tiles: [] }
        : kind === "http"
          ? { id, kind: "http", label: id, url: "", method: "POST" }
          : { id, kind: "shell", label: id, command: [""] };
    const tile = at ? { ...base, x: at.x, y: at.y } : base;
    editTiles((current) => [...current, tile]);
    setSelectedId(id);
  };

  const patchSelected = (update: Partial<QuickAction>) => {
    if (!selected) return;
    editTiles((current) =>
      current.map((tile) => (tile.id === selected.id ? { ...tile, ...update } : tile)),
    );
    if (update.id) setSelectedId(update.id);
  };

  // Where each tile sits, computed exactly as the widget computes it.
  const { placements, pages } = assignPlacements(tiles, columns, rows);
  /** Origin cell -> placement, for the tiles on the page this preview shows. */
  const onThisPage = placements.filter((entry) => entry.page === 0);
  const placed = new Map(onThisPage.map((entry) => [`${entry.x},${entry.y}`, entry]));
  /** Every cell a tile covers, so no "+" is drawn underneath a wide tile. */
  const covered = new Set<string>();
  for (const entry of onThisPage) {
    for (let y = entry.y; y < entry.y + entry.h; y += 1) {
      for (let x = entry.x; x < entry.x + entry.w; x += 1) covered.add(`${x},${y}`);
    }
  }

  /**
   * Drop a dragged tile onto a cell.
   *
   * Both tiles get an explicit position afterwards, including the dragged one
   * when it had none: a tile that was flowing into a free cell would jump
   * somewhere else entirely the moment another tile takes its place, which
   * looks like the drag went wrong. Landing on an occupied cell swaps the
   * two, so nothing is ever pushed out of the grid by a drag.
   */
  const moveTile = (dragId: string, x: number, y: number) => {
    const source = tiles.find((tile) => tile.id === dragId);
    if (!source) return;
    // The tile under the drop point, which is the one covering that cell and
    // not necessarily the one whose origin it is.
    const target =
      onThisPage.find(
        (entry) =>
          x >= entry.x && x < entry.x + entry.w && y >= entry.y && y < entry.y + entry.h,
      ) ?? null;
    if (target && target.tile.id === dragId) return;

    // The cell the dragged tile currently occupies, which is not tile.x/y
    // when it was flowing.
    const from = onThisPage.find((entry) => entry.tile.id === dragId) ?? null;

    editTiles((current) =>
      current.map((tile) => {
        if (tile.id === dragId) return { ...tile, x, y };
        if (target && tile.id === target.tile.id && from) {
          return { ...tile, x: from.x, y: from.y };
        }
        return tile;
      }),
    );
    setSelectedId(dragId);
  };

  return (
    <div className="view">
      <div className="view-head">
        <h2>{t("actions.title")}</h2>
        <p>{t("actions.help")}</p>
      </div>

      {path.length > 0 && (
        <div className="inline">
          <button className="btn small" type="button" onClick={() => setPath([])}>
            ← {t("actions.back_to_root")}
          </button>
          <span className="muted">
            {t("actions.inside_folder", { name: path[path.length - 1] })}
          </span>
        </div>
      )}

      <div className="editor-split">
        <div className="card">
          <header>
            <h3>{t("actions.grid")}</h3>
            <div className="spacer" />
            <label className="inline">
              <span className="muted">{t("actions.columns")}</span>
              <input
                type="number"
                min={1}
                max={8}
                value={draft.columns}
                style={{ width: 64 }}
                onChange={(e) =>
                  edit((c) => ({ ...c, columns: Number(e.target.value) || 1 }))
                }
              />
            </label>
            <label className="inline">
              <span className="muted">{t("actions.rows")}</span>
              <input
                type="number"
                min={1}
                max={8}
                value={draft.rows}
                style={{ width: 64 }}
                onChange={(e) => edit((c) => ({ ...c, rows: Number(e.target.value) || 1 }))}
              />
            </label>
          </header>

          <div
            className="deck"
            style={{
              gridTemplateColumns: `repeat(${columns}, 1fr)`,
              gridTemplateRows: `repeat(${rows}, 1fr)`,
              aspectRatio: `${columns} / ${rows}`,
            }}
          >
            {Array.from({ length: columns * rows }, (_, index) => {
              const x = index % columns;
              const y = Math.floor(index / columns);
              const cell = `${x},${y}`;
              const entry = placed.get(cell);
              // A cell covered by a wide tile but not its origin draws
              // nothing: it is already filled by that tile, which spans over
              // it. Rendering a "+" there would push the rest of the grid
              // along by one.
              if (!entry && covered.has(cell)) return null;

              // Accepting the drop on every cell, empty or not: dropping onto
              // a tile swaps the two, which is the only way to reorder a full
              // grid without emptying a cell first.
              const dropProps = {
                onDragOver: (event: DragEvent) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "move";
                  setDropCell(cell);
                },
                onDragLeave: () => setDropCell((current) => (current === cell ? null : current)),
                onDrop: (event: DragEvent) => {
                  event.preventDefault();
                  setDropCell(null);
                  const dragId = event.dataTransfer.getData("text/plain");
                  if (dragId) moveTile(dragId, x, y);
                },
              };
              const over = dropCell === cell ? " drop-target" : "";
              // Every cell is placed explicitly. Left to the auto-flow, a
              // tile spanning several columns would shift everything after
              // it, and the preview would stop matching the display.
              const area = {
                gridColumn: `${x + 1} / span ${entry?.w ?? 1}`,
                gridRow: `${y + 1} / span ${entry?.h ?? 1}`,
              };

              if (!entry) {
                return (
                  <div key={index} className={`deck-tile empty${over}`} style={area} {...dropProps}>
                    {/* The "+" is the button, not the whole cell: the cell
                        itself is a drop target, and a click anywhere on it
                        would create a tile every time a drag was aimed at it
                        and released elsewhere. */}
                    <button
                      type="button"
                      className="deck-add"
                      title={t("actions.new_tile_at", { col: x + 1, row: y + 1 })}
                      onClick={() => addTile("shell", { x, y })}
                    >
                      +
                    </button>
                  </div>
                );
              }

              const tile = entry.tile;
              return (
                <div
                  key={index}
                  className={`deck-tile ${selectedId === tile.id ? "active" : ""}${over}`}
                  style={{
                    ...area,
                    background: tile.color ?? undefined,
                    color: tile.text_color ?? undefined,
                  }}
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.setData("text/plain", tile.id);
                    event.dataTransfer.effectAllowed = "move";
                    setSelectedId(tile.id);
                  }}
                  onDragEnd={() => setDropCell(null)}
                  onClick={() => setSelectedId(tile.id)}
                  onDoubleClick={() => {
                    if (tile.kind === "folder") {
                      setPath([...path, tile.id]);
                      setSelectedId(null);
                    }
                  }}
                  {...dropProps}
                >
                  {tile.icon ? (
                    <span className="tile-icon">
                      <Icon icon={tile.icon} />
                    </span>
                  ) : (
                    <span className="tile-kind">
                      {tile.kind === "folder" ? "▤" : tile.kind}
                    </span>
                  )}
                  <span className="tile-label">{tile.label || tile.id}</span>
                </div>
              );
            })}
          </div>

          {pages > 1 && (
            // The widget pages the deck when tiles do not fit; the preview
            // only draws the first page. Without this the extra tiles look
            // deleted rather than moved on.
            <div className="hint" style={{ marginTop: 8 }}>
              {t("actions.more_pages", {
                count: placements.filter((entry) => entry.page > 0).length,
                pages: pages - 1,
              })}
            </div>
          )}

          <div className="inline" style={{ marginTop: 12 }}>
            <button className="btn small" type="button" onClick={() => addTile("shell")}>
              + {t("actions.new_tile")}
            </button>
            <button className="btn small" type="button" onClick={() => addTile("folder")}>
              + {t("actions.new_folder")}
            </button>
          </div>
          {tiles.length === 0 && <div className="hint">{t("actions.empty")}</div>}
        </div>

        {selected ? (
          <TileEditor
            tile={selected}
            columns={columns}
            rows={rows}
            runState={runState}
            onPatch={patchSelected}
            onEnter={() => {
              setPath([...path, selected.id]);
              setSelectedId(null);
            }}
            onDelete={() => {
              editTiles((current) => current.filter((tile) => tile.id !== selected.id));
              setSelectedId(null);
            }}
            onRun={async () => {
              setRunState(null);
              try {
                const result = await api.runQuickAction(selected.id);
                setRunState(result.ok ? t("actions.test_ok") : (result.error ?? "?"));
              } catch (err) {
                setRunState(err instanceof Error ? err.message : String(err));
              }
            }}
          />
        ) : (
          <div className="card">
            <p className="muted">{t("actions.pick_tile")}</p>
          </div>
        )}
      </div>

      <SaveBar
        dirty={dirty}
        state={state}
        onReset={reset}
        onSave={() => void save((config: QuickActionsConfig) => saveQuickActions(config))}
      />
    </div>
  );
}

export interface Placement {
  tile: QuickAction;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Deck page the tile ends up on; only page 0 is shown in this preview. */
  page: number;
}

/**
 * Work out where every tile actually lands.
 *
 * A port of `assignPlacements` in frontend/js/widgets/quick_actions.js, and it
 * has to stay one: the editor is a preview of that widget, and a preview that
 * computes positions differently from the thing it previews is worse than no
 * preview at all. Explicit coordinates win, a tile that does not fit where it
 * asks moves to the first free area of its size, and tiles without
 * coordinates flow into whatever is left, onto a further page if need be.
 */
function assignPlacements(
  tiles: QuickAction[],
  columns: number,
  rows: number,
): { placements: Placement[]; pages: number } {
  const grids = new Map<number, boolean[][]>();
  const ensure = (page: number) => {
    let grid = grids.get(page);
    if (!grid) {
      grid = Array.from({ length: rows }, () => new Array<boolean>(columns).fill(false));
      grids.set(page, grid);
    }
    return grid;
  };
  const span = (value: number | null | undefined, max: number) =>
    Math.min(Math.max(1, value || 1), max);
  const fits = (grid: boolean[][], x: number, y: number, w: number, h: number) => {
    if (x + w > columns || y + h > rows) return false;
    for (let j = y; j < y + h; j += 1) {
      for (let i = x; i < x + w; i += 1) if (grid[j][i]) return false;
    }
    return true;
  };
  const mark = (grid: boolean[][], x: number, y: number, w: number, h: number) => {
    for (let j = y; j < y + h; j += 1) {
      for (let i = x; i < x + w; i += 1) grid[j][i] = true;
    }
  };
  const findFree = (grid: boolean[][], w: number, h: number) => {
    for (let y = 0; y <= rows - h; y += 1) {
      for (let x = 0; x <= columns - w; x += 1) if (fits(grid, x, y, w, h)) return { x, y };
    }
    return null;
  };

  const placements: Placement[] = [];
  const positioned = (tile: QuickAction) =>
    Number.isInteger(tile.x) && Number.isInteger(tile.y);

  for (const tile of tiles.filter(positioned)) {
    const w = span(tile.w, columns);
    const h = span(tile.h, rows);
    const grid = ensure(0);
    let x = Math.max(0, Math.min(tile.x as number, columns - w));
    let y = Math.max(0, Math.min(tile.y as number, rows - h));
    if (!fits(grid, x, y, w, h)) {
      const slot = findFree(grid, w, h);
      if (slot) ({ x, y } = slot);
    }
    mark(grid, x, y, w, h);
    placements.push({ tile, x, y, w, h, page: 0 });
  }

  let page = 0;
  for (const tile of tiles.filter((entry) => !positioned(entry))) {
    const w = span(tile.w, columns);
    const h = span(tile.h, rows);
    let slot = findFree(ensure(page), w, h);
    while (!slot) {
      page += 1;
      slot = findFree(ensure(page), w, h);
    }
    mark(ensure(page), slot.x, slot.y, w, h);
    placements.push({ tile, x: slot.x, y: slot.y, w, h, page });
  }

  const pages = placements.reduce((most, one) => Math.max(most, one.page + 1), 1);
  return { placements, pages };
}

function TileEditor({
  tile,
  columns,
  rows,
  runState,
  onPatch,
  onEnter,
  onDelete,
  onRun,
}: {
  tile: QuickAction;
  columns: number;
  rows: number;
  runState: string | null;
  onPatch: (update: Partial<QuickAction>) => void;
  onEnter: () => void;
  onDelete: () => void;
  onRun: () => void;
}) {
  const { t } = useTranslation();
  const [pickerOpen, setPickerOpen] = useState(false);

  return (
    <div className="card">
      <header>
        <h3>{tile.label || tile.id}</h3>
        <div className="spacer" />
        {tile.kind === "folder" && (
          <button className="btn small" type="button" onClick={onEnter}>
            {t("actions.kind_folder")} →
          </button>
        )}
        {tile.kind !== "folder" && (
          <button className="btn small" type="button" onClick={onRun}>
            {t("actions.test")}
          </button>
        )}
        <button className="btn small danger" type="button" onClick={onDelete}>
          {t("common.delete")}
        </button>
      </header>

      <div className="card-body">
        {runState && <div className="hint">{runState}</div>}

        <div className="row">
          <label htmlFor="tile-id">id</label>
          <div className="control">
            <input
              id="tile-id"
              value={tile.id}
              onChange={(e) => onPatch({ id: e.target.value })}
            />
          </div>
        </div>

        <div className="row">
          <label htmlFor="tile-label">{t("actions.label")}</label>
          <div className="control">
            <input
              id="tile-label"
              value={tile.label ?? ""}
              onChange={(e) => onPatch({ label: e.target.value })}
            />
          </div>
        </div>

        <div className="row">
          <label htmlFor="tile-icon">{t("actions.icon")}</label>
          <div className="control">
            {/* Field and picker side by side: the picker covers the two
                icon sets, and the field still takes anything typed or pasted,
                which is how an icon set in the YAML stays editable. */}
            <div className="inline icon-field">
              <button
                type="button"
                className="btn small icon-trigger"
                title={t("icons.choose")}
                onClick={() => setPickerOpen((open) => !open)}
              >
                {tile.icon ? <Icon icon={tile.icon} /> : <span className="muted">+</span>}
              </button>
              <input
                id="tile-icon"
                value={tile.icon ?? ""}
                placeholder="ti:player-play · 🎵"
                onChange={(e) => onPatch({ icon: e.target.value })}
              />
              {pickerOpen && (
                <IconPicker
                  value={tile.icon ?? ""}
                  onChange={(icon) => onPatch({ icon })}
                  onClose={() => setPickerOpen(false)}
                />
              )}
            </div>
          </div>
        </div>

        <div className="row">
          <label>{t("actions.color")}</label>
          <div className="control inline">
            <input
              type="color"
              value={tile.color ?? "#1b1b20"}
              onChange={(e) => onPatch({ color: e.target.value })}
            />
            <input
              type="color"
              value={tile.text_color ?? "#e9e9ee"}
              onChange={(e) => onPatch({ text_color: e.target.value })}
              title={t("actions.text_color")}
            />
            <button
              className="btn small ghost"
              type="button"
              onClick={() => onPatch({ color: null, text_color: null })}
            >
              {t("common.reset")}
            </button>
          </div>
        </div>

        <div className="row">
          <label>{t("layout.position")}</label>
          {/* Shown 1-based, stored 0-based: the deck grid is indexed from 0 in
              the config and in the widget, but nobody counts tiles that way
              when looking at the display. Empty stays empty, which is what
              tells the deck to place the tile in the next free slot. */}
          <div className="control inline">
            <input
              type="number"
              min={1}
              max={columns}
              value={tile.x == null ? "" : tile.x + 1}
              placeholder={t("layout.col")}
              title={t("layout.col")}
              style={{ width: 72 }}
              onChange={(e) =>
                onPatch({ x: e.target.value === "" ? null : Number(e.target.value) - 1 })
              }
            />
            <input
              type="number"
              min={1}
              max={rows}
              value={tile.y == null ? "" : tile.y + 1}
              placeholder={t("layout.row")}
              title={t("layout.row")}
              style={{ width: 72 }}
              onChange={(e) =>
                onPatch({ y: e.target.value === "" ? null : Number(e.target.value) - 1 })
              }
            />
          </div>
        </div>

        <div className="row">
          <label>{t("layout.span")}</label>
          <div className="control inline">
            <input
              type="number"
              min={1}
              max={columns}
              value={tile.w ?? 1}
              placeholder={t("layout.colspan")}
              title={t("layout.colspan")}
              style={{ width: 72 }}
              onChange={(e) => onPatch({ w: Number(e.target.value) || 1 })}
            />
            <input
              type="number"
              min={1}
              max={rows}
              value={tile.h ?? 1}
              placeholder={t("layout.rowspan")}
              title={t("layout.rowspan")}
              style={{ width: 72 }}
              onChange={(e) => onPatch({ h: Number(e.target.value) || 1 })}
            />
          </div>
        </div>

        {tile.kind === "shell" && (
          <>
            <div className="row">
              <label htmlFor="tile-command">{t("actions.command")}</label>
              <div className="control">
                <textarea
                  id="tile-command"
                  value={(tile.command ?? []).join("\n")}
                  onChange={(e) =>
                    onPatch({ command: e.target.value.split("\n") })
                  }
                />
                <div className="hint">{t("actions.command_help")}</div>
              </div>
            </div>
            <div className="row">
              <label htmlFor="tile-detach">{t("actions.detach")}</label>
              <div className="control">
                <input
                  id="tile-detach"
                  type="checkbox"
                  checked={Boolean(tile.detach)}
                  onChange={(e) => onPatch({ detach: e.target.checked })}
                />
              </div>
            </div>
          </>
        )}

        {tile.kind === "http" && (
          <>
            <div className="row">
              <label htmlFor="tile-url">{t("actions.url")}</label>
              <div className="control">
                <input
                  id="tile-url"
                  value={tile.url ?? ""}
                  placeholder="https://homeassistant.local:8123/api/…"
                  onChange={(e) => onPatch({ url: e.target.value })}
                />
              </div>
            </div>
            <div className="row">
              <label htmlFor="tile-method">{t("actions.method")}</label>
              <div className="control">
                <select
                  id="tile-method"
                  value={tile.method ?? "POST"}
                  onChange={(e) => onPatch({ method: e.target.value })}
                >
                  {["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => (
                    <option key={method}>{method}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="row">
              <label>{t("actions.headers")}</label>
              <div className="control">
                <KeyValueEditor
                  value={tile.headers ?? {}}
                  onChange={(headers) => onPatch({ headers })}
                />
              </div>
            </div>
          </>
        )}

        <div className="row">
          <label htmlFor="tile-confirm">{t("actions.confirm")}</label>
          <div className="control">
            <input
              id="tile-confirm"
              type="checkbox"
              checked={Boolean(tile.confirm)}
              onChange={(e) => onPatch({ confirm: e.target.checked })}
            />
          </div>
        </div>

        {tile.kind !== "folder" && (
          <StatusEditor tile={tile} onPatch={onPatch} />
        )}
      </div>
    </div>
  );
}

function StatusEditor({
  tile,
  onPatch,
}: {
  tile: QuickAction;
  onPatch: (update: Partial<QuickAction>) => void;
}) {
  const { t } = useTranslation();
  const status = tile.status ?? null;

  return (
    <>
      <div className="row">
        <label htmlFor="tile-status">{t("actions.status")}</label>
        <div className="control">
          <select
            id="tile-status"
            value={status?.kind ?? ""}
            onChange={(e) => {
              const kind = e.target.value;
              if (!kind) return onPatch({ status: null });
              onPatch({
                status:
                  kind === "shell"
                    ? { kind: "shell", command: ["systemctl", "is-active", "unit"] }
                    : { kind: "http", url: "", method: "GET" },
              });
            }}
          >
            <option value="">{t("actions.status_none")}</option>
            <option value="shell">{t("actions.kind_shell")}</option>
            <option value="http">{t("actions.kind_http")}</option>
          </select>
          <div className="hint">{t("actions.status_help")}</div>
        </div>
      </div>

      {status?.kind === "shell" && (
        <div className="row">
          <label htmlFor="status-command">{t("actions.command")}</label>
          <div className="control">
            <textarea
              id="status-command"
              value={(status.command ?? []).join("\n")}
              onChange={(e) =>
                onPatch({ status: { ...status, command: e.target.value.split("\n") } })
              }
            />
          </div>
        </div>
      )}

      {status?.kind === "http" && (
        <div className="row">
          <label htmlFor="status-url">{t("actions.url")}</label>
          <div className="control">
            <input
              id="status-url"
              value={status.url ?? ""}
              onChange={(e) => onPatch({ status: { ...status, url: e.target.value } })}
            />
          </div>
        </div>
      )}

      {status && (
        <div className="row">
          <label htmlFor="status-match">{t("actions.status_match")}</label>
          <div className="control">
            <input
              id="status-match"
              value={status.match ?? ""}
              placeholder="^active"
              onChange={(e) =>
                onPatch({ status: { ...status, match: e.target.value || undefined } })
              }
            />
          </div>
        </div>
      )}
    </>
  );
}

function KeyValueEditor({
  value,
  onChange,
}: {
  value: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
}) {
  const { t } = useTranslation();
  const entries = Object.entries(value);

  const replace = (index: number, key: string, val: string) => {
    const next = entries.map((entry, i) => (i === index ? [key, val] : entry));
    onChange(Object.fromEntries(next.filter(([k]) => k !== "")));
  };

  return (
    <div>
      {entries.map(([key, val], index) => (
        <div className="list-row" key={index}>
          <input
            value={key}
            placeholder="Authorization"
            onChange={(e) => replace(index, e.target.value, val)}
          />
          <input
            value={val}
            placeholder="Bearer …"
            onChange={(e) => replace(index, key, e.target.value)}
          />
          <button
            className="btn small ghost"
            type="button"
            onClick={() =>
              onChange(
                Object.fromEntries(entries.filter((_, i) => i !== index)),
              )
            }
          >
            ✕
          </button>
        </div>
      ))}
      <button
        className="btn small"
        type="button"
        style={{ marginTop: 6 }}
        onClick={() => onChange({ ...value, "": "" })}
      >
        {t("common.add")}
      </button>
    </div>
  );
}
