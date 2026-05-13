"""Tests for the Settings UI plumbing: GET/POST /api/settings + hub hot-reload.

The integration tests use a temp config and a temp 'local' override path so
they don't touch the real config.local.yaml in the repo.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.modules import heartbeat as heartbeat_module
from backend.modules.base import clear_registry, get_registry


@pytest.fixture(autouse=True)
def _ensure_heartbeat_registered():
    clear_registry()
    importlib.reload(heartbeat_module)
    assert "heartbeat" in get_registry()
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
pages:
  - id: main
    grid: { columns: "1fr", rows: "1fr", areas: ["hb"] }
    widgets:
      - { id: heartbeat, area: hb }
"""
    )
    # Redirect LOCAL_CONFIG to the tmp dir so the test can't pollute the repo.
    from backend import main as main_mod
    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    return main_mod.create_app(cfg)


def test_get_settings_returns_modules_and_theme(app):
    with TestClient(app) as client:
        r = client.get("/api/settings")
        assert r.status_code == 200
        body = r.json()
        assert body["default_theme"] == "clean"
        assert "heartbeat" in body["modules"]
        assert body["modules"]["heartbeat"]["enabled"] is True


def test_post_settings_persists_to_local_yaml_and_hot_reloads(app, tmp_path):
    with TestClient(app) as client:
        # Toggle heartbeat off via the API
        r = client.post(
            "/api/settings",
            json={"modules": {"heartbeat": {"enabled": False}}},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["settings"]["modules"]["heartbeat"]["enabled"] is False

        # Persistence: config.local.yaml should now exist with the change.
        local = tmp_path / "config.local.yaml"
        assert local.is_file()
        on_disk = yaml.safe_load(local.read_text())
        assert on_disk["modules"]["heartbeat"]["enabled"] is False

        # Hot-reload: the running hub must have dropped heartbeat.
        assert "heartbeat" not in app.state.hub.modules

        # And /api/config now reports zero active modules.
        r = client.get("/api/config")
        assert "heartbeat" not in r.json()["modules"]


def test_post_settings_can_re_enable_a_module(app):
    with TestClient(app) as client:
        # Disable, then re-enable
        client.post(
            "/api/settings",
            json={"modules": {"heartbeat": {"enabled": False}}},
        )
        r = client.post(
            "/api/settings",
            json={"modules": {"heartbeat": {"enabled": True, "interval": 0.1}}},
        )
        assert r.status_code == 200
        assert r.json()["settings"]["modules"]["heartbeat"]["interval"] == 0.1
        assert "heartbeat" in app.state.hub.modules
        assert app.state.hub.modules["heartbeat"].interval == 0.1


def test_post_settings_validates_payload_through_pydantic(app):
    with TestClient(app) as client:
        # interval=0 is invalid (gt=0 in ModuleConfig)
        r = client.post(
            "/api/settings",
            json={"modules": {"heartbeat": {"interval": 0}}},
        )
        assert r.status_code == 400
        assert "validation" in r.json()["detail"].lower()


def test_post_settings_rejects_non_object_body(app):
    with TestClient(app) as client:
        r = client.post(
            "/api/settings",
            content="[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400


def test_post_settings_can_change_default_theme(app):
    with TestClient(app) as client:
        r = client.post("/api/settings", json={"default_theme": "cyberpunk"})
        assert r.status_code == 200
        assert app.state.config.default_theme == "cyberpunk"
        # Reflected in /api/config too
        cfg = client.get("/api/config").json()
        assert cfg["default_theme"] == "cyberpunk"


def test_post_settings_can_save_new_pages_layout(app):
    with TestClient(app) as client:
        new_pages = [
            {
                "id": "main",
                "title": "Main",
                "grid": {"columns": "1fr 1fr", "rows": "1fr 1fr"},
                "widgets": [
                    {"id": "heartbeat", "col": 1, "row": 1, "colspan": 2, "rowspan": 1},
                    {"id": "heartbeat", "col": 1, "row": 2},
                ],
            },
        ]
        r = client.post("/api/settings", json={"pages": new_pages})
        assert r.status_code == 200, r.text
        cfg = client.get("/api/config").json()
        assert len(cfg["pages"]) == 1
        widgets = cfg["pages"][0]["widgets"]
        assert widgets[0]["colspan"] == 2
        assert widgets[1]["row"] == 2


def test_api_widgets_lists_files():
    """Smoke-test against the real frontend dir."""
    from backend.main import create_app

    a = create_app()
    with TestClient(a) as client:
        r = client.get("/api/widgets")
        assert r.status_code == 200
        names = r.json()["widgets"]
        assert {"clock", "heartbeat", "cpu", "gpu", "ram", "network", "weather", "sensors", "media"}.issubset(set(names))


def test_resolve_config_path_prefers_local_when_present(tmp_path, monkeypatch):
    from backend import main as main_mod

    # Sandbox both candidates
    fake_local = tmp_path / "config.local.yaml"
    fake_default = tmp_path / "config.yaml"
    fake_default.write_text("server: {}")
    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", fake_local)
    monkeypatch.setattr(main_mod, "DEFAULT_CONFIG", fake_default)
    monkeypatch.delenv("EDGE_CONFIG", raising=False)

    # No local file -> falls back to default
    assert main_mod.resolve_config_path() == fake_default

    # Once local exists, it wins
    fake_local.write_text("server: {}")
    assert main_mod.resolve_config_path() == fake_local

    # Explicit override beats both
    explicit = tmp_path / "explicit.yaml"
    assert main_mod.resolve_config_path(explicit) == explicit
