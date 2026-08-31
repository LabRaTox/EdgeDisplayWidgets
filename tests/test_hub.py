"""Smoke tests for config, registry, and the Hub bootstrap layer."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.config import AppConfig, ModuleConfig, load_config
from backend.hub import Hub
from backend.modules.base import Module, clear_registry, register_module


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    yield
    clear_registry()


# ---------------------------------------------------------------- registry tests

def test_register_module_requires_name():
    class Anon(Module):
        async def poll(self):
            return {}

    with pytest.raises(ValueError):
        register_module(Anon)


def test_register_module_rejects_duplicates():
    @register_module
    class A(Module):
        name = "dupe"

        async def poll(self):
            return {}

    class B(Module):
        name = "dupe"

        async def poll(self):
            return {}

    with pytest.raises(ValueError):
        register_module(B)


def test_register_module_idempotent_for_same_class():
    @register_module
    class Once(Module):
        name = "once"

        async def poll(self):
            return {}

    # Re-registering the same class is a no-op (not an error).
    register_module(Once)


# ---------------------------------------------------------------- config tests

def test_load_config_file(tmp_path: Path):
    raw = """
server: { host: "0.0.0.0", port: 9000 }
default_theme: clean
modules:
  demo: { enabled: true, interval: 0.5 }
pages:
  - id: p1
    grid: { columns: "1fr", rows: "1fr", areas: ["a"] }
    widgets:
      - { id: w, area: a }
"""
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(raw)
    cfg = load_config(cfg_path)
    assert cfg.server.port == 9000
    assert cfg.default_theme == "clean"
    assert cfg.modules["demo"].interval == 0.5
    assert cfg.pages[0].widgets[0].area == "a"


def test_widget_area_must_exist(tmp_path: Path):
    raw = """
pages:
  - id: bad
    grid: { columns: "1fr", rows: "1fr", areas: ["a"] }
    widgets:
      - { id: w, area: nonexistent }
"""
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(raw)
    with pytest.raises(Exception):
        load_config(cfg_path)


def test_legacy_areas_format_translates_to_col_row(tmp_path: Path):
    raw = """
pages:
  - id: legacy
    grid:
      columns: "1fr 1fr 1fr"
      rows: "1fr 1fr"
      areas:
        - "a a b"
        - "c b b"
    widgets:
      - { id: aw, area: a }
      - { id: bw, area: b }
      - { id: cw, area: c }
"""
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(raw)
    cfg = load_config(cfg_path)
    page = cfg.pages[0]
    by_id = {w.id: w for w in page.widgets}
    # 'a' spans top-left 2 columns, 1 row
    assert (by_id["aw"].col, by_id["aw"].row) == (1, 1)
    assert (by_id["aw"].colspan, by_id["aw"].rowspan) == (2, 1)
    # 'b' spans the right column over 2 rows + bottom-middle
    assert (by_id["bw"].col, by_id["bw"].row) == (2, 1)
    assert (by_id["bw"].colspan, by_id["bw"].rowspan) == (2, 2)
    # 'c' is single cell bottom-left
    assert (by_id["cw"].col, by_id["cw"].row) == (1, 2)
    assert (by_id["cw"].colspan, by_id["cw"].rowspan) == (1, 1)


def test_col_row_format_accepted_directly(tmp_path: Path):
    raw = """
pages:
  - id: modern
    grid: { columns: "1fr 1fr", rows: "1fr 1fr" }
    widgets:
      - { id: a, col: 1, row: 1, colspan: 2, rowspan: 1 }
      - { id: b, col: 1, row: 2 }
"""
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(raw)
    cfg = load_config(cfg_path)
    page = cfg.pages[0]
    by_id = {w.id: w for w in page.widgets}
    assert by_id["a"].colspan == 2
    assert by_id["b"].col == 1 and by_id["b"].row == 2


# ---------------------------------------------------------------- hub tests

def test_hub_instantiates_only_enabled_modules():
    @register_module
    class Tick(Module):
        name = "tick"

        async def poll(self):
            return {"v": 1}

    @register_module
    class Off(Module):
        name = "off"

        async def poll(self):
            return {"v": 0}

    cfg = AppConfig(
        modules={
            "tick": ModuleConfig(enabled=True, interval=0.1),
            "off": ModuleConfig(enabled=False),
        }
    )
    hub = Hub(cfg)
    hub._instantiate()
    assert "tick" in hub.modules
    assert "off" not in hub.modules
    assert hub.modules["tick"].interval == 0.1


@pytest.mark.asyncio
async def test_hub_polls_caches_and_replays_to_new_clients():
    counter = {"n": 0}

    @register_module
    class Tick(Module):
        name = "tick"
        default_interval = 0.05

        async def poll(self):
            counter["n"] += 1
            return {"counter": counter["n"]}

    cfg = AppConfig(modules={"tick": ModuleConfig(enabled=True, interval=0.05)})
    hub = Hub(cfg)
    await hub.start()
    try:
        # Wait for at least one poll cycle.
        for _ in range(40):
            if hub.snapshot():
                break
            await asyncio.sleep(0.02)
        assert "tick" in hub.snapshot()

        # New client should receive the cached snapshot immediately on connect.
        class FakeWS:
            def __init__(self):
                self.sent: list[str] = []

            async def send_text(self, data: str):
                self.sent.append(data)

            async def close(self, code: int = 1000):
                pass

        ws = FakeWS()
        await hub.connect(ws)
        assert len(ws.sent) >= 1
        first = json.loads(ws.sent[0])
        assert first["module"] == "tick"
        assert "counter" in first["data"]
        await hub.disconnect(ws)
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_hub_keeps_polling_when_a_module_raises():
    state = {"calls": 0, "errors": 0}

    @register_module
    class Flaky(Module):
        name = "flaky"
        default_interval = 0.05

        async def poll(self):
            state["calls"] += 1
            if state["calls"] % 2 == 0:
                state["errors"] += 1
                raise RuntimeError("boom")
            return {"calls": state["calls"]}

    cfg = AppConfig(modules={"flaky": ModuleConfig(enabled=True, interval=0.05)})
    hub = Hub(cfg)
    await hub.start()
    try:
        for _ in range(60):
            if state["calls"] >= 4:
                break
            await asyncio.sleep(0.05)
        assert state["calls"] >= 4
        assert state["errors"] >= 1
        # Last successful payload still cached.
        assert hub.snapshot()["flaky"]["data"]["calls"] >= 1
    finally:
        await hub.stop()


# ---------------------------------------------------------------- dedupe / push

class _CollectingWS:
    """Minimal WSLike that records every frame it was sent."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        pass

    def frames(self, module: str | None = None) -> list[dict]:
        out = [json.loads(s) for s in self.sent]
        return [f for f in out if module is None or f.get("module") == module]


@pytest.mark.asyncio
async def test_unchanged_payload_is_not_rebroadcast():
    @register_module
    class Constant(Module):
        name = "constant"
        default_interval = 0.02

        async def poll(self):
            return {"value": 1}

    cfg = AppConfig(modules={"constant": ModuleConfig(enabled=True, interval=0.02)})
    hub = Hub(cfg)
    await hub.start()
    try:
        # Connect only after the first poll landed, so the snapshot replay is
        # the one and only frame this client should ever see.
        for _ in range(50):
            if hub.snapshot():
                break
            await asyncio.sleep(0.01)
        ws = _CollectingWS()
        await hub.connect(ws)
        sent_on_connect = len(ws.frames("constant"))
        assert sent_on_connect == 1
        await asyncio.sleep(0.2)  # ~10 polls, all with identical data
        assert len(ws.frames("constant")) == sent_on_connect
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_sample_stream_module_broadcasts_every_poll():
    @register_module
    class Stream(Module):
        name = "stream"
        default_interval = 0.02
        dedupe = False

        async def poll(self):
            return {"value": 1}

    cfg = AppConfig(modules={"stream": ModuleConfig(enabled=True, interval=0.02)})
    hub = Hub(cfg)
    await hub.start()
    try:
        ws = _CollectingWS()
        await hub.connect(ws)
        before = len(ws.frames("stream"))
        await asyncio.sleep(0.2)
        assert len(ws.frames("stream")) > before + 2
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_module_can_emit_between_polls():
    @register_module
    class Pushy(Module):
        name = "pushy"
        default_interval = 60.0  # would never fire during the test

        async def poll(self):
            return {"source": "poll"}

    cfg = AppConfig(modules={"pushy": ModuleConfig(enabled=True, interval=60.0)})
    hub = Hub(cfg)
    await hub.start()
    try:
        ws = _CollectingWS()
        await hub.connect(ws)
        await hub.modules["pushy"].emit({"source": "signal"})
        pushed = [f for f in ws.frames("pushy") if f["data"] == {"source": "signal"}]
        assert pushed, "emitted payload never reached the client"
        # And it becomes the value a joining client is handed.
        assert hub.snapshot()["pushy"]["data"] == {"source": "signal"}
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_publish_sends_a_control_frame():
    cfg = AppConfig(modules={})
    hub = Hub(cfg)
    await hub.start()
    try:
        ws = _CollectingWS()
        await hub.connect(ws)
        await hub.publish("settings", settings={"default_theme": "toxic"})
        frames = [json.loads(s) for s in ws.sent]
        control = [f for f in frames if f.get("event") == "settings"]
        assert control, "control frame never arrived"
        assert control[0]["settings"]["default_theme"] == "toxic"
        assert "module" not in control[0]  # must not look like module data
    finally:
        await hub.stop()
