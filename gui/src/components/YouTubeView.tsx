import { useTranslation } from "react-i18next";

import { useDraft } from "../lib/useDraft";
import { useStore } from "../store";
import type { ModuleSettings } from "../types";
import { SaveBar } from "./SaveBar";

/** Entries may be plain strings or objects the backend enriched with a title. */
function entryToText(entry: unknown): string {
  if (typeof entry === "string") return entry;
  if (entry && typeof entry === "object") {
    const record = entry as Record<string, unknown>;
    return String(record.url ?? record.id ?? "");
  }
  return "";
}

export function YouTubeView() {
  const { t } = useTranslation();
  const settings = useStore((s) => s.settings);
  const saveSettings = useStore((s) => s.saveSettings);

  const upstream = settings?.modules.youtube ?? null;
  const { draft, dirty, state, edit, reset, save } = useDraft(upstream);
  if (!draft) return null;

  const entries = Array.isArray(draft.entries)
    ? (draft.entries as unknown[]).map(entryToText)
    : [];

  // Empty rows are kept while editing — a field you just cleared should stay
  // where it is instead of vanishing under the cursor. They are dropped once,
  // on save.
  const setEntries = (next: string[]) => edit((d) => ({ ...d, entries: next }));

  return (
    <div className="view">
      <div className="view-head">
        <h2>{t("youtube.title")}</h2>
        <p>{t("youtube.help")}</p>
      </div>

      <div className="card">
        {entries.length === 0 && <div className="hint">{t("modules.list_empty")}</div>}
        {entries.map((entry, index) => (
          <div className="list-row" key={index}>
            <input
              value={entry}
              placeholder={t("youtube.entry_placeholder")}
              onChange={(e) =>
                setEntries(entries.map((v, i) => (i === index ? e.target.value : v)))
              }
            />
            <button
              className="btn small ghost"
              type="button"
              title={t("common.up")}
              disabled={index === 0}
              onClick={() => {
                const next = [...entries];
                [next[index - 1], next[index]] = [next[index]!, next[index - 1]!];
                setEntries(next);
              }}
            >
              ↑
            </button>
            <button
              className="btn small ghost"
              type="button"
              title={t("common.down")}
              disabled={index === entries.length - 1}
              onClick={() => {
                const next = [...entries];
                [next[index + 1], next[index]] = [next[index]!, next[index + 1]!];
                setEntries(next);
              }}
            >
              ↓
            </button>
            <button
              className="btn small ghost"
              type="button"
              title={t("common.remove")}
              onClick={() => setEntries(entries.filter((_, i) => i !== index))}
            >
              ✕
            </button>
          </div>
        ))}
        <button
          className="btn small"
          type="button"
          style={{ marginTop: 8 }}
          onClick={() => setEntries([...entries, ""])}
        >
          {t("common.add")}
        </button>
      </div>

      <SaveBar
        dirty={dirty}
        state={state}
        onReset={reset}
        onSave={() =>
          void save((youtube: ModuleSettings) =>
            saveSettings({
              modules: {
                youtube: {
                  ...youtube,
                  entries: (youtube.entries as string[]).filter(
                    (line) => line.trim() !== "",
                  ),
                },
              },
            }),
          )
        }
      />
    </div>
  );
}
