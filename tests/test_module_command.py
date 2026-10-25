"""The command endpoint: how a widget hands an action to its own module."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from backend.modules.base import Module, clear_registry, register_module


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clear_registry()

    @register_module
    class Echo(Module):
        name: ClassVar[str] = "echo"
        default_interval: ClassVar[float] = 60

        async def poll(self) -> dict[str, Any]:
            return {}

        async def command(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
            if action == "echo":
                return {"ok": True, "args": args}
            if action == "fail":
                return {"ok": False, "error": "nope"}
            raise NotImplementedError

    @register_module
    class Mute(Module):
        name: ClassVar[str] = "mute"
        default_interval: ClassVar[float] = 60

        async def poll(self) -> dict[str, Any]:
            return {}

    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        """
server: { host: "127.0.0.1", port: 8765 }
default_theme: clean
modules:
  echo: { enabled: true }
  mute: { enabled: true }
pages: []
"""
    )
    from backend import main as main_mod
    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    yield main_mod.create_app(cfg)
    clear_registry()


def test_command_reaches_module_with_body(app):
    with TestClient(app) as client:
        r = client.post("/api/modules/echo/command/echo", json={"channel": "42"})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "args": {"channel": "42"}}


def test_command_without_body(app):
    with TestClient(app) as client:
        r = client.post("/api/modules/echo/command/echo")
        assert r.status_code == 200
        assert r.json()["args"] == {}


def test_failed_command_is_400(app):
    with TestClient(app) as client:
        r = client.post("/api/modules/echo/command/fail", json={})
        assert r.status_code == 400
        assert r.json()["error"] == "nope"


@pytest.mark.parametrize("path", [
    "/api/modules/echo/command/unknown",       # action the module does not know
    "/api/modules/mute/command/echo",          # module without commands
    "/api/modules/absent/command/echo",        # module not running
])
def test_unknown_is_404(app, path):
    with TestClient(app) as client:
        assert client.post(path, json={}).status_code == 404


def test_body_must_be_object(app):
    with TestClient(app) as client:
        assert client.post("/api/modules/echo/command/echo", json=[1]).status_code == 400


def test_new_template_modules_join_an_old_local_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A module added to config.yaml later runs for a config.local.yaml that
    predates it; one the local file mentions, even switched off, stays put."""
    from backend import main as main_mod

    template = tmp_path / "config.yaml"
    template.write_text("""
modules:
  echo: { enabled: true, interval: 5 }
  mute: { enabled: true }
pages: []
""")
    local = tmp_path / "config.local.yaml"
    local.write_text("""
modules:
  mute: { enabled: false }
pages: []
""")
    monkeypatch.setattr(main_mod, "DEFAULT_CONFIG", template)
    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", local)
    cfg = main_mod._add_new_modules(main_mod.load_config(local), local)
    assert cfg.modules["echo"].enabled is True and cfg.modules["echo"].interval == 5
    assert cfg.modules["mute"].enabled is False
    # An explicit config is taken as it is.
    other = tmp_path / "other.yaml"
    other.write_text(local.read_text())
    assert "echo" not in main_mod._add_new_modules(main_mod.load_config(other), other).modules
