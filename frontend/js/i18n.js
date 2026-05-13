// Tiny i18n: flat key lookup with {placeholder} substitution.
//
// Language is auto-detected from navigator.languages on first load (falls
// back to English). The user can override via the Settings sheet; the choice
// persists in localStorage. Locale JSON lives in /locales/<code>.json and
// is fetched at init — adding a new language = drop a JSON file + extend
// SUPPORTED below.

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

  let stored = null;
  try { stored = localStorage.getItem(STORAGE_KEY); } catch (_) { /* private mode */ }
  const target = (stored && SUPPORTED_CODES.includes(stored))
    ? stored
    : detectBrowserLang();

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
