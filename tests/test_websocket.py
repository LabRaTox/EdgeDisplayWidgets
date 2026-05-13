"""End-to-end WebSocket plumbing test using the real heartbeat module.

The autouse fixture forces a fresh import of `backend.modules.heartbeat`
so the registry is populated even after `clear_registry()` calls in
`test_hub.py` (the heartbeat module body would otherwise stay cached
without re-running its `@register_module` decorator).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
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
def app(tmp_path: Path):
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
    from backend.main import create_app

    return create_app(cfg)


def test_api_config_lists_active_modules(app):
    with TestClient(app) as client:
        res = client.get("/api/config")
        assert res.status_code == 200
        body = res.json()
        assert body["default_theme"] == "clean"
        assert "heartbeat" in body["modules"]
        assert body["pages"][0]["id"] == "main"


def test_websocket_replays_snapshot_to_new_client(app):
    with TestClient(app) as client:
        # Hub started on TestClient enter; heartbeat polls every 50ms.
        # On WS connect the hub replays the cached snapshot, so we should
        # see a heartbeat frame promptly without waiting a full interval.
        with client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
            assert msg["module"] == "heartbeat"
            assert msg["data"]["seq"] >= 1
            assert msg["data"]["uptime"] >= 0.0
            assert "ts" in msg


def test_websocket_streams_subsequent_polls(app):
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            seqs = []
            for _ in range(3):
                frame = ws.receive_json()
                if frame["module"] != "heartbeat":
                    continue
                seqs.append(frame["data"]["seq"])
        assert len(seqs) >= 3
        # seq is monotonically increasing
        assert seqs == sorted(seqs)
        assert seqs[-1] > seqs[0]


def test_api_themes_lists_discovered_files(app):
    with TestClient(app) as client:
        res = client.get("/api/themes")
        assert res.status_code == 200
        body = res.json()
        # Theme files live in frontend/css/themes/*.css; the dashboard ships
        # with cyberpunk, clean, steampunk, light. Anything else found there
        # is also fair game (the endpoint discovers automatically).
        assert {"cyberpunk", "clean", "steampunk", "light"}.issubset(set(body["themes"]))
        assert body["default"] == "clean"  # comes from the test app fixture


def test_snapshot_endpoint_after_a_poll(app):
    with TestClient(app) as client:
        # Pull one WS frame to ensure a poll has run.
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
        snap = client.get("/api/snapshot").json()
        assert "heartbeat" in snap
        assert snap["heartbeat"]["data"]["seq"] >= 1
