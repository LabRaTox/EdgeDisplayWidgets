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

const GITHUB_URL = "https://github.com/LabRaTox";
const KOFI_URL = "https://ko-fi.com/labratox";

// Third-party assets bundled into the dashboard, surfaced in the About → Credits
// list so attribution travels with the app.
const CREDITS = [
  { name: "Tabler Icons", url: "https://tabler.io/icons", license: "MIT", descKey: "settings.about.credits_icons" },
  { name: "emoji-picker-element", url: "https://github.com/nolanlawson/emoji-picker-element", license: "Apache-2.0", descKey: "settings.about.credits_emoji" },
];

// Cached app version from /api/config (shared across About-pane re-renders).
let _appVersion = null;
async function fetchAppVersion() {
  if (_appVersion != null) return _appVersion;
  try {
    const r = await fetch("/api/config");
    if (r.ok) _appVersion = (await r.json()).version || "";
  } catch (_err) {
    /* leave null; About pane falls back to a dash */
  }
  return _appVersion ?? "";
}

export function buildSettingsSheet(theme, { onEditLayout, standalone = false } = {}) {
  const sheet = document.createElement("div");
  sheet.id = "theme-sheet";
  sheet.hidden = true;
  if (standalone) sheet.classList.add("is-standalone");

  const tabsHtml = TAB_KEYS.map(
    (tab, i) =>
      `<button class="sheet-tab ${i === 0 ? "is-active" : ""}" data-tab="${tab.id}" type="button">${t(tab.labelKey)}</button>`,
  ).join("");

  const panesHtml = TAB_KEYS.map(
    (tab, i) =>
      `<div class="sheet-pane ${i === 0 ? "is-active" : ""}" data-pane="${tab.id}"></div>`,
  ).join("");

  // In the standalone window the panel already *is* the popout, so the
  // detach / open-in-window controls are pointless there.
  const popoutControls = standalone
    ? ""
    : `
        <button class="sheet-icon-btn sheet-detach" type="button"
                aria-label="${t("settings.popout.detach")}" title="${t("settings.popout.detach")}">⤢</button>
        <button class="sheet-icon-btn sheet-popout" type="button"
                aria-label="${t("settings.popout.window")}" title="${t("settings.popout.window")}">⧉</button>`;

  // Drag bar — only visible once the panel is detached (see CSS .is-floating).
  const dragbarHtml = standalone
    ? ""
    : `<div class="sheet-dragbar" data-bind="dragbar">
         <span class="sheet-dragbar-title">${t("settings.dialog_label")}</span>
         <span class="sheet-dragbar-grip" aria-hidden="true">⠿</span>
       </div>`;

  sheet.innerHTML = `
    <div class="sheet-backdrop"></div>
    <div class="sheet-panel" role="dialog" aria-label="${t("settings.dialog_label")}">
      ${dragbarHtml}
      <div class="sheet-header">
        <div class="sheet-tabs">${tabsHtml}</div>
        ${popoutControls}
        <button class="sheet-close" type="button" aria-label="${t("common.close")}">×</button>
      </div>
      <div class="sheet-body">${panesHtml}</div>
      <div class="sheet-toast" data-bind="toast" hidden></div>
    </div>
  `;
  document.body.appendChild(sheet);

  const $ = (sel) => sheet.querySelector(sel);
  const panel = $(".sheet-panel");

  const close = () => {
    if (standalone) {
      window.close();
      return;
    }
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

  // ---- Popout: detach into a floating, draggable panel -----------------
  if (!standalone) {
    const detachBtn = $(".sheet-detach");
    const dragbar = $('[data-bind="dragbar"]');

    // Keep a floating panel fully on-screen given its current size.
    const clampInto = (x, y) => {
      const maxX = Math.max(0, window.innerWidth - panel.offsetWidth);
      const maxY = Math.max(0, window.innerHeight - panel.offsetHeight);
      return [
        Math.min(Math.max(0, x), maxX),
        Math.min(Math.max(0, y), maxY),
      ];
    };

    const setFloating = (on) => {
      if (on) {
        // Measure the *docked* rect first, then switch to floating and pin the
        // panel to that spot (clamped) so it doesn't jump or land off-screen.
        const r = panel.getBoundingClientRect();
        sheet.classList.add("is-floating");
        detachBtn.classList.add("is-active");
        const [x, y] = clampInto(Math.round(r.left), Math.round(r.top));
        panel.style.left = `${x}px`;
        panel.style.top = `${y}px`;
      } else {
        sheet.classList.remove("is-floating");
        detachBtn.classList.remove("is-active");
        // Drop inline left/top/size so the bottom-anchored rules take over.
        panel.style.left = panel.style.top = panel.style.width = panel.style.height = "";
      }
    };
    detachBtn.addEventListener("click", () => setFloating(!sheet.classList.contains("is-floating")));

    // Drag the floating panel by its dedicated drag bar.
    dragbar.addEventListener("pointerdown", (e) => {
      if (!sheet.classList.contains("is-floating")) return;
      e.preventDefault();
      const r = panel.getBoundingClientRect();
      const offX = e.clientX - r.left;
      const offY = e.clientY - r.top;
      dragbar.setPointerCapture(e.pointerId);
      dragbar.classList.add("is-grabbing");
      const onMove = (ev) => {
        const [x, y] = clampInto(ev.clientX - offX, ev.clientY - offY);
        panel.style.left = `${x}px`;
        panel.style.top = `${y}px`;
      };
      const onUp = () => {
        dragbar.classList.remove("is-grabbing");
        dragbar.removeEventListener("pointermove", onMove);
        dragbar.removeEventListener("pointerup", onUp);
        dragbar.removeEventListener("pointercancel", onUp);
      };
      dragbar.addEventListener("pointermove", onMove);
      dragbar.addEventListener("pointerup", onUp);
      dragbar.addEventListener("pointercancel", onUp);
    });

    // If the viewport shrinks, pull a floating panel back into view.
    window.addEventListener("resize", () => {
      if (!sheet.classList.contains("is-floating") || !panel.style.left) return;
      const [x, y] = clampInto(parseInt(panel.style.left, 10) || 0, parseInt(panel.style.top, 10) || 0);
      panel.style.left = `${x}px`;
      panel.style.top = `${y}px`;
    });

    // ---- Popout: open settings in a separate browser window ----------
    $(".sheet-popout").addEventListener("click", () => {
      const w = Math.min(820, window.screen.availWidth);
      const h = Math.min(720, window.screen.availHeight);
      window.open(
        "/settings.html",
        "edge-settings",
        `width=${w},height=${h},menubar=no,toolbar=no,location=no,status=no`,
      );
      close();
    });
  }

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
  let _moduleSchemas = null; // per-module editable-field schema (fetched once)

  // --- schema-driven module fields (see backend SettingField) -------------
  // Attribute-safe escaping for interpolated values.
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");

  const getDotted = (obj, key) =>
    key.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);

  const setDotted = (obj, key, value) => {
    const parts = key.split(".");
    let cur = obj;
    for (let i = 0; i < parts.length - 1; i++) {
      cur[parts[i]] = cur[parts[i]] || {};
      cur = cur[parts[i]];
    }
    cur[parts.at(-1)] = value;
  };

  function schemaFieldHtml(name, f, mc) {
    const val = getDotted(mc, f.key);
    const attrs =
      `data-module="${name}" data-key="${esc(f.key)}" data-type="${f.type}"` +
      (f.secret ? ' data-secret="1"' : "");
    const help = f.help_key
      ? `<span class="hint field-help">${esc(t(f.help_key))}</span>`
      : "";
    let control;
    if (f.secret) {
      // Backend sends "***" when a secret is stored, "" when not. We never
      // echo the real value; an empty submit means "keep the stored one".
      const ph = val === "***" ? t("settings.secret.set") : t("settings.secret.empty");
      control = `<input type="password" autocomplete="off" ${attrs} value="" placeholder="${esc(ph)}">`;
    } else if (f.type === "bool") {
      control = `<input type="checkbox" ${attrs} ${val ? "checked" : ""}>`;
    } else if (f.type === "int" || f.type === "float") {
      const step = f.step ?? (f.type === "int" ? 1 : "any");
      const min = f.min != null ? `min="${f.min}"` : "";
      const max = f.max != null ? `max="${f.max}"` : "";
      control = `<input type="number" ${min} ${max} step="${step}" ${attrs} value="${val ?? ""}" placeholder="${f.default ?? ""}">`;
    } else if (f.type === "select") {
      const opts = (f.options || [])
        .map((o) => `<option value="${esc(o)}" ${String(val) === o ? "selected" : ""}>${esc(o)}</option>`)
        .join("");
      control = `<select ${attrs}>${opts}</select>`;
    } else if (f.type === "list") {
      const lines = Array.isArray(val) ? val.join("\n") : "";
      control = `<textarea rows="2" ${attrs} placeholder="${esc(t("settings.list.placeholder"))}">${esc(lines)}</textarea>`;
    } else {
      control = `<input type="text" ${attrs} value="${esc(val ?? "")}">`;
    }
    const cls = f.type === "bool" ? "settings-field field-inline" : "settings-field";
    return `<label class="${cls}"><span>${esc(t(f.label_key))}</span>${control}${help}</label>`;
  }

  function schemaFieldsHtml(name, mc) {
    const fields = (_moduleSchemas || {})[name] || [];
    if (!fields.length) return "";
    let lastGroup = null;
    const parts = [];
    for (const f of fields) {
      if (f.group_key && f.group_key !== lastGroup) {
        parts.push(`<div class="field-group-title">${esc(t(f.group_key))}</div>`);
        lastGroup = f.group_key;
      }
      parts.push(schemaFieldHtml(name, f, mc));
    }
    return `<div class="module-settings">${parts.join("")}</div>`;
  }

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
            <div class="module-head">
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
            ${schemaFieldsHtml(name, mc)}
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
    const ensure = (name) => (updates[name] = updates[name] || {});
    // Common enabled / interval controls.
    for (const inp of root.querySelectorAll("[data-field]")) {
      const name = inp.dataset.module;
      ensure(name);
      if (inp.dataset.field === "enabled") {
        updates[name].enabled = inp.checked;
      } else if (inp.dataset.field === "interval") {
        const v = inp.value.trim();
        updates[name].interval = v === "" ? null : Number(v);
      }
    }
    // Schema-driven, module-specific fields.
    for (const inp of root.querySelectorAll("[data-key]")) {
      const name = inp.dataset.module;
      const key = inp.dataset.key;
      const type = inp.dataset.type;
      let value;
      if (inp.dataset.secret === "1") {
        const typed = inp.value.trim();
        value = typed === "" ? "***" : typed; // "***" ⇒ keep stored secret
      } else if (type === "bool") {
        value = inp.checked;
      } else if (type === "int" || type === "float") {
        const v = inp.value.trim();
        if (v === "") continue; // empty number ⇒ leave as-is (avoid writing null)
        value = type === "int" ? parseInt(v, 10) : parseFloat(v);
        if (Number.isNaN(value)) continue;
      } else if (type === "list") {
        value = inp.value.split("\n").map((s) => s.trim()).filter(Boolean);
      } else {
        value = inp.value.trim();
      }
      setDotted(ensure(name), key, value);
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

  let _qaEditor = null;
  const renderActionsPane = () => {
    const root = $('[data-pane="actions"]');
    // The editor manages its own load/save lifecycle and reads its data
    // from a dedicated endpoint (full action data, unscrubbed). Mount it
    // exactly once; on later opens, ask it to re-sync with the on-disk config
    // (so positions changed via the widget's edit mode aren't overwritten by a
    // stale buffer) — it keeps any unsaved edits.
    if (_qaEditor) {
      _qaEditor.reload?.();
      return;
    }
    _qaEditor = mountQuickActionsEditor(root, { flashToast });
  };

  const renderAboutPane = () => {
    const root = $('[data-pane="about"]');
    const creditsHtml = CREDITS.map(
      (c) => `
        <li class="about-credit">
          <a href="${c.url}" target="_blank" rel="noopener noreferrer">${c.name}</a>
          <span class="about-credit-desc">${t(c.descKey)}</span>
          <span class="about-credit-license">${c.license}</span>
        </li>`,
    ).join("");
    root.innerHTML = `
      <div class="about-pane">
        <h3 class="about-title">Edge Dashboard</h3>
        <div class="about-version" data-bind="version">${t("settings.about.version", { version: _appVersion ?? "…" })}</div>
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
        <div class="about-credits">
          <div class="about-credits-title">${t("settings.about.credits")}</div>
          <ul class="about-credits-list">${creditsHtml}</ul>
        </div>
      </div>
    `;
    // Fill in the version once /api/config resolves (works for both the
    // embedded sheet and the standalone settings window).
    fetchAppVersion().then((v) => {
      const el = root.querySelector('[data-bind="version"]');
      if (el) el.textContent = t("settings.about.version", { version: v || "—" });
    });
  };

  const renderLayoutPane = () => {
    const root = $('[data-pane="layout"]');
    if (standalone || !onEditLayout) {
      // Layout editing manipulates the live dashboard DOM, which the
      // standalone settings window doesn't host.
      root.innerHTML = `
        <p class="settings-help">${t("settings.layout.help")}</p>
        <div class="settings-empty">${t("settings.layout.display_only")}</div>
      `;
      return;
    }
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
    if (_moduleSchemas === null) {
      // Static for a build, so fetch once and cache across sheet reopens.
      try {
        const r = await fetch("/api/modules/schema");
        if (r.ok) _moduleSchemas = (await r.json()).modules || {};
      } catch (err) {
        console.warn("[settings] /api/modules/schema failed:", err);
        _moduleSchemas = {};
      }
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
