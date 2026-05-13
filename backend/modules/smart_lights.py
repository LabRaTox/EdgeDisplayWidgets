"""Smart lights aggregator — Govee Developer API + Tuya IoT Cloud.

Both providers are wrapped in a small ``LightProvider`` abstraction so the
module produces one unified ``devices`` list. Each device is namespaced by
``provider:id`` so device IDs stay globally unique even when Govee and Tuya
happen to reuse local IDs.

Credentials live in the per-module config; ``_settings_view`` in ``main.py``
strips them before exposing settings to the frontend so API keys / secrets
never travel beyond the backend.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import httpx
from loguru import logger

from .base import Module, register_module


# --------------------------------------------------------------------- color helpers


def _parse_rgb(value: Any) -> tuple[int, int, int]:
    """Accept RGB as ``{r,g,b}`` dict or ``#rrggbb`` hex string."""
    if isinstance(value, dict):
        r = int(value.get("r", 0))
        g = int(value.get("g", 0))
        b = int(value.get("b", 0))
    elif isinstance(value, str):
        s = value.strip().lstrip("#")
        if len(s) != 6:
            raise ValueError(f"hex color must be 6 chars, got '{value}'")
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    else:
        raise ValueError(f"unsupported color value type: {type(value).__name__}")
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def _rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert 0–255 RGB to (h ∈ [0, 360), s ∈ [0, 1], v ∈ [0, 1])."""
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(rf, gf, bf), min(rf, gf, bf)
    df = mx - mn
    if df == 0:
        h = 0.0
    elif mx == rf:
        h = (60 * ((gf - bf) / df) + 360) % 360
    elif mx == gf:
        h = (60 * ((bf - rf) / df) + 120) % 360
    else:
        h = (60 * ((rf - gf) / df) + 240) % 360
    s = 0.0 if mx == 0 else df / mx
    return h, s, mx


# --------------------------------------------------------------------- ABC


class LightProvider(ABC):
    """One backend integration (Govee, Tuya, …)."""

    name: str = ""

    @abstractmethod
    async def list_devices(self) -> list[dict[str, Any]]:
        """Return current devices including state.

        Each entry must include the keys consumed by the frontend:
            id, provider, name, online, on, brightness, has_brightness, has_color
        Plus any provider-private fields under ``_meta`` for control routing.
        """

    @abstractmethod
    async def control(
        self, device_meta: dict[str, Any], action: str, value: Any = None,
    ) -> dict[str, Any]:
        """Apply the action to a single device."""


# --------------------------------------------------------------------- Govee


class GoveeProvider(LightProvider):
    """Govee Developer API v1 — https://developer-api.govee.com/v1.

    Free tier: ~10 000 requests/day. The module's default 30 s poll keeps
    well under that limit even with a dozen devices.
    """

    name = "govee"
    BASE = "https://developer-api.govee.com/v1"

    def __init__(self, api_key: str, timeout: float = 10.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Govee-API-Key": self.api_key}

    async def list_devices(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(f"{self.BASE}/devices", headers=self._headers())
            r.raise_for_status()
            raw = r.json().get("data", {}).get("devices", []) or []

            async def _hydrate(d: dict[str, Any]) -> dict[str, Any]:
                state = await self._fetch_state(client, d.get("device"), d.get("model"))
                cmds = set(d.get("supportCmds", []) or [])
                power = state.get("powerState")
                return {
                    "id": f"govee:{d.get('device')}",
                    "provider": "govee",
                    "name": d.get("deviceName") or d.get("device") or "?",
                    "online": True if state else False,
                    "on": power == "on" if power else None,
                    "brightness": state.get("brightness"),
                    "has_brightness": "brightness" in cmds,
                    "has_color": "color" in cmds,
                    "_meta": {"device": d.get("device"), "model": d.get("model")},
                }

            # Govee's per-device state endpoint is rate-friendly enough to hit
            # concurrently; gather keeps total poll latency around one round-trip.
            return await asyncio.gather(*[_hydrate(d) for d in raw])

    async def _fetch_state(
        self, client: httpx.AsyncClient, device: str | None, model: str | None,
    ) -> dict[str, Any]:
        if not device or not model:
            return {}
        try:
            r = await client.get(
                f"{self.BASE}/devices/state",
                params={"device": device, "model": model},
                headers=self._headers(),
            )
            r.raise_for_status()
            # Govee returns properties as an array of single-key dicts; flatten.
            flat: dict[str, Any] = {}
            for p in r.json().get("data", {}).get("properties", []) or []:
                if isinstance(p, dict):
                    flat.update(p)
            return flat
        except Exception as exc:
            logger.warning(f"govee state fetch failed for {device}: {exc}")
            return {}

    async def control(
        self, device_meta: dict[str, Any], action: str, value: Any = None,
    ) -> dict[str, Any]:
        if action == "on":
            cmd = {"name": "turn", "value": "on"}
        elif action == "off":
            cmd = {"name": "turn", "value": "off"}
        elif action == "brightness":
            level = max(0, min(100, int(value)))
            cmd = {"name": "brightness", "value": level}
        elif action == "color":
            r, g, b = _parse_rgb(value)
            cmd = {"name": "color", "value": {"r": r, "g": g, "b": b}}
        else:
            raise ValueError(f"unsupported govee action: {action}")
        body = {
            "device": device_meta["device"],
            "model": device_meta["model"],
            "cmd": cmd,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.put(
                f"{self.BASE}/devices/control",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
            )
            r.raise_for_status()
            return {"ok": True, "raw": r.json()}


# --------------------------------------------------------------------- Tuya


# Tuya signs requests with HMAC-SHA256 over:
#   client_id + (access_token if authenticated) + t + nonce + stringToSign
# where stringToSign = method + "\n" + sha256(body) + "\n" + signedHeaders + "\n" + canonical_url.
def _tuya_sign(
    client_id: str,
    secret: str,
    method: str,
    path: str,
    body: str,
    t: str,
    access_token: str = "",
    nonce: str = "",
) -> str:
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    string_to_sign = f"{method}\n{content_hash}\n\n{path}"
    msg = f"{client_id}{access_token}{t}{nonce}{string_to_sign}"
    sig = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256)
    return sig.hexdigest().upper()


# Tuya regional endpoints — pick the one closest to where the Smart Life
# account was created. Most EU users land on EU central.
TUYA_REGIONS = {
    "eu": "https://openapi.tuyaeu.com",
    "us": "https://openapi.tuyaus.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}


class TuyaProvider(LightProvider):
    """Tuya IoT Cloud — used by Antela, Smart Life, Tuya Smart, and dozens of OEMs."""

    name = "tuya"

    def __init__(
        self,
        client_id: str,
        secret: str,
        uid: str,
        region: str = "eu",
        timeout: float = 10.0,
    ) -> None:
        self.client_id = client_id
        self.secret = secret
        self.uid = uid
        self.base = TUYA_REGIONS.get(region.lower(), TUYA_REGIONS["eu"])
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        async with self._token_lock:
            if self._token and time.time() < self._token_expires_at - 60:
                return self._token
            path = "/v1.0/token?grant_type=1"
            t = str(int(time.time() * 1000))
            nonce = uuid.uuid4().hex
            sign = _tuya_sign(
                self.client_id, self.secret, "GET", path, "", t, "", nonce,
            )
            r = await client.get(
                self.base + path,
                headers={
                    "client_id": self.client_id,
                    "sign_method": "HMAC-SHA256",
                    "t": t,
                    "nonce": nonce,
                    "sign": sign,
                },
            )
            r.raise_for_status()
            body = r.json()
            if not body.get("success"):
                raise RuntimeError(f"tuya token request failed: {body}")
            result = body["result"]
            self._token = result["access_token"]
            self._token_expires_at = time.time() + int(result.get("expire_time", 7200))
            return self._token

    async def _signed_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self._ensure_token(client)
        t = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        body_str = json.dumps(body, separators=(",", ":")) if body is not None else ""
        sign = _tuya_sign(
            self.client_id, self.secret, method, path, body_str, t, token, nonce,
        )
        headers = {
            "client_id": self.client_id,
            "sign_method": "HMAC-SHA256",
            "t": t,
            "nonce": nonce,
            "sign": sign,
            "access_token": token,
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        r = await client.request(
            method, self.base + path, headers=headers, content=body_str or None,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success", True):
            raise RuntimeError(f"tuya error: {data.get('msg', data)}")
        return data

    async def list_devices(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            data = await self._signed_request(
                client, "GET", f"/v1.0/users/{self.uid}/devices",
            )
        out: list[dict[str, Any]] = []
        for d in data.get("result") or []:
            status = {s["code"]: s["value"] for s in (d.get("status") or [])}
            switch = status.get("switch_led")
            if switch is None:
                # Some devices use `switch_1` instead of `switch_led`.
                switch = status.get("switch_1")
            # Brightness in Tuya is usually 10–1000 (one decimal of percent).
            raw_bright = status.get("bright_value") or status.get("bright_value_v2")
            brightness_pct: int | None = None
            if isinstance(raw_bright, (int, float)) and raw_bright > 0:
                brightness_pct = max(1, min(100, round(raw_bright / 10)))
            out.append({
                "id": f"tuya:{d['id']}",
                "provider": "tuya",
                "name": d.get("name") or d["id"],
                "online": bool(d.get("online", False)),
                "on": bool(switch) if switch is not None else None,
                "brightness": brightness_pct,
                "has_brightness": any(
                    "bright_value" in c for c in (
                        status.keys() if status else []
                    )
                ) or "Light" in (d.get("category") or ""),
                "has_color": "colour_data" in status or "colour_data_v2" in status,
                "_meta": {"device": d["id"]},
            })
        return out

    async def control(
        self, device_meta: dict[str, Any], action: str, value: Any = None,
    ) -> dict[str, Any]:
        # Tuya commands are issued as a list of {code, value} pairs.
        if action == "on":
            commands = [{"code": "switch_led", "value": True}]
        elif action == "off":
            commands = [{"code": "switch_led", "value": False}]
        elif action == "brightness":
            level = max(1, min(100, int(value)))
            commands = [{"code": "bright_value_v2", "value": level * 10}]
        elif action == "color":
            r, g, b = _parse_rgb(value)
            h, s, v = _rgb_to_hsv(r, g, b)
            # Tuya HSV scale: h 0..360, s 0..1000, v 0..1000.
            commands = [{
                "code": "colour_data_v2",
                "value": {
                    "h": int(round(h)),
                    "s": int(round(s * 1000)),
                    "v": int(round(v * 1000)),
                },
            }]
        else:
            raise ValueError(f"unsupported tuya action: {action}")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            data = await self._signed_request(
                client,
                "POST",
                f"/v1.0/iot-03/devices/{device_meta['device']}/commands",
                {"commands": commands},
            )
        return {"ok": True, "raw": data}


# --------------------------------------------------------------- Module


@register_module
class SmartLightsModule(Module):
    name = "smart_lights"
    default_interval = 30.0  # cloud APIs don't need to be hammered

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.providers: dict[str, LightProvider] = {}
        self._provider_errors: dict[str, str | None] = {}

        govee_cfg = config.get("govee") or {}
        if govee_cfg.get("api_key"):
            self.providers["govee"] = GoveeProvider(
                api_key=str(govee_cfg["api_key"]),
                timeout=float(govee_cfg.get("timeout", 10.0)),
            )
        tuya_cfg = config.get("tuya") or {}
        if all(tuya_cfg.get(k) for k in ("client_id", "secret", "uid")):
            self.providers["tuya"] = TuyaProvider(
                client_id=str(tuya_cfg["client_id"]),
                secret=str(tuya_cfg["secret"]),
                uid=str(tuya_cfg["uid"]),
                region=str(tuya_cfg.get("region", "eu")),
                timeout=float(tuya_cfg.get("timeout", 10.0)),
            )

        self._devices: list[dict[str, Any]] = []
        self._meta_by_id: dict[str, dict[str, Any]] = {}

    async def poll(self) -> dict[str, Any]:
        merged: list[dict[str, Any]] = []
        errors: dict[str, str | None] = {}
        # All possible providers — we report 'not configured' for ones the
        # user hasn't filled in yet, so the widget surface stays honest.
        for name in ("govee", "tuya"):
            provider = self.providers.get(name)
            if provider is None:
                errors[name] = "not configured"
                continue
            try:
                devices = await provider.list_devices()
                merged.extend(devices)
                errors[name] = None
            except Exception as exc:
                logger.warning(f"smart_lights: {name} fetch failed: {exc}")
                errors[name] = str(exc)[:200]

        self._meta_by_id = {d["id"]: d.get("_meta", {}) for d in merged}
        # Strip _meta from the public payload — frontend doesn't need it.
        self._devices = [{k: v for k, v in d.items() if k != "_meta"} for d in merged]
        return {"devices": self._devices, "errors": errors}

    async def control(
        self, device_id: str, action: str, value: Any = None,
    ) -> dict[str, Any]:
        if ":" not in device_id:
            return {"ok": False, "error": "invalid device id"}
        provider_name, _ = device_id.split(":", 1)
        provider = self.providers.get(provider_name)
        if provider is None:
            return {"ok": False, "error": f"provider '{provider_name}' not configured"}
        meta = self._meta_by_id.get(device_id)
        if meta is None:
            # First control before the first poll completes — refresh once.
            await self.poll()
            meta = self._meta_by_id.get(device_id)
        if meta is None:
            return {"ok": False, "error": "device not found"}
        try:
            return await provider.control(meta, action, value)
        except Exception as exc:
            logger.exception(f"smart_lights control {device_id} {action} failed: {exc}")
            return {"ok": False, "error": str(exc)}
