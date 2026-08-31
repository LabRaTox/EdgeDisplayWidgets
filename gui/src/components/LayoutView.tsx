import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useDraft } from "../lib/useDraft";
import { useStore } from "../store";
import type { Page, WidgetPlacement } from "../types";
import { SaveBar } from "./SaveBar";

/**
 * Pages and their widget placement.
 *
 * On the kiosk this used to be an edit mode drawn on top of the live
 * dashboard: you dragged the real widgets around. In a window that is not
 * possible and, for this job, not desirable either — a placeholder grid shows
 * the *structure* without live data fighting for attention, and the preview is
 * locked to the display's 32:9 proportion so a layout that looks balanced here
 * is balanced there.
 */

/** How many columns/rows a CSS grid template describes. */
function countTracks(template: string): number {
  const trimmed = template.trim();
  if (!trimmed) return 1;
  // `repeat(4, 1fr)` is the one function that changes the count.
  const repeat = /repeat\(\s*(\d+)\s*,/.exec(trimmed);
  if (repeat) return Number(repeat[1]);
  // Otherwise: top-level tokens, with the contents of any minmax(...) ignored.
  let depth = 0;
  let tokens = 0;
  let inToken = false;
  for (const char of trimmed) {
    if (char === "(") depth += 1;
    else if (char === ")") depth -= 1;
    else if (depth === 0 && /\s/.test(char)) {
      inToken = false;
      continue;
    }
    if (depth === 0 && !inToken) {
      inToken = true;
      tokens += 1;
    }
  }
  return Math.max(1, tokens);
}

export function LayoutView() {
  const { t } = useTranslation();
  const settings = useStore((s) => s.settings);
  const widgets = useStore((s) => s.widgets);
  const widgetVariants = useStore((s) => s.widgetVariants);
  const saveSettings = useStore((s) => s.saveSettings);

  const { draft, dirty, state, edit, reset, save } = useDraft(
    settings ? settings.pages : null,
  );
  const [pageIndex, setPageIndex] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);

  if (!draft) return null;
  const page = draft[Math.min(pageIndex, draft.length - 1)];
  if (!page) return null;

  const columns = countTracks(page.grid.columns);
  const rows = countTracks(page.grid.rows);

  const editPage = (update: (current: Page) => Page) =>
    edit((pages) => pages.map((p, i) => (i === pageIndex ? update(p) : p)));

  const editWidget = (index: number, update: (w: WidgetPlacement) => WidgetPlacement) =>
    editPage((p) => ({
      ...p,
      widgets: p.widgets.map((w, i) => (i === index ? update(w) : w)),
    }));

  return (
    <div className="view">
      <div className="view-head">
        <h2>{t("layout.title")}</h2>
        <p>{t("layout.help")}</p>
      </div>

      <div className="tabs">
        {draft.map((entry, index) => (
          <button
            key={entry.id}
            type="button"
            className={index === pageIndex ? "active" : ""}
            onClick={() => {
              setPageIndex(index);
              setSelected(null);
            }}
          >
            {entry.title || entry.id}
          </button>
        ))}
        <button
          className="btn small"
          type="button"
          onClick={() => {
            const id = uniqueId(draft, "page");
            edit((pages) => [
              ...pages,
              {
                id,
                title: id,
                grid: { columns: "1fr 1fr", rows: "1fr 1fr", areas: [] },
                widgets: [],
              },
            ]);
            setPageIndex(draft.length);
            setSelected(null);
          }}
        >
          + {t("layout.new_page")}
        </button>
      </div>

      <div className="card">
        <header>
          <h3>{page.title || page.id}</h3>
          <div className="spacer" />
          <button
            className="btn small danger"
            type="button"
            disabled={draft.length <= 1}
            title={draft.length <= 1 ? t("layout.last_page") : undefined}
            onClick={() => {
              if (!confirm(t("layout.delete_page_confirm", { name: page.title || page.id })))
                return;
              edit((pages) => pages.filter((_, i) => i !== pageIndex));
              setPageIndex(Math.max(0, pageIndex - 1));
              setSelected(null);
            }}
          >
            {t("layout.delete_page")}
          </button>
        </header>

        <div className="card-body">
          <div className="row">
            <label htmlFor="page-id">{t("layout.page_id")}</label>
            <div className="control">
              <input
                id="page-id"
                value={page.id}
                onChange={(e) => editPage((p) => ({ ...p, id: e.target.value }))}
              />
              {draft.filter((p) => p.id === page.id).length > 1 && (
                <div className="hint" style={{ color: "var(--danger)" }}>
                  {t("layout.duplicate_id")}
                </div>
              )}
            </div>
          </div>

          <div className="row">
            <label htmlFor="page-title">{t("layout.page_title")}</label>
            <div className="control">
              <input
                id="page-title"
                value={page.title}
                onChange={(e) => editPage((p) => ({ ...p, title: e.target.value }))}
              />
            </div>
          </div>

          <div className="row">
            <label htmlFor="page-cols">{t("layout.columns")}</label>
            <div className="control">
              <input
                id="page-cols"
                value={page.grid.columns}
                onChange={(e) =>
                  editPage((p) => ({ ...p, grid: { ...p.grid, columns: e.target.value } }))
                }
              />
            </div>
          </div>

          <div className="row">
            <label htmlFor="page-rows">{t("layout.rows")}</label>
            <div className="control">
              <input
                id="page-rows"
                value={page.grid.rows}
                onChange={(e) =>
                  editPage((p) => ({ ...p, grid: { ...p.grid, rows: e.target.value } }))
                }
              />
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <header>
          <h3>{t("layout.preview")}</h3>
          <div className="spacer" />
          <span className="muted">
            {columns} × {rows}
          </span>
        </header>
        <div
          className="page-preview"
          style={{
            gridTemplateColumns: page.grid.columns,
            gridTemplateRows: page.grid.rows,
          }}
        >
          {page.widgets.map((widget, index) => {
            const outside =
              widget.col + widget.colspan - 1 > columns ||
              widget.row + widget.rowspan - 1 > rows;
            return (
              <div
                key={index}
                className={`page-cell ${selected === index ? "selected" : ""} ${
                  outside ? "invalid" : ""
                }`}
                style={{
                  gridColumn: `${widget.col} / span ${widget.colspan}`,
                  gridRow: `${widget.row} / span ${widget.rowspan}`,
                }}
                onClick={() => setSelected(index)}
                title={outside ? t("layout.out_of_grid") : undefined}
              >
                {widget.id}
                {widget.variant ? ` · ${widget.variant}` : ""}
              </div>
            );
          })}
        </div>
      </div>

      <div className="card">
        <header>
          <h3>{t("layout.widgets")}</h3>
          <div className="spacer" />
          <select
            value=""
            onChange={(e) => {
              if (!e.target.value) return;
              editPage((p) => ({
                ...p,
                widgets: [
                  ...p.widgets,
                  { id: e.target.value, col: 1, row: 1, colspan: 1, rowspan: 1 },
                ],
              }));
              setSelected(page.widgets.length);
              e.target.value = "";
            }}
            style={{ width: 220 }}
          >
            <option value="">+ {t("layout.add_widget")}</option>
            {widgets.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </header>

        <div className="card-body">
          {page.widgets.length === 0 && <div className="hint">{t("modules.list_empty")}</div>}
          {page.widgets.map((widget, index) => (
            <div className="row" key={index}>
              <label>
                <button
                  className="btn small ghost"
                  type="button"
                  onClick={() => setSelected(index)}
                >
                  {widget.id}
                </button>
              </label>
              <div className="control inline" style={{ flexWrap: "wrap" }}>
                <NumberBox
                  label={t("layout.col")}
                  value={widget.col}
                  min={1}
                  max={columns}
                  onChange={(v) => editWidget(index, (w) => ({ ...w, col: v }))}
                />
                <NumberBox
                  label={t("layout.row")}
                  value={widget.row}
                  min={1}
                  max={rows}
                  onChange={(v) => editWidget(index, (w) => ({ ...w, row: v }))}
                />
                {/* Arrows rather than words: spelt out, five labelled fields
                    plus the variant no longer fit on one line. The meaning is
                    in the tooltip. */}
                <NumberBox
                  label="↔"
                  title={t("layout.colspan")}
                  value={widget.colspan}
                  min={1}
                  max={columns}
                  onChange={(v) => editWidget(index, (w) => ({ ...w, colspan: v }))}
                />
                <NumberBox
                  label="↕"
                  title={t("layout.rowspan")}
                  value={widget.rowspan}
                  min={1}
                  max={rows}
                  onChange={(v) => editWidget(index, (w) => ({ ...w, rowspan: v }))}
                />
                <VariantPicker
                  value={widget.variant ?? ""}
                  options={widgetVariants[widget.id] ?? []}
                  onChange={(value) =>
                    editWidget(index, (w) => ({ ...w, variant: value || null }))
                  }
                />
                <button
                  className="btn small ghost"
                  type="button"
                  title={t("common.remove")}
                  onClick={() => {
                    editPage((p) => ({
                      ...p,
                      widgets: p.widgets.filter((_, i) => i !== index),
                    }));
                    setSelected(null);
                  }}
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <SaveBar
        dirty={dirty}
        state={state}
        onReset={reset}
        onSave={() =>
          void save((pages: Page[]) =>
            // `area` is the legacy placement format; the backend resolves it
            // into col/row on load, and sending it back would override the
            // numbers just edited here.
            saveSettings({
              pages: pages.map((p) => ({
                ...p,
                grid: { ...p.grid, areas: [] },
                widgets: p.widgets.map(({ area: _area, ...rest }) => rest),
              })),
            }),
          )
        }
      />
    </div>
  );
}

/**
 * The display variant of one widget.
 *
 * The options come from the widget's own JS file (`static variants`), read by
 * the backend — so this offers exactly what the widget can actually do,
 * rather than a name that has to be remembered correctly.
 *
 * A value that is not on the list is kept as an option regardless. Widgets
 * lose and gain variants as they are edited, and dropping an unknown one
 * silently would rewrite a layout on the next save without anyone asking for
 * it.
 */
function VariantPicker({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const known = value === "" || options.includes(value);
  return (
    <select
      value={value}
      title={t("layout.variant_help")}
      style={{ width: 130 }}
      disabled={options.length === 0 && known}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{t("layout.variant_none")}</option>
      {options.map((name) => (
        <option key={name} value={name}>
          {t([`layout.variant_${name}`, name])}
        </option>
      ))}
      {!known && (
        <option value={value}>{t("layout.variant_unknown", { name: value })}</option>
      )}
    </select>
  );
}

function NumberBox({
  label,
  title,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  /** Spelt-out meaning, for the labels that are only an arrow. */
  title?: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="inline" style={{ gap: 4 }} title={title}>
      <span className="muted">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        style={{ width: 68 }}
        onChange={(e) => onChange(Math.max(min, Number(e.target.value) || min))}
      />
    </label>
  );
}

function uniqueId(pages: Page[], base: string): string {
  const taken = new Set(pages.map((p) => p.id));
  if (!taken.has(base)) return base;
  for (let n = 2; ; n += 1) {
    const candidate = `${base}-${n}`;
    if (!taken.has(candidate)) return candidate;
  }
}
