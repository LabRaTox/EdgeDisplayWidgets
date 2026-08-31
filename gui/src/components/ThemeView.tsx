import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { API_BASE } from "../api/client";
import { useDraft } from "../lib/useDraft";
import { useStore } from "../store";
import type { Settings } from "../types";
import { SaveBar } from "./SaveBar";

/** Language choices for the *kiosk*; the window's own language is in the menu. */
const DISPLAY_LANGUAGES = ["auto", "en", "de"];

interface ThemeDraft {
  default_theme: string;
  default_language: string;
}

export function ThemeView() {
  const { t } = useTranslation();
  const settings = useStore((s) => s.settings);
  const themes = useStore((s) => s.themes);
  const saveSettings = useStore((s) => s.saveSettings);

  // Memoised because it is built here rather than taken from the store: an
  // object rebuilt on every render makes every render look like a change to
  // whatever consumes it. useDraft compares by value and would cope, but not
  // handing it churn in the first place is cheaper and clearer.
  const upstream: ThemeDraft | null = useMemo(
    () =>
      settings
        ? {
            default_theme: settings.default_theme,
            default_language: settings.default_language ?? "auto",
          }
        : null,
    [settings],
  );
  const { draft, dirty, state, edit, reset, save } = useDraft(upstream);
  if (!draft) return null;

  return (
    <div className="view">
      <div className="view-head">
        <h2>{t("theme.title")}</h2>
        <p>{t("theme.help")}</p>
      </div>

      <div className="card">
        <div className="theme-grid">
          {themes.map((name) => (
            <button
              key={name}
              type="button"
              className={`theme-tile ${draft.default_theme === name ? "active" : ""}`}
              onClick={() => edit((d) => ({ ...d, default_theme: name }))}
            >
              <ThemeSwatch name={name} />
              {name}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="row">
          <label htmlFor="display-language">{t("theme.language")}</label>
          <div className="control">
            <select
              id="display-language"
              value={draft.default_language}
              onChange={(e) => edit((d) => ({ ...d, default_language: e.target.value }))}
            >
              {DISPLAY_LANGUAGES.map((code) => (
                <option key={code} value={code}>
                  {code === "auto" ? t("theme.language_auto") : code.toUpperCase()}
                </option>
              ))}
            </select>
            <div className="hint">{t("theme.language_help")}</div>
          </div>
        </div>
      </div>

      <SaveBar
        dirty={dirty}
        state={state}
        onReset={reset}
        onSave={() =>
          void save(async (value: ThemeDraft) => {
            await saveSettings(value as unknown as Partial<Settings>);
          })
        }
      />
    </div>
  );
}

/**
 * A strip of the theme's own CSS, rendered by letting the browser load the
 * actual stylesheet into an isolated frame. Guessing at colours would drift
 * from the themes the moment someone edits one; this cannot.
 */
function ThemeSwatch({ name }: { name: string }) {
  const href = `${API_BASE}/css/themes/${encodeURIComponent(name)}.css`;
  const html = `<!doctype html><link rel="stylesheet" href="${href}">
    <style>
      html,body{margin:0;height:100%}
      body{background:var(--bg,#111);display:flex;align-items:stretch}
      i{flex:1}
      .a{background:var(--accent,#3b82f6)}
      .b{background:var(--accent-2,var(--accent,#666))}
      .c{background:var(--panel,var(--bg-raised,#222))}
    </style>
    <i class="c"></i><i class="a"></i><i class="b"></i><i class="c"></i>`;
  return (
    <iframe
      className="theme-swatch"
      title={name}
      srcDoc={html}
      tabIndex={-1}
      scrolling="no"
    />
  );
}
