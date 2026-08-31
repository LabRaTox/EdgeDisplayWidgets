// Theme manager: swaps the <link id="theme-link"> href to the theme the
// backend says to use. The list of themes is fetched from /api/themes
// (auto-discovered by the backend from frontend/css/themes/*.css), so adding a
// theme = drop a CSS file. No code changes anywhere.
//
// The backend is the authority, not this device. That is a change from when
// the dashboard configured itself: the settings live in their own window now —
// a separate application with a separate browser profile, which cannot reach
// into this one's localStorage. So the theme travels through the config, where
// every client sees the same value, and localStorage is kept purely as a
// cache so index.html can paint the right theme before the first response
// arrives.

const STORAGE_KEY = "edge-dashboard.theme";
const FALLBACK_THEMES = ["cyberpunk", "clean", "steampunk", "light"];

export class ThemeManager {
  constructor() {
    this.themes = [];
    this.current = null;
    this._link = document.getElementById("theme-link");
  }

  async init(defaultTheme) {
    let wanted = defaultTheme || this._readCached();
    try {
      const r = await fetch("/api/themes");
      if (r.ok) {
        const body = await r.json();
        this.themes = body.themes || [];
        if (body.default) wanted = body.default;
      }
    } catch (err) {
      console.warn("[theme] /api/themes failed:", err);
    }
    if (this.themes.length === 0) this.themes = [...FALLBACK_THEMES];
    if (!wanted || !this.themes.includes(wanted)) wanted = this.themes[0];
    this.apply(wanted);
  }

  apply(name) {
    if (!name || name === this.current) return;
    if (this._link) {
      this._link.href = `/css/themes/${encodeURIComponent(name)}.css`;
    }
    document.documentElement.dataset.theme = name;
    document.body.dataset.theme = name;
    this.current = name;
    try {
      localStorage.setItem(STORAGE_KEY, name);
    } catch (_err) {
      /* storage unavailable — the theme still applies for this session */
    }
  }

  _readCached() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (_err) {
      return null;
    }
  }
}
