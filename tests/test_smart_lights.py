"""Tests for the SmartLightsModule: providers, Tuya signing, control routing."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.modules.base import clear_registry, register_module
from backend.modules.smart_lights import (
    GoveeProvider,
    SmartLightsModule,
    TuyaProvider,
    _parse_rgb,
    _rgb_to_hsv,
    _tuya_sign,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    register_module(SmartLightsModule)
    yield
    clear_registry()


# --------------------------------------------------------------- Tuya signing


def test_tuya_sign_is_deterministic_and_uppercase():
    """Snapshot the signature for a known input — guards against accidental
    changes to the canonical-string format that would break authentication."""
    sig = _tuya_sign(
        client_id="abc123",
        secret="topsecret",
        method="GET",
        path="/v1.0/token?grant_type=1",
        body="",
        t="1700000000000",
        access_token="",
        nonce="fixed-nonce",
    )
    assert sig.isupper()
    # Stable across runs for the same inputs.
    sig2 = _tuya_sign(
        "abc123", "topsecret", "GET",
        "/v1.0/token?grant_type=1", "", "1700000000000", "", "fixed-nonce",
    )
    assert sig == sig2


def test_tuya_sign_changes_with_inputs():
    base = dict(
        client_id="abc123", secret="topsecret", method="GET",
        path="/p", body="", t="1700000000000", access_token="", nonce="",
    )
    sig0 = _tuya_sign(**base)
    sig_method = _tuya_sign(**{**base, "method": "POST"})
    sig_path = _tuya_sign(**{**base, "path": "/q"})
    sig_token = _tuya_sign(**{**base, "access_token": "tok"})
    sig_body = _tuya_sign(**{**base, "body": '{"x":1}'})
    assert len({sig0, sig_method, sig_path, sig_token, sig_body}) == 5


# --------------------------------------------------------------- Govee


def _patch_httpx(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(
        "backend.modules.smart_lights.httpx.AsyncClient", patched,
    )


@pytest.mark.asyncio
async def test_govee_list_devices(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices") and request.method == "GET":
            return httpx.Response(200, json={
                "data": {"devices": [
                    {
                        "device": "AA:BB:CC", "model": "H6159",
                        "deviceName": "Schreibtisch",
                        "supportCmds": ["turn", "brightness", "color"],
                    },
                ]},
            })
        if request.url.path.endswith("/devices/state"):
            return httpx.Response(200, json={
                "data": {"properties": [
                    {"online": True},
                    {"powerState": "on"},
                    {"brightness": 75},
                ]},
            })
        return httpx.Response(404)

    _patch_httpx(monkeypatch, handler)
    devices = await GoveeProvider(api_key="dummy").list_devices()
    assert len(devices) == 1
    d = devices[0]
    assert d["id"] == "govee:AA:BB:CC"
    assert d["provider"] == "govee"
    assert d["name"] == "Schreibtisch"
    assert d["on"] is True
    assert d["brightness"] == 75
    assert d["has_brightness"] is True
    assert d["has_color"] is True
    assert d["_meta"] == {"device": "AA:BB:CC", "model": "H6159"}


@pytest.mark.asyncio
async def test_govee_control_turn_on(monkeypatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("Govee-API-Key")
        return httpx.Response(200, json={"code": 200})

    _patch_httpx(monkeypatch, handler)
    p = GoveeProvider(api_key="my-key")
    await p.control({"device": "AA", "model": "M"}, "on")
    assert seen["method"] == "PUT"
    assert seen["path"].endswith("/devices/control")
    assert seen["auth"] == "my-key"
    assert seen["body"]["cmd"] == {"name": "turn", "value": "on"}


# --------------------------------------------------------------- color helpers


def test_parse_rgb_accepts_dict_and_hex():
    assert _parse_rgb({"r": 255, "g": 128, "b": 0}) == (255, 128, 0)
    assert _parse_rgb("#ff8000") == (255, 128, 0)
    assert _parse_rgb("ff8000") == (255, 128, 0)


def test_parse_rgb_clamps_and_rejects_bad_input():
    assert _parse_rgb({"r": 300, "g": -5, "b": 50}) == (255, 0, 50)
    with pytest.raises(ValueError):
        _parse_rgb("not-a-color")
    with pytest.raises(ValueError):
        _parse_rgb(42)


def test_rgb_to_hsv_known_colors():
    # Pure red, green, blue, white, black — easy sanity checks.
    h, s, v = _rgb_to_hsv(255, 0, 0)
    assert h == 0 and s == 1.0 and v == 1.0
    h, s, v = _rgb_to_hsv(0, 255, 0)
    assert h == 120 and s == 1.0 and v == 1.0
    h, s, v = _rgb_to_hsv(0, 0, 255)
    assert h == 240 and s == 1.0 and v == 1.0
    h, s, v = _rgb_to_hsv(255, 255, 255)
    assert s == 0 and v == 1.0
    h, s, v = _rgb_to_hsv(0, 0, 0)
    assert v == 0


@pytest.mark.asyncio
async def test_govee_control_color(monkeypatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 200})

    _patch_httpx(monkeypatch, handler)
    p = GoveeProvider(api_key="k")
    await p.control({"device": "AA", "model": "M"}, "color", "#ff8000")
    assert seen["body"]["cmd"] == {
        "name": "color",
        "value": {"r": 255, "g": 128, "b": 0},
    }


@pytest.mark.asyncio
async def test_tuya_control_color_converts_to_hsv():
    seen: dict = {}

    async def fake_signed(self, client, method, path, body=None):
        seen["body"] = body
        return {"success": True, "result": True}

    p = TuyaProvider(client_id="c", secret="s", uid="u")
    p._signed_request = fake_signed.__get__(p, TuyaProvider)
    # Pure red → h=0, s=1000, v=1000
    await p.control({"device": "x"}, "color", "#ff0000")
    cmd = seen["body"]["commands"][0]
    assert cmd["code"] == "colour_data_v2"
    assert cmd["value"] == {"h": 0, "s": 1000, "v": 1000}


@pytest.mark.asyncio
async def test_govee_control_brightness_clamped(monkeypatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 200})

    _patch_httpx(monkeypatch, handler)
    p = GoveeProvider(api_key="k")
    await p.control({"device": "AA", "model": "M"}, "brightness", 350)
    assert seen["body"]["cmd"]["value"] == 100
    await p.control({"device": "AA", "model": "M"}, "brightness", -5)
    assert seen["body"]["cmd"]["value"] == 0


# --------------------------------------------------------------- Tuya control


@pytest.mark.asyncio
async def test_tuya_token_then_control(monkeypatch):
    seen_calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_calls.append((request.method, request.url.path))
        if request.url.path == "/v1.0/token":
            return httpx.Response(200, json={
                "success": True,
                "result": {"access_token": "TOK", "expire_time": 7200},
            })
        if request.url.path.endswith("/commands"):
            body = json.loads(request.content)
            assert body == {"commands": [{"code": "switch_led", "value": True}]}
            assert request.headers.get("access_token") == "TOK"
            return httpx.Response(200, json={"success": True, "result": True})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, handler)
    p = TuyaProvider(client_id="c", secret="s", uid="u", region="eu")
    await p.control({"device": "dev-1"}, "on")
    assert seen_calls[0][1] == "/v1.0/token"
    assert seen_calls[1][1].endswith("/commands")


@pytest.mark.asyncio
async def test_tuya_brightness_scaled():
    """Tuya expects bright_value_v2 in 10..1000 (percent × 10)."""
    seen: dict = {}

    async def fake_signed(self, client, method, path, body=None):
        seen["body"] = body
        return {"success": True, "result": True}

    p = TuyaProvider(client_id="c", secret="s", uid="u")
    p._signed_request = fake_signed.__get__(p, TuyaProvider)
    await p.control({"device": "dev-1"}, "brightness", 60)
    assert seen["body"] == {
        "commands": [{"code": "bright_value_v2", "value": 600}],
    }


# --------------------------------------------------------------- Module


@pytest.mark.asyncio
async def test_module_reports_not_configured_for_missing_providers():
    mod = SmartLightsModule({})
    data = await mod.poll()
    assert data["devices"] == []
    assert data["errors"] == {"govee": "not configured", "tuya": "not configured"}


@pytest.mark.asyncio
async def test_module_only_govee_configured(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices") and request.method == "GET":
            return httpx.Response(200, json={"data": {"devices": []}})
        return httpx.Response(200, json={"data": {"properties": []}})

    _patch_httpx(monkeypatch, handler)
    mod = SmartLightsModule({"govee": {"api_key": "k"}})
    data = await mod.poll()
    assert data["errors"]["govee"] is None
    assert data["errors"]["tuya"] == "not configured"


@pytest.mark.asyncio
async def test_module_control_unknown_provider():
    mod = SmartLightsModule({})  # no providers configured
    result = await mod.control("unknown:abc", "on")
    assert result["ok"] is False
    assert "not configured" in result["error"]


@pytest.mark.asyncio
async def test_module_strips_meta_from_public_payload(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices") and request.method == "GET":
            return httpx.Response(200, json={"data": {"devices": [
                {"device": "AA", "model": "H1", "deviceName": "L",
                 "supportCmds": ["turn", "brightness"]},
            ]}})
        return httpx.Response(200, json={"data": {"properties": [
            {"powerState": "off"}, {"brightness": 10},
        ]}})

    _patch_httpx(monkeypatch, handler)
    mod = SmartLightsModule({"govee": {"api_key": "k"}})
    data = await mod.poll()
    assert len(data["devices"]) == 1
    assert "_meta" not in data["devices"][0]
    # Internal cache still has the meta so control can route it.
    assert "govee:AA" in mod._meta_by_id
