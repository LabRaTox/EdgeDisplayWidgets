"""Tests for the tray icon, the app icon and the autostart switch.

None of these touch the real session: `systemctl` is replaced by a recorder,
and the units are written into a temp directory. The one thing deliberately
not tested is the D-Bus registration itself — that needs a session bus and a
panel, and mocking dbus-next would only assert that the mock was called.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import autostart, brand, tray

# ---------------------------------------------------------------- the icon


@pytest.mark.parametrize("size", [16, 22, 24, 48, 128])
def test_icon_has_the_requested_size_and_alpha(size: int):
    image = brand.icon_image(size)
    assert image.size == (size, size)
    assert image.mode == "RGBA"
    # The corners are rounded, so the very first pixel has to be transparent —
    # otherwise the icon would sit on a square block of colour in the panel.
    assert image.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize("size", [16, 18, 22, 24, 32])
def test_tiles_stay_separated_at_panel_sizes(size: int):
    """The gap between the two top tiles must survive the pixel grid.

    This is the failure this icon is most prone to: rounded down, the gap
    becomes zero and the two tiles merge into one white block that reads as a
    completely different symbol.
    """
    tiles, _ = brand._shapes(size)
    first, second = tiles[0], tiles[1]
    gap = second[0] - (first[0] + first[2])
    assert gap >= 1, f"tiles touch at {size}px"


def test_offline_icon_is_grey_but_same_shape():
    online = brand.icon_image(48)
    offline = brand.icon_image(48, online=False)
    assert online.size == offline.size
    # Same silhouette: the alpha channel is what makes the shape.
    assert online.getchannel("A").tobytes() == offline.getchannel("A").tobytes()
    # Different colour: at least the body must have lost its saturation.
    centre_online = online.getpixel((2, 24))[:3]
    centre_offline = offline.getpixel((2, 24))[:3]
    assert centre_online != centre_offline
    assert len(set(centre_offline)) <= 2  # grey: channels near-identical


def test_svg_and_pixmap_describe_the_same_shapes():
    svg = brand.icon_svg(64)
    tiles, _line = brand._shapes(64)
    assert svg.startswith("<svg")
    # One rect per tile, one for the sparkline, plus the body.
    assert svg.count("<rect") == len(tiles) + 2
    assert f'x="{tiles[0][0]}"' in svg


# ------------------------------------------------------------ the launcher


def test_settings_app_is_taken_from_the_environment(tmp_path: Path, monkeypatch):
    binary = tmp_path / "edgedash"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setenv("EDGE_GUI_BINARY", str(binary))
    assert tray.find_settings_app() == binary


def test_unexecutable_override_is_rejected(tmp_path: Path, monkeypatch):
    """A path that is not executable is not a launcher — say so instead of
    handing it to Popen, where it would fail long after the click."""
    binary = tmp_path / "edgedash"
    binary.write_text("not a program")
    binary.chmod(0o644)
    monkeypatch.setenv("EDGE_GUI_BINARY", str(binary))
    assert tray.find_settings_app() is None


@pytest.mark.parametrize(
    ("configured", "locale", "expected"),
    [
        ("de", "", "de"),
        ("en", "", "en"),
        ("auto", "de_DE.UTF-8", "de"),
        ("auto", "en_GB.UTF-8", "en"),
        ("auto", "fr_FR.UTF-8", "en"),  # no labels for it — fall back
        ("auto", "", "en"),
        ("nonsense", "", "en"),
    ],
)
def test_menu_language(configured: str, locale: str, expected: str, monkeypatch):
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(variable, raising=False)
    if locale:
        monkeypatch.setenv("LANG", locale)
    assert tray._resolve_language(configured) == expected


def test_tray_reports_the_connection_state():
    item = tray.SystemTray(url="http://127.0.0.1:8765", language="de")
    assert "Kein Dashboard" in item.tooltip()
    item.update(clients=1)
    assert "verbunden" in item.tooltip()
    # No D-Bus item exists, so this must not raise either.
    item.update(clients=0)


# ------------------------------------------------------------- autostart


@pytest.fixture
def systemctl(monkeypatch, tmp_path: Path):
    """Replaces systemctl with a recorder and redirects the unit directory."""
    calls: list[list[str]] = []
    states = {"enabled": "disabled"}

    def fake_run(args, **kwargs):
        calls.append(list(args))
        command = args[2] if len(args) > 2 else ""
        if command == "is-system-running":
            return subprocess.CompletedProcess(args, 0, "running\n", "")
        if command == "is-enabled":
            return subprocess.CompletedProcess(args, 0, states["enabled"] + "\n", "")
        if command == "enable":
            states["enabled"] = "enabled"
        elif command == "disable":
            states["enabled"] = "disabled"
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(autostart.subprocess, "run", fake_run)
    monkeypatch.setattr(autostart, "UNIT_DIR", tmp_path / "systemd")
    return calls


def test_status_is_off_when_units_are_not_enabled(systemctl):
    state = autostart.status()
    assert state.supported is True
    assert state.enabled is False
    assert state.units == []


def test_enabling_writes_both_units_and_enables_them(systemctl, tmp_path: Path):
    state = autostart.set_enabled(True)
    assert state.enabled is True

    for unit in autostart.UNITS:
        written = (tmp_path / "systemd" / unit).read_text()
        assert "__PROJECT_DIR__" not in written, "placeholder left in the unit"
        assert "__UV__" not in written
        assert str(autostart.ROOT) in written

    commands = [call[2] for call in systemctl]
    assert "daemon-reload" in commands
    # Both units in one call, backend first — the window follows what it talks to.
    enable = next(call for call in systemctl if call[2] == "enable")
    assert enable[3:] == list(autostart.UNITS)


def test_disabling_without_units_is_not_an_error(systemctl):
    """Nothing installed means the goal is already reached; systemctl disable
    on a unit that does not exist would only produce a confusing failure."""
    state = autostart.set_enabled(False)
    assert state.enabled is False
    assert not any(call[2] == "disable" for call in systemctl)


def test_missing_user_bus_is_reported_rather_than_raised(monkeypatch):
    def no_bus(args, **kwargs):
        return subprocess.CompletedProcess(
            args, 1, "", "Failed to connect to bus: No such file or directory"
        )

    monkeypatch.setattr(autostart.subprocess, "run", no_bus)
    state = autostart.status()
    assert state.supported is False
    assert state.enabled is False
    assert state.reason and "systemd" in state.reason

    with pytest.raises(autostart.AutostartUnavailable):
        autostart.set_enabled(True)


def test_systemctl_failure_becomes_an_error(systemctl, monkeypatch):
    def failing(args, **kwargs):
        if len(args) > 2 and args[2] == "is-system-running":
            return subprocess.CompletedProcess(args, 0, "running\n", "")
        if len(args) > 2 and args[2] == "enable":
            return subprocess.CompletedProcess(args, 1, "", "Unit not found.")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(autostart.subprocess, "run", failing)
    with pytest.raises(autostart.AutostartError, match="Unit not found"):
        autostart.set_enabled(True)


# --------------------------------------------------------------- the API


@pytest.fixture
def app(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        """
server: { host: "127.0.0.1", port: 8765 }
default_theme: clean
modules: {}
pages:
  - id: main
    grid: { columns: "1fr", rows: "1fr", areas: ["hb"] }
    widgets: []
"""
    )
    from backend import main as main_mod

    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    return main_mod.create_app(cfg)


def test_api_reports_autostart_state(app, monkeypatch):
    monkeypatch.setattr(
        autostart,
        "status",
        lambda: autostart.AutostartStatus(
            supported=True, enabled=True, units=list(autostart.UNITS)
        ),
    )
    with TestClient(app) as client:
        body = client.get("/api/autostart").json()
    assert body["enabled"] is True
    assert body["units"] == list(autostart.UNITS)


def test_api_switches_autostart(app, monkeypatch):
    seen: list[bool] = []

    def fake_set(enabled: bool):
        seen.append(enabled)
        return autostart.AutostartStatus(supported=True, enabled=enabled, units=[])

    monkeypatch.setattr(autostart, "set_enabled", fake_set)
    with TestClient(app) as client:
        response = client.post("/api/autostart", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert seen == [False]


def test_api_reports_a_missing_session_as_conflict(app, monkeypatch):
    def unavailable(enabled: bool):
        raise autostart.AutostartUnavailable("No systemd user session reachable.")

    monkeypatch.setattr(autostart, "set_enabled", unavailable)
    with TestClient(app) as client:
        response = client.post("/api/autostart", json={"enabled": True})
    # 409, not 500: nothing is broken, the machine simply cannot do this.
    assert response.status_code == 409
    assert "systemd" in response.json()["detail"]


def test_api_rejects_a_body_without_the_flag(app):
    with TestClient(app) as client:
        assert client.post("/api/autostart", json={}).status_code == 422


def test_tray_is_not_started_by_merely_creating_the_app(app, monkeypatch):
    """The test suite builds apps constantly; none of them may end up in the
    panel. The tray is opt-in through EDGE_TRAY, which only `main()` sets."""
    started = []
    monkeypatch.delenv("EDGE_TRAY", raising=False)

    async def record():
        started.append(True)
        return False

    monkeypatch.setattr(app.state.tray, "start", record)
    with TestClient(app):
        pass
    assert started == []
