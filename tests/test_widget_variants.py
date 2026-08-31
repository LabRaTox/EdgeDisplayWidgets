"""Tests for the widget variant declaration.

A widget offers display variants by declaring them in its own JS file
(`static variants = [...]`); the backend reads that when it scans the widget
directory, and the layout editor turns it into a picker. These tests pin the
parsing down, because it is the one place where Python looks at JavaScript.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import _widget_variants, create_app


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "w.js"
    path.write_text(body, encoding="utf-8")
    return path


def test_reads_a_declaration(tmp_path: Path):
    path = write(
        tmp_path,
        'class W {\n  static modules = ["system"];\n'
        '  static variants = ["compact", "wide"];\n}\n',
    )
    assert _widget_variants(path) == ["compact", "wide"]


@pytest.mark.parametrize(
    "declaration",
    [
        'static variants=["compact"]',
        "static  variants = [ 'compact' ]",
        'static variants = [\n    "compact",\n  ]',
    ],
)
def test_tolerates_the_usual_spellings(tmp_path: Path, declaration: str):
    assert _widget_variants(write(tmp_path, declaration)) == ["compact"]


def test_a_widget_without_variants_offers_none(tmp_path: Path):
    assert _widget_variants(write(tmp_path, "class W {}\n")) == []


def test_an_empty_declaration_offers_none(tmp_path: Path):
    assert _widget_variants(write(tmp_path, "static variants = [];")) == []


def test_a_missing_file_is_not_an_error(tmp_path: Path):
    """The directory is scanned live; a file can vanish between listing it and
    reading it, and that must not take the endpoint down."""
    assert _widget_variants(tmp_path / "gone.js") == []


def test_every_shipped_widget_declares_something_parseable():
    """Guards the real files: a variant declared in JS but written in a way
    the parser misses would silently never appear in the editor."""
    widgets = Path("frontend/js/widgets")
    declared = {
        path.stem: _widget_variants(path)
        for path in widgets.glob("*.js")
        if "static variants" in path.read_text(encoding="utf-8")
    }
    assert declared, "no widget declares variants any more — parser or files changed"
    for name, variants in declared.items():
        assert variants, f"{name}.js declares variants the parser cannot read"


def test_metric_widgets_offer_compact():
    """The variant the layout editor and the docs promise."""
    widgets = Path("frontend/js/widgets")
    for name in ("cpu", "gpu", "ram", "network", "sensors", "disk_usage"):
        assert "compact" in _widget_variants(widgets / f"{name}.js"), name


def test_endpoint_lists_widgets_and_their_variants(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        """
server: { host: "127.0.0.1", port: 8765 }
default_theme: clean
modules: {}
pages:
  - id: main
    grid: { columns: "1fr", rows: "1fr", areas: [] }
    widgets: []
"""
    )
    from backend import main as main_mod

    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    with TestClient(create_app(cfg)) as client:
        body = client.get("/api/widgets").json()

    assert "cpu" in body["widgets"]
    assert body["variants"]["cpu"] == ["compact"]
    # Widgets with a single look stay out of the map rather than carrying an
    # empty list — the editor checks for a key, not for a length.
    assert "clock" not in body["variants"]
