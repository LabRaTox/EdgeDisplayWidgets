import { useTranslation } from "react-i18next";

import { useDraft } from "../lib/useDraft";
import { useStore } from "../store";
import type { ModuleSettings } from "../types";
import { SaveBar } from "./SaveBar";

/**
 * Weather keeps its own view rather than living off a settings schema: a
 * latitude and a longitude belong next to each other and next to the place
 * name they describe, which a generic field list cannot express.
 */
export function WeatherView() {
  const { t } = useTranslation();
  const settings = useStore((s) => s.settings);
  const saveSettings = useStore((s) => s.saveSettings);

  const upstream = settings?.modules.weather ?? null;
  const { draft, dirty, state, edit, reset, save } = useDraft(upstream);
  if (!draft) return null;

  const value = (key: string, fallback = "") => String(draft[key] ?? fallback);
  const set = (key: string, next: unknown) => edit((d) => ({ ...d, [key]: next }));

  return (
    <div className="view">
      <div className="view-head">
        <h2>{t("weather.title")}</h2>
        <p>{t("weather.help")}</p>
      </div>

      <div className="card">
        <div className="row">
          <label htmlFor="w-name">{t("settings.weather.name", { defaultValue: "Ort" })}</label>
          <div className="control">
            <input id="w-name" value={value("name")} onChange={(e) => set("name", e.target.value)} />
          </div>
        </div>

        <div className="row">
          <label>{t("settings.weather.coords", { defaultValue: "Koordinaten" })}</label>
          <div className="control grid-2">
            <label className="inline">
              <span className="muted">lat</span>
              <input
                type="number"
                step="0.0001"
                value={value("lat")}
                onChange={(e) => set("lat", Number(e.target.value))}
              />
            </label>
            <label className="inline">
              <span className="muted">lon</span>
              <input
                type="number"
                step="0.0001"
                value={value("lon")}
                onChange={(e) => set("lon", Number(e.target.value))}
              />
            </label>
          </div>
        </div>

        <div className="row">
          <label htmlFor="w-units">
            {t("settings.weather.units", { defaultValue: "Einheiten" })}
          </label>
          <div className="control">
            <select
              id="w-units"
              value={value("units", "metric")}
              onChange={(e) => set("units", e.target.value)}
            >
              <option value="metric">metric (°C, km/h)</option>
              <option value="imperial">imperial (°F, mph)</option>
            </select>
          </div>
        </div>

        <div className="row">
          <label htmlFor="w-tz">
            {t("settings.weather.timezone", { defaultValue: "Zeitzone" })}
          </label>
          <div className="control">
            <input
              id="w-tz"
              value={value("timezone", "auto")}
              onChange={(e) => set("timezone", e.target.value)}
            />
            <div className="hint">auto · Europe/Berlin · UTC …</div>
          </div>
        </div>

        <div className="row">
          <label>
            {t("settings.weather.forecast", { defaultValue: "Vorhersage" })}
          </label>
          <div className="control grid-2">
            <label className="inline">
              <span className="muted">h</span>
              <input
                type="number"
                min={0}
                max={48}
                value={value("forecast_hours", "24")}
                onChange={(e) => set("forecast_hours", Number(e.target.value))}
              />
            </label>
            <label className="inline">
              <span className="muted">d</span>
              <input
                type="number"
                min={0}
                max={16}
                value={value("forecast_days", "7")}
                onChange={(e) => set("forecast_days", Number(e.target.value))}
              />
            </label>
          </div>
        </div>
      </div>

      <SaveBar
        dirty={dirty}
        state={state}
        onReset={reset}
        onSave={() =>
          void save((weather: ModuleSettings) =>
            saveSettings({ modules: { weather } }),
          )
        }
      />
    </div>
  );
}
