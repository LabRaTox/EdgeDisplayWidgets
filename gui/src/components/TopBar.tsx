import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import i18n, { LANGUAGE_LABELS, SUPPORTED_LANGUAGES, setLanguage } from "../i18n";
import type { Language } from "../i18n";
import { useStore } from "../store";
import type { View } from "../types";
import { Wordmark } from "./Wordmark";

const VIEWS: { id: View; labelKey: string }[] = [
  { id: "theme", labelKey: "nav.theme" },
  { id: "modules", labelKey: "nav.modules" },
  { id: "weather", labelKey: "nav.weather" },
  { id: "youtube", labelKey: "nav.youtube" },
  { id: "actions", labelKey: "nav.actions" },
  { id: "layout", labelKey: "nav.layout" },
  { id: "system", labelKey: "nav.system" },
  { id: "about", labelKey: "nav.about" },
];

/**
 * A menu that behaves like a menu bar: click to open, click anywhere else to
 * close, Escape closes. Built here rather than through Tauri's native menu
 * API so it renders identically when the same UI is opened in a browser tab
 * during development.
 */
function Menu({
  label,
  children,
}: {
  label: string;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className={`menu ${open ? "open" : ""}`} ref={ref}>
      <button className="menu-label" type="button" onClick={() => setOpen((v) => !v)}>
        {label}
      </button>
      {open && <div className="menu-items">{children(() => setOpen(false))}</div>}
    </div>
  );
}

/**
 * Close the settings window.
 *
 * `window.close()` does nothing inside a Tauri webview: the page is not what
 * owns the window, so the request has to go to Tauri itself. The API is
 * imported on demand rather than at the top, because the same UI runs in a
 * plain browser tab during development, where there is no Tauri to ask and
 * `window.close()` is the right answer after all.
 */
async function closeWindow(): Promise<void> {
  if ("__TAURI_INTERNALS__" in window) {
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      await getCurrentWindow().close();
      return;
    } catch (error) {
      console.warn("could not close the window through Tauri:", error);
    }
  }
  window.close();
}

export function TopBar() {
  const { t } = useTranslation();
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const online = useStore((s) => s.online);
  const ready = useStore((s) => s.ready);
  const version = useStore((s) => s.version);

  const state = online ? "online" : ready ? "offline" : "";
  const primary = online
    ? t("status.connected")
    : ready
      ? t("status.offline")
      : t("status.checking");

  return (
    <>
      <header className="topbar">
        <Wordmark />

        <nav className="menubar">
          <Menu label={t("menu.file")}>
            {(close) => (
              <>
                <button
                  type="button"
                  onClick={() => {
                    void useStore.getState().load();
                    close();
                  }}
                >
                  {t("menu.reload")}
                </button>
                <div className="sep" />
                <button
                  type="button"
                  onClick={() => {
                    close();
                    void closeWindow();
                  }}
                >
                  {t("menu.quit")}
                </button>
              </>
            )}
          </Menu>

          <Menu label={t("menu.language")}>
            {(close) => (
              <>
                {SUPPORTED_LANGUAGES.map((code) => (
                  <button
                    key={code}
                    type="button"
                    onClick={() => {
                      void setLanguage(code as Language);
                      close();
                    }}
                  >
                    {LANGUAGE_LABELS[code]}
                    {i18n.language === code && <span className="check">✓</span>}
                  </button>
                ))}
              </>
            )}
          </Menu>

          <Menu label={t("menu.help")}>
            {(close) => (
              <button
                type="button"
                onClick={() => {
                  setView("about");
                  close();
                }}
              >
                {t("menu.about")}
              </button>
            )}
          </Menu>
        </nav>

        <div className="spacer" />

        <div className={`status ${state}`}>
          <span className="dot" />
          <div className="lines">
            <div className="primary">{primary}</div>
            {online && version && (
              <div className="secondary">{t("status.version", { version })}</div>
            )}
          </div>
        </div>
      </header>

      {/* Own row: at the window's minimum width these entries do not fit
          beside the wordmark, the menu and the status pill. */}
      <nav className="nav">
        {VIEWS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={view === entry.id ? "active" : ""}
            onClick={() => setView(entry.id)}
          >
            {t(entry.labelKey)}
          </button>
        ))}
      </nav>
    </>
  );
}
