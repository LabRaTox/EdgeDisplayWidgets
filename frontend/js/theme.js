// Theme manager: swaps the <link id="theme-link"> href and persists to
// localStorage. The list of themes is fetched from /api/themes (auto-
// discovered by the backend from frontend/css/themes/*.css), so adding a
// theme = drop a CSS file. No code changes anywhere.

import { mountQuickActionsEditor } from "./settings/quick_actions_editor.js";
import { t, getLang, getSupported, setLang, onLanguageChange } from "./i18n.js";

const STORAGE_KEY = "edge-dashboard.theme";
const FALLBACK_THEMES = ["cyberpunk", "clean", "steampunk", "light"];

export class ThemeManager {
  constructor() {
    this.themes = [];
    this.current = this._readStored() || "cyberpunk";
    this._link = document.getElementById("theme-link");
  }

  async init(defaultTheme) {
    try {
      const r = await fetch("/api/themes");
      if (r.ok) {
        const body = await r.json();
        this.themes = body.themes || [];
        if (!this._readStored() && body.default) {
          this.current = body.default;
        }
      }
    } catch (err) {
      console.warn("[theme] /api/themes failed:", err);
    }
    if (this.themes.length === 0) this.themes = [...FALLBACK_THEMES];
    if (!this.themes.includes(this.current)) {
      this.current = defaultTheme || this.themes[0];
    }
    this.apply(this.current, { persist: false });
  }

  apply(name, { persist = true } = {}) {
    if (!name) return;
    if (this._link) {
      this._link.href = `/css/themes/${encodeURIComponent(name)}.css`;
    }
    document.documentElement.dataset.theme = name;
    document.body.dataset.theme = name;
    this.current = name;
    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, name);
      } catch (_err) {
        /* localStorage may be unavailable in private browsing */
      }
    }
  }

  next() {
    const i = this.themes.indexOf(this.current);
    const j = (i + 1) % this.themes.length;
    this.apply(this.themes[j]);
  }

  _readStored() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (_err) {
      return null;
    }
  }
}

// ---------------------------------------------------------------- Settings sheet
//
// Three tabs in a single bottom-anchored modal:
//   • Design      — theme picker (uses ThemeManager)
//   • Module      — toggle modules + interval
//   • Wetter      — location name, lat/lon, units
//
// On save, the Module + Wetter tabs POST a partial settings object to
// /api/settings; the backend persists it to config.local.yaml and hot-
// reloads the hub (no restart).

const TAB_KEYS = [
  { id: "theme", labelKey: "settings.tab.theme" },
  { id: "modules", labelKey: "settings.tab.modules" },
  { id: "weather", labelKey: "settings.tab.weather" },
  { id: "youtube", labelKey: "settings.tab.youtube" },
  { id: "actions", labelKey: "settings.tab.actions" },
  { id: "layout", labelKey: "settings.tab.layout" },
  { id: "about", labelKey: "settings.tab.about" },
];

const APP_VERSION = "1.0.0";
const GITHUB_URL = "https://github.com/LabRaTox";
const KOFI_URL = "https://ko-fi.com/labratox";

export function buildSettingsSheet(theme, { onEditLayout } = {}) {
  const sheet = document.createElement("div");
  sheet.id = "theme-sheet";
  sheet.hidden = true;

  const tabsHtml = TAB_KEYS.map(
    (tab, i) =>
      `<button class="sheet-tab ${i === 0 ? "is-active" : ""}" data-tab="${tab.id}" type="button">${t(tab.labelKey)}</button>`,
  ).join("");

  const panesHtml = TAB_KEYS.map(
    (tab, i) =>
      `<div class="sheet-pane ${i === 0 ? "is-active" : ""}" data-pane="${tab.id}"></div>`,
  ).join("");

  sheet.innerHTML = `
    <div class="sheet-backdrop"></div>
    <div class="sheet-panel" role="dialog" aria-label="${t("settings.dialog_label")}">
      <div class="sheet-header">
        <div class="sheet-tabs">${tabsHtml}</div>
        <button class="sheet-close" type="button" aria-label="${t("common.close")}">×</button>
      </div>
      <div class="sheet-body">${panesHtml}</div>
      <div class="sheet-toast" data-bind="toast" hidden></div>
    </div>
  `;
  document.body.appendChild(sheet);

  const $ = (sel) => sheet.querySelector(sel);
  const close = () => {
    sheet.classList.remove("is-open");
    setTimeout(() => {
      sheet.hidden = true;
    }, 200);
  };
  const open = async () => {
    await refresh();
    sheet.hidden = false;
    requestAnimationFrame(() => sheet.classList.add("is-open"));
  };

  const setActiveTab = (id) => {
    for (const btn of sheet.querySelectorAll(".sheet-tab")) {
      btn.classList.toggle("is-active", btn.dataset.tab === id);
    }
    for (const pane of sheet.querySelectorAll(".sheet-pane")) {
      pane.classList.toggle("is-active", pane.dataset.pane === id);
    }
  };

  for (const btn of sheet.querySelectorAll(".sheet-tab")) {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
  }
  $(".sheet-close").addEventListener("click", close);
  $(".sheet-backdrop").addEventListener("click", close);

  // When the language changes, refresh the static labels that were baked
  // into the sheet markup. Active-pane content is re-rendered via refresh()
  // on the next open or by the language picker itself.
  onLanguageChange(() => {
    const panel = sheet.querySelector(".sheet-panel");
    if (panel) panel.setAttribute("aria-label", t("settings.dialog_label"));
    const closeBtn = sheet.querySelector(".sheet-close");
    if (closeBtn) closeBtn.setAttribute("aria-label", t("common.close"));
    for (const btn of sheet.querySelectorAll(".sheet-tab")) {
      const tab = TAB_KEYS.find((x) => x.id === btn.dataset.tab);
      if (tab) btn.textContent = t(tab.labelKey);
    }
  });

  const toast = $('[data-bind="toast"]');
  const flashToast = (msg, isError = false) => {
    toast.textContent = msg;
    toast.classList.toggle("is-error", !!isError);
    toast.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      toast.hidden = true;
    }, 2400);
  };

  // ---------------------------------------------------------------- panes

  const renderThemePane = () => {
    const root = $('[data-pane="theme"]');
    root.innerHTML = `
      <div class="theme-options"></div>
      <div class="settings-section">
        <div class="settings-section-title">${t("settings.language.section")}</div>
        <div class="lang-options"></div>
        <div class="settings-hint">${t("settings.language.hint")}</div>
      </div>
    `;
    const options = root.querySelector(".theme-options");
    for (const name of theme.themes) {
      const btn = document.createElement("button");
      btn.className = "theme-option";
      btn.type = "button";
      btn.dataset.theme = name;
      btn.innerHTML = `
        <span class="theme-swatch theme-swatch-${name}"></span>
        <span class="theme-label">${name}</span>
      `;
      if (name === theme.current) btn.classList.add("active");
      btn.addEventListener("click", () => {
        theme.apply(name);
        for (const b of options.children) b.classList.remove("active");
        btn.classList.add("active");
      });
      options.appendChild(btn);
    }

    const langOpts = root.querySelector(".lang-options");
    const currentLang = getLang();
    for (const lang of getSupported()) {
      const btn = document.createElement("button");
      btn.className = "lang-option";
      btn.type = "button";
      btn.dataset.lang = lang.code;
      btn.textContent = lang.label;
      if (lang.code === currentLang) btn.classList.add("active");
      btn.addEventListener("click", async () => {
        const ok = await setLang(lang.code);
        if (!ok) return;
        // i18n's onLanguageChange listeners (incl. renderPages in app.js)
        // fire automatically; refresh in-place so the open sheet reflects
        // the new locale immediately.
        for (const b of langOpts.children) b.classList.remove("active");
        btn.classList.add("active");
        await refresh();
      });
      langOpts.appendChild(btn);
    }
  };

  let _settings = null; // last fetched

  const renderModulesPane = () => {
    const root = $('[data-pane="modules"]');
    if (!_settings) {
      root.innerHTML = `<div class="settings-empty">${t("common.loading")}</div>`;
      return;
    }
    const intervalLbl = t("settings.modules.interval");
    const intervalUnit = t("settings.modules.interval_unit");
    const rows = Object.entries(_settings.modules)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, mc]) => {
        const interval = mc.interval ?? "";
        const checked = mc.enabled ? "checked" : "";
        return `
          <div class="module-row">
            <label class="module-toggle">
              <input type="checkbox" data-module="${name}" data-field="enabled" ${checked}>
              <span class="module-name">${name}</span>
            </label>
            <label class="module-interval">
              <span class="hint">${intervalLbl}</span>
              <input type="number" min="0.05" step="0.05"
                     data-module="${name}" data-field="interval"
                     value="${interval}" placeholder="default">
              <span class="unit">${intervalUnit}</span>
            </label>
          </div>
        `;
      })
      .join("");
    root.innerHTML = `
      <div class="modules-list">${rows}</div>
      <div class="settings-actions">
        <button class="btn btn-primary" data-save="modules" type="button">${t("common.save")}</button>
      </div>
    `;
    root.querySelector('[data-save="modules"]').addEventListener("click", saveModules);
  };

  const renderWeatherPane = () => {
    const root = $('[data-pane="weather"]');
    if (!_settings) {
      root.innerHTML = `<div class="settings-empty">${t("common.loading")}</div>`;
      return;
    }
    const w = _settings.modules.weather || {};
    const units = w.units || "metric";
    root.innerHTML = `
      <form class="weather-form" onsubmit="return false">
        <label class="settings-field">
          <span>${t("settings.weather.location_name")}</span>
          <input type="text" data-field="name" value="${(w.name || "").replace(/"/g, "&quot;")}">
        </label>
        <div class="settings-row">
          <label class="settings-field">
            <span>${t("settings.weather.latitude")}</span>
            <input type="number" step="0.0001" data-field="lat" value="${w.lat ?? ""}">
          </label>
          <label class="settings-field">
            <span>${t("settings.weather.longitude")}</span>
            <input type="number" step="0.0001" data-field="lon" value="${w.lon ?? ""}">
          </label>
        </div>
        <label class="settings-field">
          <span>${t("settings.weather.unit")}</span>
          <select data-field="units">
            <option value="metric"   ${units === "metric" ? "selected" : ""}>${t("settings.weather.unit_metric")}</option>
            <option value="imperial" ${units === "imperial" ? "selected" : ""}>${t("settings.weather.unit_imperial")}</option>
          </select>
        </label>
      </form>
      <div class="settings-actions">
        <button class="btn btn-primary" data-save="weather" type="button">${t("common.save")}</button>
      </div>
    `;
    root.querySelector('[data-save="weather"]').addEventListener("click", saveWeather);
  };

  // ---------------------------------------------------------------- save handlers

  async function postSettings(payload) {
    const r = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`HTTP ${r.status}: ${text}`);
    }
    const body = await r.json();
    _settings = body.settings;
    return body;
  }

  async function saveModules() {
    const root = $('[data-pane="modules"]');
    const updates = {};
    for (const inp of root.querySelectorAll("[data-module]")) {
      const name = inp.dataset.module;
      const field = inp.dataset.field;
      updates[name] = updates[name] || {};
      if (field === "enabled") {
        updates[name].enabled = inp.checked;
      } else if (field === "interval") {
        const v = inp.value.trim();
        updates[name].interval = v === "" ? null : Number(v);
      }
    }
    try {
      await postSettings({ modules: updates });
      flashToast(t("settings.modules.saved"));
      renderModulesPane();
    } catch (err) {
      console.error("[settings] save modules failed:", err);
      flashToast(t("common.save_failed"), true);
    }
  }

  async function saveWeather() {
    const root = $('[data-pane="weather"]');
    const get = (sel) => root.querySelector(sel);
    const updates = {
      weather: {
        name: get('[data-field="name"]').value.trim(),
        lat: parseFloat(get('[data-field="lat"]').value),
        lon: parseFloat(get('[data-field="lon"]').value),
        units: get('[data-field="units"]').value,
      },
    };
    if (!Number.isFinite(updates.weather.lat) || !Number.isFinite(updates.weather.lon)) {
      flashToast(t("settings.weather.lat_lon_invalid"), true);
      return;
    }
    try {
      await postSettings({ modules: updates });
      flashToast(t("settings.weather.saved"));
    } catch (err) {
      console.error("[settings] save weather failed:", err);
      flashToast(t("common.save_failed"), true);
    }
  }

  const renderYoutubePane = () => {
    const root = $('[data-pane="youtube"]');
    if (!_settings) {
      root.innerHTML = `<div class="settings-empty">${t("common.loading")}</div>`;
      return;
    }
    const yt = _settings.modules.youtube || { entries: [] };
    const entries = Array.isArray(yt.entries) ? yt.entries : [];
    const lines = entries
      .map((e) =>
        typeof e === "string"
          ? e
          : e?.url || (e?.kind && e?.id ? `${e.kind}:${e.id}` : ""),
      )
      .filter(Boolean)
      .join("\n");
    root.innerHTML = `
      <p class="settings-help">${t("settings.youtube.help")}</p>
      <label class="settings-field">
        <textarea data-field="entries" rows="8" class="yt-entries"
          placeholder="https://www.youtube.com/watch?v=…"
        >${(lines).replace(/</g, "&lt;")}</textarea>
      </label>
      <div class="settings-actions">
        <button class="btn btn-primary" data-save="youtube" type="button">${t("common.save")}</button>
      </div>
    `;
    root.querySelector('[data-save="youtube"]').addEventListener("click", saveYoutube);
  };

  async function saveYoutube() {
    const root = $('[data-pane="youtube"]');
    const text = root.querySelector('[data-field="entries"]').value;
    const entries = text
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      await postSettings({ modules: { youtube: { entries } } });
      flashToast(t("settings.youtube.saved"));
    } catch (err) {
      console.error("[settings] save youtube failed:", err);
      flashToast(t("common.save_failed"), true);
    }
  }

  let _qaMounted = false;
  const renderActionsPane = () => {
    const root = $('[data-pane="actions"]');
    // The editor manages its own load/save lifecycle and reads its data
    // from a dedicated endpoint (full action data, unscrubbed). Mount it
    // exactly once; the sheet keeps it in the DOM between opens.
    if (_qaMounted) return;
    _qaMounted = true;
    mountQuickActionsEditor(root, { flashToast });
  };

  const renderAboutPane = () => {
    const root = $('[data-pane="about"]');
    root.innerHTML = `
      <div class="about-pane">
        <h3 class="about-title">Edge Dashboard</h3>
        <div class="about-version">${t("settings.about.version", { version: APP_VERSION })}</div>
        <p class="about-desc">${t("settings.about.description")}</p>
        <div class="about-links">
          <a class="about-link about-github" href="${GITHUB_URL}" target="_blank" rel="noopener noreferrer">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M12 .5a11.5 11.5 0 0 0-3.63 22.41c.57.1.78-.25.78-.55v-2.1c-3.2.7-3.87-1.36-3.87-1.36-.53-1.34-1.3-1.7-1.3-1.7-1.06-.72.08-.71.08-.71 1.17.08 1.79 1.2 1.79 1.2 1.04 1.78 2.73 1.27 3.4.97.1-.76.4-1.27.74-1.56-2.55-.29-5.24-1.27-5.24-5.66 0-1.25.45-2.27 1.18-3.07-.12-.29-.51-1.45.11-3.02 0 0 .96-.31 3.15 1.17a10.95 10.95 0 0 1 5.74 0c2.19-1.48 3.15-1.17 3.15-1.17.63 1.57.23 2.73.11 3.02.74.8 1.18 1.82 1.18 3.07 0 4.4-2.69 5.36-5.25 5.65.41.36.78 1.06.78 2.13v3.16c0 .3.21.66.79.55A11.5 11.5 0 0 0 12 .5z"/></svg>
            <span>${t("settings.about.github")}</span>
          </a>
          <a class="about-link about-kofi" href="${KOFI_URL}" target="_blank" rel="noopener noreferrer">
            <span class="about-link-icon" aria-hidden="true">☕</span>
            <span>${t("settings.about.kofi")}</span>
          </a>
        </div>
      </div>
    `;
  };

  const renderLayoutPane = () => {
    const root = $('[data-pane="layout"]');
    root.innerHTML = `
      <p class="settings-help">${t("settings.layout.help")}</p>
      <div class="settings-actions">
        <button class="btn btn-primary" type="button" data-act="edit-layout">${t("settings.layout.enter")}</button>
      </div>
    `;
    root.querySelector('[data-act="edit-layout"]').addEventListener("click", () => {
      close();
      onEditLayout?.();
    });
  };

  async function refresh() {
    try {
      const r = await fetch("/api/settings");
      if (r.ok) _settings = await r.json();
    } catch (err) {
      console.warn("[settings] /api/settings failed:", err);
    }
    renderThemePane();
    renderModulesPane();
    renderWeatherPane();
    renderYoutubePane();
    renderActionsPane();
    renderLayoutPane();
    renderAboutPane();
  }

  return { open, close, sheet };
}
