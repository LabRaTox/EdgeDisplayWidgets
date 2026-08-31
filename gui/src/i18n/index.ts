/**
 * Interface language.
 *
 * Two sources, deliberately: this window ships the strings for its own chrome
 * (menus, window title, banners), and it pulls the *dashboard's* translation
 * file from the backend at startup. Module settings label themselves with
 * keys like `settings.mod.disk_usage.mounts`, which live in
 * frontend/locales/<code>.json — fetching them means a new module's labels
 * appear here the moment the backend knows about them, with no second copy to
 * keep in sync.
 *
 * The kiosk's files use flat, dotted keys and `{placeholder}` interpolation,
 * so i18next is configured to match rather than the other way round.
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { api } from "../api/client";
import de from "./de.json";
import en from "./en.json";

export const SUPPORTED_LANGUAGES = ["de", "en"] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

const STORAGE_KEY = "edge-dashboard-gui.lang";

/** Language names in their own language, so the picker reads correctly. */
export const LANGUAGE_LABELS: Record<Language, string> = {
  de: "Deutsch",
  en: "English",
};

function detect(): Language {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && (SUPPORTED_LANGUAGES as readonly string[]).includes(stored)) {
      return stored as Language;
    }
  } catch {
    /* private mode — fall through to the browser's preference */
  }
  for (const raw of navigator.languages ?? [navigator.language]) {
    const short = String(raw).slice(0, 2).toLowerCase();
    if ((SUPPORTED_LANGUAGES as readonly string[]).includes(short)) {
      return short as Language;
    }
  }
  return "en";
}

void i18n.use(initReactI18next).init({
  resources: {
    de: { translation: de },
    en: { translation: en },
  },
  lng: detect(),
  fallbackLng: "en",
  // The dashboard's keys are literal dotted strings, not a nested tree.
  keySeparator: false,
  nsSeparator: false,
  interpolation: { escapeValue: false, prefix: "{", suffix: "}" },
});

/** Remember the choice for the next start of the window. */
export async function setLanguage(language: Language): Promise<void> {
  try {
    localStorage.setItem(STORAGE_KEY, language);
  } catch {
    /* not fatal — the choice just won't outlive the window */
  }
  await i18n.changeLanguage(language);
  await loadDashboardStrings(language);
}

/**
 * Merge the dashboard's translation file in *underneath* our own strings:
 * where both define a key, the window's wording wins, because it was written
 * for a desktop window rather than a touch sheet.
 */
export async function loadDashboardStrings(language: string): Promise<void> {
  try {
    const strings = await api.locale(language);
    i18n.addResourceBundle(language, "translation", strings, true, false);
  } catch {
    // Backend not reachable yet. The window stays usable; the offline banner
    // already tells the story, and this retries on the next language change.
  }
}

export default i18n;
