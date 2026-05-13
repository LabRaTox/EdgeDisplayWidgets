import { registerWidget } from "../registry.js";
import { t } from "../i18n.js";

// WMO weather codes → day/night glyph + label key. Labels resolve to the
// current locale via t() at render time. Source: open-meteo.com (weather_code)
const CODE_MAP = new Map([
  [0,  { day: "☀",  night: "🌙" }],
  [1,  { day: "🌤", night: "🌙" }],
  [2,  { day: "⛅", night: "☁"  }],
  [3,  { day: "☁",  night: "☁"  }],
  [45, { day: "🌫", night: "🌫" }],
  [48, { day: "🌫", night: "🌫" }],
  [51, { day: "🌦", night: "🌧" }],
  [53, { day: "🌦", night: "🌧" }],
  [55, { day: "🌧", night: "🌧" }],
  [56, { day: "🌨", night: "🌨" }],
  [57, { day: "🌨", night: "🌨" }],
  [61, { day: "🌦", night: "🌧" }],
  [63, { day: "🌧", night: "🌧" }],
  [65, { day: "🌧", night: "🌧" }],
  [66, { day: "🌨", night: "🌨" }],
  [67, { day: "🌨", night: "🌨" }],
  [71, { day: "🌨", night: "🌨" }],
  [73, { day: "❄",  night: "❄"  }],
  [75, { day: "❄",  night: "❄"  }],
  [77, { day: "🌨", night: "🌨" }],
  [80, { day: "🌦", night: "🌧" }],
  [81, { day: "🌧", night: "🌧" }],
  [82, { day: "⛈", night: "⛈"  }],
  [85, { day: "🌨", night: "🌨" }],
  [86, { day: "❄",  night: "❄"  }],
  [95, { day: "⛈", night: "⛈"  }],
  [96, { day: "⛈", night: "⛈"  }],
  [99, { day: "⛈", night: "⛈"  }],
]);

function weatherIcon(code, isDay = true) {
  const n = Number(code);
  const entry = CODE_MAP.get(n);
  if (!entry) return { glyph: "·", label: "—" };
  return { glyph: isDay ? entry.day : entry.night, label: t(`widget.weather.code.${n}`) };
}

function fmtTemp(value, unit) {
  if (value == null || Number.isNaN(value)) return "–";
  return `${Math.round(value)}${unit || "°"}`;
}

function fmtHour(iso) {
  if (!iso) return "";
  // Open-Meteo liefert "2026-05-10T18:00" in der konfigurierten Zeitzone
  const m = iso.match(/T(\d{2}):/);
  return m ? m[1] : iso;
}

function fmtAge(seconds) {
  if (seconds < 60) return t("widget.weather.age_seconds", { value: seconds });
  if (seconds < 3600) return t("widget.weather.age_minutes", { value: Math.round(seconds / 60) });
  return t("widget.weather.age_hours", { value: Math.round(seconds / 3600) });
}

class WeatherWidget {
  static modules = ["weather"];

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="weather-location" data-bind="location"></div>
      <div class="weather-head">
        <div class="weather-now">
          <div class="weather-icon" data-bind="icon">·</div>
          <div class="weather-temp" data-bind="temp">–</div>
        </div>
        <div class="weather-meta">
          <div class="weather-cond" data-bind="cond">…</div>
          <div class="weather-feels"><span data-bind="feels"></span></div>
          <div class="weather-hilo">
            <span class="hi">↑ <span data-bind="hi">–</span></span>
            <span class="lo">↓ <span data-bind="lo">–</span></span>
          </div>
        </div>
      </div>
      <div class="weather-stale" data-bind="stale" hidden>${t("widget.weather.stale")} <span data-bind="stale_age"></span></div>
      <div class="weather-hours" data-bind="hours"></div>
    `;
    this._lastUpdate = null;
    this._timer = setInterval(() => this._renderStaleAge(), 30_000);
  }

  update(data) {
    if (!data?.available) {
      this._renderUnavailable(data?.error);
      return;
    }
    this._lastUpdate = data;
    this.el.classList.remove("widget-disabled");

    const cur = data.current || {};
    const tempUnit = data.units?.temperature || "°C";
    const isDay = cur.is_day !== false;
    const icon = weatherIcon(cur.weather_code, isDay);

    const locName = data.location?.name || "";
    const locEl = this.el.querySelector('[data-bind="location"]');
    locEl.textContent = locName;
    locEl.hidden = !locName;

    this.el.querySelector('[data-bind="icon"]').textContent = icon.glyph;
    this.el.querySelector('[data-bind="cond"]').textContent = icon.label;
    this.el.querySelector('[data-bind="temp"]').textContent =
      fmtTemp(cur.temperature, tempUnit);
    this.el.querySelector('[data-bind="feels"]').textContent =
      cur.apparent_temperature != null
        ? t("widget.weather.feels_like", { temp: fmtTemp(cur.apparent_temperature, tempUnit) })
        : "";

    const daily = data.daily || {};
    const hi = daily.temperature_max?.[0];
    const lo = daily.temperature_min?.[0];
    this.el.querySelector('[data-bind="hi"]').textContent = fmtTemp(hi, tempUnit);
    this.el.querySelector('[data-bind="lo"]').textContent = fmtTemp(lo, tempUnit);

    this._renderHourly(data.hourly || {}, tempUnit);

    const stale = this.el.querySelector('[data-bind="stale"]');
    if (data.stale) {
      stale.hidden = false;
      this._renderStaleAge();
    } else {
      stale.hidden = true;
    }
  }

  _renderHourly(hourly, tempUnit) {
    const root = this.el.querySelector('[data-bind="hours"]');
    const times = hourly.time || [];
    const temps = hourly.temperature || [];
    const codes = hourly.weather_code || [];
    const probs = hourly.precipitation_probability || [];

    const now = Date.now();
    let startIdx = 0;
    for (let i = 0; i < times.length; i++) {
      const t = Date.parse(times[i]);
      if (Number.isFinite(t) && t >= now - 30 * 60_000) {
        startIdx = i;
        break;
      }
    }

    const slots = [];
    for (let i = startIdx; i < Math.min(startIdx + 24, times.length); i++) {
      const icon = weatherIcon(codes[i], true);
      slots.push(`
        <div class="weather-hour">
          <div class="weather-hour-time">${fmtHour(times[i])}</div>
          <div class="weather-hour-icon">${icon.glyph}</div>
          <div class="weather-hour-temp">${fmtTemp(temps[i], tempUnit)}</div>
          ${probs[i] != null && probs[i] > 0 ? `<div class="weather-hour-rain">${Math.round(probs[i])}%</div>` : ""}
        </div>
      `);
    }
    root.innerHTML = slots.join("");
  }

  _renderUnavailable(reason) {
    this.el.classList.add("widget-disabled");
    this.el.querySelector('[data-bind="location"]').hidden = true;
    this.el.querySelector('[data-bind="icon"]').textContent = "·";
    this.el.querySelector('[data-bind="temp"]').textContent = "–";
    this.el.querySelector('[data-bind="cond"]').textContent =
      reason || t("common.unavailable");
    this.el.querySelector('[data-bind="feels"]').textContent = "";
    this.el.querySelector('[data-bind="hi"]').textContent = "–";
    this.el.querySelector('[data-bind="lo"]').textContent = "–";
    this.el.querySelector('[data-bind="hours"]').innerHTML = "";
    this.el.querySelector('[data-bind="stale"]').hidden = true;
  }

  _renderStaleAge() {
    const d = this._lastUpdate;
    if (!d?.stale || !d.fetched_at) return;
    const ageSec = Math.max(0, Math.round(Date.now() / 1000 - d.fetched_at));
    const el = this.el.querySelector('[data-bind="stale_age"]');
    if (el) el.textContent = fmtAge(ageSec);
  }

  destroy() {
    clearInterval(this._timer);
  }
}

registerWidget("weather", WeatherWidget);
