"""Weather module — Open-Meteo (no API key) with 10-minute cache.

Resilient by design: any fetch error keeps serving the previous response
with ``stale: true``, so a transient outage doesn't blank the widget.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger

from .base import Module, register_module

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


@register_module
class WeatherModule(Module):
    name = "weather"
    default_interval = 600  # 10 minutes

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.lat: float = float(config.get("lat", 52.52))
        self.lon: float = float(config.get("lon", 13.41))
        self.location_name: str = str(config.get("name", "")).strip()
        self.timezone: str = str(config.get("timezone", "auto"))
        self.units: str = str(config.get("units", "metric")).lower()
        self.forecast_hours: int = int(config.get("forecast_hours", 24))
        self.forecast_days: int = int(config.get("forecast_days", 7))

        self._last_payload: dict[str, Any] | None = None
        self._last_fetch_ts: float = 0.0
        self._last_error: str | None = None

    @property
    def _params(self) -> dict[str, Any]:
        is_metric = self.units == "metric"
        return {
            "latitude": self.lat,
            "longitude": self.lon,
            "current": ",".join([
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "weather_code",
                "wind_speed_10m",
                "wind_direction_10m",
                "is_day",
            ]),
            "hourly": ",".join([
                "temperature_2m",
                "weather_code",
                "precipitation_probability",
            ]),
            "daily": ",".join([
                "temperature_2m_min",
                "temperature_2m_max",
                "weather_code",
                "sunrise",
                "sunset",
            ]),
            "forecast_hours": self.forecast_hours,
            "forecast_days": self.forecast_days,
            "timezone": self.timezone,
            "temperature_unit": "celsius" if is_metric else "fahrenheit",
            "wind_speed_unit": "kmh" if is_metric else "mph",
            "precipitation_unit": "mm" if is_metric else "inch",
        }

    async def poll(self) -> dict[str, Any]:
        try:
            payload = await self._fetch()
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning(f"weather fetch failed: {exc}")
            if self._last_payload is not None:
                return {
                    "available": True,
                    "stale": True,
                    "error": self._last_error,
                    "fetched_at": self._last_fetch_ts,
                    **self._last_payload,
                }
            return {"available": False, "error": self._last_error}

        self._last_payload = payload
        self._last_fetch_ts = time.time()
        self._last_error = None
        return {
            "available": True,
            "stale": False,
            "fetched_at": self._last_fetch_ts,
            **payload,
        }

    async def _fetch(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(OPEN_METEO_URL, params=self._params)
            r.raise_for_status()
            return self._normalize(r.json())

    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Trim Open-Meteo's response to the fields the frontend uses."""
        cur = raw.get("current") or {}
        hourly = raw.get("hourly") or {}
        daily = raw.get("daily") or {}

        return {
            "location": {
                "lat": self.lat,
                "lon": self.lon,
                "name": self.location_name,
            },
            "units": {
                "temperature": raw.get("current_units", {}).get("temperature_2m", "°C"),
                "wind": raw.get("current_units", {}).get("wind_speed_10m", "km/h"),
                "precipitation": raw.get("hourly_units", {}).get("precipitation_probability", "%"),
            },
            "current": {
                "temperature": cur.get("temperature_2m"),
                "apparent_temperature": cur.get("apparent_temperature"),
                "humidity": cur.get("relative_humidity_2m"),
                "weather_code": cur.get("weather_code"),
                "wind_speed": cur.get("wind_speed_10m"),
                "wind_direction": cur.get("wind_direction_10m"),
                "is_day": bool(cur.get("is_day")),
                "time": cur.get("time"),
            },
            "hourly": {
                "time": hourly.get("time", []),
                "temperature": hourly.get("temperature_2m", []),
                "weather_code": hourly.get("weather_code", []),
                "precipitation_probability": hourly.get("precipitation_probability", []),
            },
            "daily": {
                "time": daily.get("time", []),
                "temperature_min": daily.get("temperature_2m_min", []),
                "temperature_max": daily.get("temperature_2m_max", []),
                "weather_code": daily.get("weather_code", []),
                "sunrise": daily.get("sunrise", []),
                "sunset": daily.get("sunset", []),
            },
        }
