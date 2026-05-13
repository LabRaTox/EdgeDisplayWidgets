"""Tests for the WeatherModule (Open-Meteo client)."""

from __future__ import annotations

import time

import httpx
import pytest

from backend.modules.base import clear_registry, register_module
from backend.modules.weather import WeatherModule, OPEN_METEO_URL


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    register_module(WeatherModule)
    yield
    clear_registry()


_FAKE_RESPONSE = {
    "current_units": {"temperature_2m": "°C", "wind_speed_10m": "km/h"},
    "hourly_units": {"precipitation_probability": "%"},
    "current": {
        "time": "2026-05-10T14:00",
        "temperature_2m": 18.4,
        "apparent_temperature": 17.0,
        "relative_humidity_2m": 62,
        "weather_code": 3,
        "wind_speed_10m": 12.5,
        "wind_direction_10m": 220,
        "is_day": 1,
    },
    "hourly": {
        "time": ["2026-05-10T14:00", "2026-05-10T15:00"],
        "temperature_2m": [18.4, 18.9],
        "weather_code": [3, 2],
        "precipitation_probability": [10, 5],
    },
    "daily": {
        "time": ["2026-05-10"],
        "temperature_2m_min": [11.2],
        "temperature_2m_max": [19.5],
        "weather_code": [3],
        "sunrise": ["2026-05-10T06:11"],
        "sunset": ["2026-05-10T20:42"],
    },
}


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_poll_returns_normalised_payload(monkeypatch):
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_FAKE_RESPONSE)

    transport = _mock_transport(handler)

    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("backend.modules.weather.httpx.AsyncClient", patched_client)

    mod = WeatherModule({
        "lat": 49.9667,
        "lon": 8.05,
        "name": "Ingelheim am Rhein",
        "interval": 600,
    })
    data = await mod.poll()

    assert data["available"] is True
    assert data["stale"] is False
    assert data["location"]["name"] == "Ingelheim am Rhein"
    assert data["location"]["lat"] == pytest.approx(49.9667)
    assert data["current"]["temperature"] == 18.4
    assert data["daily"]["temperature_max"] == [19.5]
    assert data["units"]["temperature"] == "°C"
    assert OPEN_METEO_URL in captured["url"]


def test_location_name_defaults_to_empty_string():
    mod = WeatherModule({})
    assert mod.location_name == ""


@pytest.mark.asyncio
async def test_poll_returns_stale_when_fetch_fails_after_success(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_FAKE_RESPONSE)
        return httpx.Response(503, json={"error": "down"})

    transport = _mock_transport(handler)
    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("backend.modules.weather.httpx.AsyncClient", patched_client)

    mod = WeatherModule({"lat": 1.0, "lon": 2.0})
    first = await mod.poll()
    assert first["stale"] is False
    assert first["current"]["temperature"] == 18.4

    second = await mod.poll()
    assert second["available"] is True
    assert second["stale"] is True
    assert "error" in second
    # Stale payload should still hold the previous numbers
    assert second["current"]["temperature"] == 18.4


@pytest.mark.asyncio
async def test_poll_unavailable_when_no_prior_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = _mock_transport(handler)
    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("backend.modules.weather.httpx.AsyncClient", patched_client)

    mod = WeatherModule({})
    data = await mod.poll()
    assert data["available"] is False
    assert "error" in data


def test_metric_imperial_units_in_request_params():
    mod_metric = WeatherModule({"units": "metric"})
    p = mod_metric._params
    assert p["temperature_unit"] == "celsius"
    assert p["wind_speed_unit"] == "kmh"

    mod_imperial = WeatherModule({"units": "imperial"})
    p = mod_imperial._params
    assert p["temperature_unit"] == "fahrenheit"
    assert p["wind_speed_unit"] == "mph"
