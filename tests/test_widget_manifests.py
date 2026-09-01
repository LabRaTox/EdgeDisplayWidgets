"""Tests for the widget manifests.

A widget is registered by having a file in `widgets/`. The manifest declares
which modules it consumes, its display variants and its editable options; the
backend validates the options against `SettingField` and hands them to the
layout editor, filling in any list the schema said to source from a module.

These tests pin down that a broken manifest costs that widget its options
rather than taking the picker down, and that the sensor list is substituted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.main import _manifest_options, _sensor_choices, _widget_manifest

MANIFESTS = Path("widgets")


def write(tmp_path: Path, body: Any) -> Path:
    """One manifest file, from a string as-is or from a value as JSON."""
    path = tmp_path / "w.json"
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return path


def options_of(path: Path) -> list[dict[str, Any]]:
    return _manifest_options(path, _widget_manifest(path))


def test_manifest_without_options(tmp_path: Path):
    assert options_of(write(tmp_path, {"modules": ["system"]})) == []


def test_unreadable_manifest_is_ignored(tmp_path: Path):
    """The directory is scanned live; a file can vanish between listing it and
    reading it, and that must not take the endpoint down."""
    assert _widget_manifest(tmp_path / "gone.json") == {}


def test_reads_a_schema(tmp_path: Path):
    path = write(tmp_path, {"options": [
        {"key": "display", "type": "select", "label_key": "l",
         "default": "line", "options": ["line", "circle"]},
    ]})
    fields = options_of(path)
    assert len(fields) == 1
    assert fields[0]["key"] == "display"
    assert fields[0]["options"] == ["line", "circle"]
    # Absent keys still come back, so the editor can rely on their presence.
    assert fields[0]["option_labels"] is None


def test_broken_json_is_ignored(tmp_path: Path):
    assert _widget_manifest(write(tmp_path, "{not json")) == {}


def test_wrong_shape_is_ignored(tmp_path: Path):
    assert _widget_manifest(write(tmp_path, ["not", "an", "object"])) == {}


def test_options_must_be_a_list(tmp_path: Path):
    assert options_of(write(tmp_path, {"options": {"key": "x"}})) == []


def test_invalid_field_is_ignored(tmp_path: Path):
    # `type` is not one of the known inputs, so the whole block is refused
    # rather than handing the editor a field it cannot render.
    assert options_of(write(tmp_path, {"options": [
        {"key": "x", "type": "colour", "label_key": "l"},
    ]})) == []


class FakeHub:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def snapshot(self) -> dict[str, Any]:
        return {"sensors": {"module": "sensors", "data": self._payload, "ts": 0}}


def test_sensor_choices_pair_ids_with_names():
    ids, labels = _sensor_choices(FakeHub({
        "available": True,
        "readings": [
            {"id": "hwmon3/k10temp:1", "display_chip": "CPU", "display_label": "Package"},
            {"id": "hwmon7/amdgpu:1", "chip": "amdgpu", "label": "edge"},
        ],
    }))
    # The empty first entry is how a field is cleared again.
    assert ids == ["", "hwmon3/k10temp:1", "hwmon7/amdgpu:1"]
    assert labels == ["", "CPU Package", "amdgpu edge"]


def test_sensor_choices_when_unavailable():
    ids, labels = _sensor_choices(FakeHub({"available": False, "reason": "no sensors"}))
    assert ids == [""] and labels == [""]


def test_every_shipped_manifest_is_readable():
    """A manifest the parser cannot read costs that widget its variants and
    options silently, which is exactly the kind of thing nobody notices."""
    files = sorted(MANIFESTS.glob("*.json"))
    assert files, "no widget manifests found"
    for path in files:
        assert _widget_manifest(path), f"{path.name} is empty or unreadable"


def test_metric_widgets_offer_compact():
    """The variant the layout editor and the docs promise."""
    for name in ("cpu", "gpu", "ram", "network", "sensors", "disk_usage"):
        manifest = _widget_manifest(MANIFESTS / f"{name}.json")
        assert "compact" in manifest.get("variants", []), name


def test_shipped_sensor_focus_schema_is_valid():
    """The schema this repository ships has to survive its own validation."""
    path = MANIFESTS / "sensor_focus.json"
    fields = options_of(path)
    by_key = {f["key"]: f for f in fields}
    # Both sensors offer the same things, so neither is a second-class one.
    for side in ("a", "b"):
        assert by_key[f"sensor_{side}"]["options_source"] == "sensors"
        assert by_key[f"label_{side}"]["type"] == "text"
        assert by_key[f"color_{side}"]["type"] == "color"
        # Empty is what "use the theme's colour" and "use the sensor's own
        # name" look like, so neither may carry a value as its default.
        assert by_key[f"color_{side}"]["default"] == ""
        assert by_key[f"label_{side}"]["default"] == ""
    assert by_key["display"]["options"] == ["line", "circle"]
    assert by_key["max_c"]["default"] == 100
    assert by_key["show_unit"]["default"] is True


def test_color_is_a_known_field_type(tmp_path: Path):
    """The editor has to be handed a type it can render."""
    fields = options_of(write(tmp_path, {"options": [
        {"key": "tint", "type": "color", "label_key": "l", "default": ""},
    ]}))
    assert fields and fields[0]["type"] == "color"
