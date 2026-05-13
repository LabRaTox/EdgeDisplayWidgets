// Bootstrap: fetch /api/config, dynamic-import widget files referenced by
// every page, mount instances per page into CSS-Grid layouts, route WS
// frames to all matching instances, wire swiper + theme switcher.

import { getWidget } from "./registry.js";
import { WSClient } from "./ws.js";
import { PageSwiper, attachLongPress, attachSwipeFromBottom } from "./swiper.js";
import { ThemeManager, buildSettingsSheet } from "./theme.js";
import { LayoutEditor } from "./layout_editor.js";
import { initI18n, t, onLanguageChange } from "./i18n.js";

async function fetchConfig() {
  const res = await fetch("/api/config");
  if (!res.ok) throw new Error(`/api/config failed: ${res.status}`);
  return res.json();
}

async function loadWidgetFiles(ids) {
  const unique = [...new Set(ids)];
  await Promise.all(
    unique.map(async (id) => {
      try {
        await import(`./widgets/${id}.js`);
      } catch (err) {
        console.error(`[app] widget '${id}' failed to load:`, err);
      }
    }),
  );
}

function buildPage(pageCfg) {
  const el = document.createElement("section");
  el.className = "page";
  el.dataset.pageId = pageCfg.id;
  el.style.gridTemplateColumns = pageCfg.grid.columns;
  el.style.gridTemplateRows = pageCfg.grid.rows;
  if (pageCfg.grid.areas?.length) {
    el.style.gridTemplateAreas = pageCfg.grid.areas
      .map((row) => `"${row}"`)
      .join(" ");
  }
  return el;
}

function applyPlacement(wEl, p) {
  // `gridArea` is the catch-all shorthand for gridRow/Column-Start/End.
  // Setting it to "" clears ALL four longhands — so we have to do the reset
  // BEFORE writing the new values, never after.
  wEl.style.gridArea = "";
  if (Number.isFinite(p.col) && Number.isFinite(p.row)) {
    wEl.style.gridColumn = `${p.col} / span ${p.colspan || 1}`;
    wEl.style.gridRow = `${p.row} / span ${p.rowspan || 1}`;
  } else if (p.area) {
    wEl.style.gridArea = p.area;
  }
}

async function bootstrap() {
  // i18n and config can resolve in parallel — both are tiny HTTP fetches.
  const [cfg] = await Promise.all([fetchConfig(), initI18n()]);

  const theme = new ThemeManager();
  await theme.init(cfg.default_theme);

  // Live-update aria-labels and re-render widgets when the user switches
  // language so labels picked up at mount time get refreshed.
  onLanguageChange(() => {
    document.getElementById("dots")?.setAttribute("aria-label", t("app.pages_nav_label"));
    renderPages();
  });

  // Mutable application state, kept in sync with the host.
  let pages = cfg.pages;
  const allInstances = []; // { id, inst, modules, el, placement }
  let editor = null;
  const lastByModule = new Map();

  const pagesRoot = document.getElementById("pages");

  function replayCachedDataTo(inst, modules) {
    for (const mod of modules) {
      const cached = lastByModule.get(mod);
      if (!cached) continue;
      try {
        inst.update(cached.data, mod, cached.ts);
      } catch (err) {
        console.error(`[app] replay update failed for '${mod}':`, err);
      }
    }
  }

  function mountSingleWidget(pageEl, placement) {
    const Cls = getWidget(placement.id);
    if (!Cls) {
      console.warn(`[app] no widget class for '${placement.id}'`);
      return null;
    }
    const wEl = document.createElement("div");
    wEl.className = `widget widget-${placement.id}`;
    applyPlacement(wEl, placement);
    if (placement.variant) wEl.dataset.variant = placement.variant;
    pageEl.appendChild(wEl);

    let inst;
    try {
      inst = new Cls();
      inst.mount(wEl, null, {
        id: placement.id,
        variant: placement.variant,
        options: placement.options || {},
      });
    } catch (err) {
      console.error(`[app] widget '${placement.id}' mount failed:`, err);
      wEl.textContent = t("app.widget_failed", { id: placement.id });
      return null;
    }
    const modules = Cls.modules || [];
    const entry = { id: placement.id, inst, modules, el: wEl, placement };
    allInstances.push(entry);
    replayCachedDataTo(inst, modules);
    return entry;
  }

  function unmountSingleWidget(wEl) {
    const idx = allInstances.findIndex((e) => e.el === wEl);
    if (idx >= 0) {
      const entry = allInstances[idx];
      try {
        entry.inst.destroy?.();
      } catch (err) {
        console.warn(`[app] destroy failed for '${entry.id}':`, err);
      }
      allInstances.splice(idx, 1);
    }
    wEl.remove();
  }

  function renderPages() {
    // Tear down everything cleanly so widgets get to release timers/observers
    while (allInstances.length) {
      const entry = allInstances.pop();
      try {
        entry.inst.destroy?.();
      } catch (_) { /* noop */ }
    }
    pagesRoot.innerHTML = "";
    const widgetIds = pages.flatMap((p) => p.widgets.map((w) => w.id));
    loadWidgetFiles(widgetIds);
    for (const pageCfg of pages) {
      const pageEl = buildPage(pageCfg);
      pagesRoot.appendChild(pageEl);
      for (const placement of pageCfg.widgets) {
        mountSingleWidget(pageEl, placement);
      }
    }
    if (editor?.active) editor.refreshHandles();
  }

  // First render needs widget JS to be loaded so mountSingleWidget can resolve classes.
  await loadWidgetFiles(pages.flatMap((p) => p.widgets.map((w) => w.id)));
  renderPages();

  const swiper = new PageSwiper(pagesRoot);

  const sheet = buildSettingsSheet(theme, {
    onEditLayout: () => editor?.enter(),
  });

  editor = new LayoutEditor({
    pagesRoot,
    swiper,
    getPages: () => pages,
    setPages: (next) => {
      pages = next;
      renderPages();
      dotButtons = buildIndicator();
    },
    mountWidget: (pageEl, placement) => mountSingleWidget(pageEl, placement)?.el ?? null,
    unmountWidget: (wEl) => unmountSingleWidget(wEl),
    onSave: async (newPages) => {
      const r = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pages: newPages }),
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(`HTTP ${r.status}: ${text}`);
      }
      // Use the POST response directly — avoids a second GET that the browser
      // might serve from cache. The server-rendered shape includes all the
      // Pydantic-filled defaults (col/row/colspan/rowspan, options, etc.).
      const body = await r.json();
      if (Array.isArray(body?.settings?.pages)) {
        pages = body.settings.pages;
        renderPages();
      } else {
        console.warn("[app] settings response missing pages:", body);
      }
    },
  });

  // Swipe up from the bottom edge to open settings — touch-friendly
  // shortcut for kiosk use. We attach the gesture to a dedicated invisible
  // hotspot strip rather than `document.body` because on touch devices the
  // browser claims vertical pans on regular elements (via touch-action:
  // auto) and fires pointercancel before our handler sees enough motion.
  // touch-action: none on the hotspot opts the strip out of that.
  const hotspot = document.createElement("div");
  hotspot.id = "swipe-hotspot";
  hotspot.setAttribute("aria-hidden", "true");
  document.body.appendChild(hotspot);
  attachSwipeFromBottom(hotspot, () => sheet.open());

  const dotsRoot = document.getElementById("dots");
  dotsRoot.setAttribute("aria-label", t("app.pages_nav_label"));
  function buildIndicator() {
    dotsRoot.innerHTML = "";
    const buttons = [];
    pages.forEach((p, i) => {
      const btn = document.createElement("button");
      btn.className = "dot";
      btn.type = "button";
      btn.setAttribute("aria-label", p.title || p.id);
      if (i === swiper.activeIndex) btn.classList.add("active");
      dotsRoot.appendChild(btn);
      buttons.push(btn);
      attachLongPress(btn, {
        onClick: () => swiper.goTo(i),
        onLongPress: () => sheet.open(),
      });
    });
    return buttons;
  }
  let dotButtons = buildIndicator();
  swiper.addEventListener("pagechange", (e) => {
    dotButtons.forEach((b, i) => b.classList.toggle("active", i === e.detail));
  });

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WSClient(`${proto}//${location.host}/ws`);
  ws.addEventListener("message", (event) => {
    const { module, data, ts } = event.detail;
    lastByModule.set(module, { data, ts });
    for (const { inst, modules } of allInstances) {
      if (!modules.includes(module)) continue;
      try {
        inst.update(data, module, ts);
      } catch (err) {
        console.error(`[app] update failed for '${module}':`, err);
      }
    }
  });
}

bootstrap().catch((err) => {
  console.error("[app] bootstrap failed:", err);
  // i18n may not be initialised yet, so t() falls back to the key. Use a
  // bilingual literal so the error is readable either way.
  document.body.textContent =
    "Dashboard failed to start — see console. / Dashboard konnte nicht gestartet werden — siehe Konsole.";
});
