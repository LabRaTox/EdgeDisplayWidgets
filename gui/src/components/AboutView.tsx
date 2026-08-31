import { useTranslation } from "react-i18next";

import { API_BASE, openExternal } from "../api/client";
import { useStore } from "../store";

/** Other things by the same author, worth a look if this one is useful. */
const SIBLINGS = [
  {
    name: "DECK//SWITCH",
    // Its own brand colour, not this window's accent: the two happen to match
    // today, and the name should keep looking right if ours ever changes.
    accent: "#3b82f6",
    logo: "/deckswitch.svg",
    descriptionKey: "about.deckswitch",
    url: "https://github.com/LabRaTox/Deck-Switch",
  },
];

/**
 * A name of the NAME//NAME kind, with the slashes in the brand colour.
 *
 * The same construction as the EDGE//DASH wordmark in the top bar, which is
 * what makes the family recognisable.
 */
function Wordmark({ name, accent }: { name: string; accent: string }) {
  const parts = name.split("//");
  return (
    <>
      {parts.map((part, index) => (
        <span key={index}>
          {index > 0 && <span style={{ color: accent }}>//</span>}
          {part}
        </span>
      ))}
    </>
  );
}

const CREDITS = [
  { name: "Open-Meteo", what: "Wetterdaten / weather data", url: "https://open-meteo.com" },
  { name: "Tabler Icons", what: "MIT", url: "https://tabler.io/icons" },
  { name: "Qt WebEngine", what: "Kiosk-Fenster / kiosk window", url: "https://www.qt.io" },
  { name: "Tauri", what: "Fensterrahmen / window frame", url: "https://tauri.app" },
];

export function AboutView() {
  const { t } = useTranslation();
  const version = useStore((s) => s.version);

  return (
    <div className="view">
      <div className="view-head">
        <h2>{t("about.title")}</h2>
        <p>{t("about.description")}</p>
      </div>

      <div className="card">
        <dl className="about-list">
          <dt>{t("about.backend")}</dt>
          <dd>{version || t("common.none")}</dd>
          <dt>{t("about.window")}</dt>
          <dd>{__APP_VERSION__}</dd>
          <dt>API</dt>
          <dd>{API_BASE}</dd>
        </dl>
      </div>

      <div className="card">
        <header>
          <h3>{t("about.siblings")}</h3>
        </header>
        <div className="card-body">
          {SIBLINGS.map((project) => (
            <button
              key={project.name}
              type="button"
              className="sibling"
              onClick={() => void openExternal(project.url)}
              title={project.url}
            >
              <img className="sibling-logo" src={project.logo} alt="" />
              <span className="sibling-text">
                <strong>
                  <Wordmark name={project.name} accent={project.accent} />
                </strong>
                <span className="hint">{t(project.descriptionKey)}</span>
                <span className="muted sibling-url">{project.url}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <header>
          <h3>{t("about.credits")}</h3>
        </header>
        <div className="card-body">
          <dl className="about-list">
            {CREDITS.map((entry) => (
              <div key={entry.name} style={{ display: "contents" }}>
                <dt>{entry.name}</dt>
                <dd>
                  {entry.what} ·{" "}
                  <button
                    type="button"
                    className="linkish"
                    onClick={() => void openExternal(entry.url)}
                  >
                    {entry.url}
                  </button>
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}
