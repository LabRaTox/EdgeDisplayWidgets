"""Tests for how the kiosk window finds a widget's QML file.

The window has no table of widgets. It turns the id from the layout into a
file name and loads that, so a new widget needs no entry anywhere in the
window. These tests pin the naming rule down, and that an id from the config
cannot become a path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shell" / "qml_kiosk"))

from views import view_path, widget_id  # noqa: E402

VIEWS = ROOT / "shell" / "qml_kiosk" / "qml" / "widgets"
MANIFESTS = ROOT / "widgets"


@pytest.mark.parametrize(
    "wid,expected",
    [
        ("cpu", "Cpu.qml"),
        ("disk_usage", "DiskUsage.qml"),
        ("top_processes", "TopProcesses.qml"),
        ("sensor_focus", "SensorFocus.qml"),
    ],
)
def test_id_becomes_a_file_name(wid: str, expected: str):
    path = view_path(wid)
    assert path is not None and path.name == expected


def test_unknown_widget_has_no_view():
    assert view_path("moonphase") is None


@pytest.mark.parametrize(
    "wid",
    [
        "",
        "../../etc/passwd",
        "Cpu",            # the file is CamelCase, the id is not
        "cpu/../../x",
        "cpu.qml",
        "-cpu",
        "cpu widget",
    ],
)
def test_an_id_cannot_become_a_path(wid: str):
    """The config is a file anyone can edit, so the id is checked before it
    is turned into a file name."""
    assert view_path(wid) is None


def test_every_manifest_has_a_view():
    """A widget the editor offers but the window cannot draw is a tile that
    silently stays empty on the display."""
    missing = [
        path.stem
        for path in sorted(MANIFESTS.glob("*.json"))
        if view_path(path.stem) is None
    ]
    assert not missing, f"no QML file for: {', '.join(missing)}"


def test_every_view_has_a_manifest():
    """The other way round: a view without a manifest cannot be placed,
    because the layout editor never lists it."""
    from views import SHARED

    orphans = [
        path.name
        for path in sorted(VIEWS.glob("*.qml"))
        if path.stem not in SHARED and not (MANIFESTS / f"{widget_id(path.name)}.json").is_file()
    ]
    assert not orphans, f"no manifest for: {', '.join(orphans)}"
