// Tiny i18n: flat key lookup with {placeholder} substitution.
//
// The language comes from the backend config (`default_language`), because the
// settings window is a separate application and cannot write this display's
// localStorage. "auto" — the default — falls back to detecting it from
// navigator.languages, which is what the kiosk did before there was a window
// to choose in. localStorage only caches the result so index.html can set
// <html lang> before the first response arrives. Locale JSON lives in
// /locales/<code>.json and is fetched at init — adding a new language = drop a
// JSON file + extend SUPPORTED below.

const STORAGE_KEY = "edge-dashboard.lang";
const FALLBACK = "en";

// Display names use the language's own endonym so the picker is readable
// regardless of the current UI language.
export const SUPPORTED = [
  { code: "en", label: "English" },
  { code: "de", label: "Deutsch" },
];

const SUPPORTED_CODES = SUPPORTED.map((l) => l.code);

let _strings = {};
let _fallbackStrings = {};
let _current = FALLBACK;
const _listeners = new Set();

function detectBrowserLang() {
  const langs = navigator.languages?.length
    ? navigator.languages
    : [navigator.language || ""];
  for (const raw of langs) {
    const short = String(raw).slice(0, 2).toLowerCase();
    if (SUPPORTED_CODES.includes(short)) return short;
  }
  return FALLBACK;
}

async function loadLocale(code) {
  const r = await fetch(`/locales/${encodeURIComponent(code)}.json`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function serverLanguage() {
  try {
    const r = await fetch("/api/settings");
    if (!r.ok) return null;
    const body = await r.json();
    const wanted = body?.default_language;
    return SUPPORTED_CODES.includes(wanted) ? wanted : null;
  } catch (err) {
    console.warn("[i18n] could not read the configured language:", err);
    return null;
  }
}

export async function initI18n() {
  // The fallback bundle is always loaded so missing keys in a translated
  // locale don't render as English-shaped placeholders; they render as
  // proper English text.
  try {
    _fallbackStrings = await loadLocale(FALLBACK);
  } catch (err) {
    console.warn(`[i18n] fallback locale '${FALLBACK}' failed to load:`, err);
    _fallbackStrings = {};
  }

  // Config first, browser preference only when the config says "auto".
  const target = (await serverLanguage()) || detectBrowserLang();

  if (target === FALLBACK) {
    _strings = _fallbackStrings;
    _current = FALLBACK;
  } else {
    try {
      _strings = await loadLocale(target);
      _current = target;
    } catch (err) {
      console.warn(`[i18n] locale '${target}' failed, using '${FALLBACK}':`, err);
      _strings = _fallbackStrings;
      _current = FALLBACK;
    }
  }
  document.documentElement.lang = _current;
  try {
    localStorage.setItem(STORAGE_KEY, _current);
  } catch (_) { /* ignore — only the pre-paint hint is lost */ }
}

export function t(key, params) {
  let s = _strings[key];
  if (s == null) s = _fallbackStrings[key];
  if (s == null) s = key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      s = s.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
    }
  }
  return s;
}

export function getLang() {
  return _current;
}

export function getSupported() {
  return SUPPORTED.map((l) => ({ ...l }));
}

export async function setLang(code) {
  if (!SUPPORTED_CODES.includes(code) || code === _current) return false;
  try {
    _strings = code === FALLBACK ? _fallbackStrings : await loadLocale(code);
  } catch (err) {
    console.warn(`[i18n] setLang('${code}') failed:`, err);
    return false;
  }
  _current = code;
  document.documentElement.lang = code;
  // Cache for the pre-paint bootstrap in index.html, not a preference.
  try { localStorage.setItem(STORAGE_KEY, code); } catch (_) { /* ignore */ }
  for (const fn of _listeners) {
    try { fn(code); } catch (err) { console.error("[i18n] listener failed:", err); }
  }
  return true;
}

export function onLanguageChange(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}
