"""Tests for the schema-driven module settings editor.

Covers the ``/api/modules/schema`` endpoint plus the secret round-trip: the
Settings view masks configured secrets, an unchanged (masked) value is kept on
save, and a freshly typed value overwrites the stored one.

The fixture registers a handful of modules that declare a ``settings_schema``
and configures them *disabled* — the schema comes from the registered class, so
the endpoint still exposes it, while the hub skips instantiation (no network).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.modules import disk_usage as disk_usage_module
from backend.modules import heartbeat as heartbeat_module
from backend.modules import smart_lights as smart_lights_module
from backend.modules import top_processes as top_processes_module
from backend.modules.base import clear_registry, get_registry


@pytest.fixture(autouse=True)
def _registry():
    clear_registry()
    for m in (heartbeat_module, smart_lights_module, disk_usage_module, top_processes_module):
        importlib.reload(m)
    assert {"heartbeat", "smart_lights", "disk_usage", "top_processes"} <= set(get_registry())
    yield


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        """
server: { host: "127.0.0.1", port: 8765 }
default_theme: clean
modules:
  heartbeat: { enabled: true, interval: 0.05 }
  smart_lights:
    enabled: false
    govee: { api_key: "SECRET-GOVEE-KEY" }
    tuya: { region: "us" }
  disk_usage: { enabled: false, min_size_gb: 2.5 }
  top_processes: { enabled: false, limit: 8 }
pages:
  - id: main
    grid: { columns: "1fr", rows: "1fr", areas: ["hb"] }
    widgets:
      - { id: heartbeat, area: hb }
"""
    )
    from backend import main as main_mod
    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    return main_mod.create_app(cfg)


def _on_disk(tmp_path: Path) -> dict:
    return yaml.safe_load((tmp_path / "config.local.yaml").read_text())


def test_schema_endpoint_lists_module_fields(app):
    with TestClient(app) as client:
        r = client.get("/api/modules/schema")
        assert r.status_code == 200
        mods = r.json()["modules"]
        keys = {f["key"] for f in mods["smart_lights"]}
        assert {"govee.api_key", "tuya.client_id", "tuya.region"} <= keys
        api_key = next(f for f in mods["smart_lights"] if f["key"] == "govee.api_key")
        assert api_key["secret"] is True
        region = next(f for f in mods["smart_lights"] if f["key"] == "tuya.region")
        assert region["type"] == "select" and region["options"] == ["eu", "us", "cn", "in"]
        assert "disk_usage" in mods and "top_processes" in mods
        # Modules without extra fields aren't listed at all.
        assert "heartbeat" not in mods


def test_settings_view_masks_configured_secret(app):
    with TestClient(app) as client:
        body = client.get("/api/settings").json()
        sl = body["modules"]["smart_lights"]
        assert sl["govee"]["api_key"] == "***"  # secret masked
        assert sl["tuya"]["region"] == "us"  # non-secret preserved


def test_masked_secret_is_kept_on_save(app, tmp_path):
    with TestClient(app) as client:
        # Re-submit the masked value (user left it untouched) + a region change.
        r = client.post(
            "/api/settings",
            json={"modules": {"smart_lights": {"govee": {"api_key": "***"}, "tuya": {"region": "eu"}}}},
        )
        assert r.status_code == 200, r.text
        sl = _on_disk(tmp_path)["modules"]["smart_lights"]
        assert sl["govee"]["api_key"] == "SECRET-GOVEE-KEY"  # stored value survives
        assert sl["tuya"]["region"] == "eu"  # other change applied


def test_new_secret_overwrites_and_is_re_masked(app, tmp_path):
    with TestClient(app) as client:
        r = client.post(
            "/api/settings",
            json={"modules": {"smart_lights": {"govee": {"api_key": "NEW-KEY"}}}},
        )
        assert r.status_code == 200, r.text
        assert _on_disk(tmp_path)["modules"]["smart_lights"]["govee"]["api_key"] == "NEW-KEY"
        # The GET view re-masks the freshly stored secret.
        body = client.get("/api/settings").json()
        assert body["modules"]["smart_lights"]["govee"]["api_key"] == "***"


def test_non_secret_schema_field_roundtrips(app, tmp_path):
    with TestClient(app) as client:
        r = client.post("/api/settings", json={"modules": {"top_processes": {"limit": 12}}})
        assert r.status_code == 200, r.text
        assert _on_disk(tmp_path)["modules"]["top_processes"]["limit"] == 12
