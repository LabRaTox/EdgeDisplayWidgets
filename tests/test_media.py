"""Tests for the MediaModule.

Covers the parts that don't require a live D-Bus session:
  - ArtCache: file://, data:, http(s):// fetching, LRU eviction
  - Player picking: most-recently-active selection
  - Disabled paths: dbus-next missing, session bus connect failure
  - Action gating when no player is available

A real D-Bus integration test would need a session bus + a fake MPRIS
service; out of scope for the suite.
"""

from __future__ import annotations

import asyncio
import sys
import time
import urllib.parse
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.modules.base import clear_registry, register_module
from backend.modules.media import (
    MPRIS_PREFIX,
    ArtCache,
    MediaModule,
    _Player,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    register_module(MediaModule)
    yield
    clear_registry()


# ---------------------------------------------------------------- ArtCache

@pytest.mark.asyncio
async def test_art_cache_handles_file_url(tmp_path: Path):
    img = tmp_path / "cover.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-bytes")
    cache = ArtCache()
    url = "file://" + urllib.parse.quote(str(img))
    token = await cache.store(url)
    assert token is not None
    item = cache.get(token)
    assert item is not None
    data, mime = item
    assert data.startswith(b"\x89PNG")
    assert mime == "image/png"


@pytest.mark.asyncio
async def test_art_cache_handles_data_url():
    cache = ArtCache()
    url = "data:image/png;base64,iVBORw0KGgo="  # base64 of "PNG hdr"
    token = await cache.store(url)
    assert token is not None
    data, mime = cache.get(token)
    assert mime == "image/png"
    assert data.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_art_cache_dedups_same_url():
    cache = ArtCache()
    url = "data:image/png;base64,iVBORw0KGgo="
    t1 = await cache.store(url)
    t2 = await cache.store(url)
    assert t1 == t2
    assert len(cache._entries) == 1


@pytest.mark.asyncio
async def test_art_cache_lru_eviction(tmp_path: Path):
    cache = ArtCache(capacity=3)
    files = []
    for i in range(5):
        p = tmp_path / f"art{i}.png"
        p.write_bytes(f"png-{i}".encode())
        files.append("file://" + urllib.parse.quote(str(p)))
    tokens = []
    for url in files:
        tok = await cache.store(url)
        tokens.append(tok)
    # Only the last 3 should remain.
    assert cache.get(tokens[0]) is None
    assert cache.get(tokens[1]) is None
    for tok in tokens[2:]:
        assert cache.get(tok) is not None


@pytest.mark.asyncio
async def test_art_cache_unsupported_scheme_returns_none():
    cache = ArtCache()
    token = await cache.store("ftp://example.com/cover.jpg")
    assert token is None


@pytest.mark.asyncio
async def test_art_cache_missing_file_returns_none(tmp_path: Path):
    cache = ArtCache()
    token = await cache.store("file:///does/not/exist.png")
    assert token is None


# ---------------------------------------------------------------- player pick

def _make_player(name: str, status: str = "Stopped", last_active: float = 0.0) -> _Player:
    p = _Player(MPRIS_PREFIX + name)
    p.identity = name
    p.playback_status = status
    p.last_active_ts = last_active
    return p


def test_pick_active_returns_none_when_empty():
    mod = MediaModule({})
    assert mod.pick_active() is None


def test_pick_active_prefers_most_recent_playing():
    mod = MediaModule({})
    now = time.time()
    spotify = _make_player("Spotify", status="Playing", last_active=now)
    vlc = _make_player("VLC", status="Paused", last_active=now - 60)
    mod._players = {p.bus_name: p for p in (vlc, spotify)}
    assert mod.pick_active() is spotify


def test_pick_active_falls_back_to_paused_recent():
    mod = MediaModule({})
    now = time.time()
    spotify = _make_player("Spotify", status="Stopped", last_active=now - 30)
    vlc = _make_player("VLC", status="Paused", last_active=now)
    mod._players = {p.bus_name: p for p in (vlc, spotify)}
    # All last_active>0; most recent wins (vlc), even though paused
    assert mod.pick_active() is vlc


def test_pick_active_fallback_when_nothing_was_ever_active():
    mod = MediaModule({})
    a = _make_player("A", status="Stopped", last_active=0)
    b = _make_player("B", status="Stopped", last_active=0)
    mod._players = {a.bus_name: a, b.bus_name: b}
    picked = mod.pick_active()
    assert picked in (a, b)


# ---------------------------------------------------------------- disabled paths

@pytest.mark.asyncio
async def test_module_disabled_when_dbus_next_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "dbus_next", None)
    monkeypatch.setitem(sys.modules, "dbus_next.aio", None)
    mod = MediaModule({})
    await mod.setup()
    assert mod._available is False
    data = await mod.poll()
    assert data["available"] is False
    assert "dbus-next" in data["reason"]


@pytest.mark.asyncio
async def test_module_disabled_when_bus_connect_fails():
    fake_bus_class = MagicMock()
    fake_bus = MagicMock()
    fake_bus.connect = AsyncMock(side_effect=ConnectionError("no session bus"))
    fake_bus_class.return_value = fake_bus

    with patch("dbus_next.aio.MessageBus", fake_bus_class):
        mod = MediaModule({})
        await mod.setup()
    assert mod._available is False
    data = await mod.poll()
    assert data["available"] is False
    assert "session" in data["reason"].lower() or "bus" in data["reason"].lower()


# ---------------------------------------------------------------- actions

@pytest.mark.asyncio
async def test_action_returns_false_when_module_unavailable():
    mod = MediaModule({})
    # _available stays False (no setup called)
    assert await mod.action("play") is False
    assert await mod.action("pause") is False
    assert await mod.action("not_a_real_action") is False


@pytest.mark.asyncio
async def test_action_returns_false_when_no_player():
    mod = MediaModule({})
    mod._available = True
    mod._players = {}
    assert await mod.action("play") is False


@pytest.mark.asyncio
async def test_action_unknown_name_rejected():
    mod = MediaModule({})
    mod._available = True
    mod._players = {"x": _make_player("X")}
    assert await mod.action("rm_rf") is False


@pytest.mark.asyncio
async def test_action_play_calls_iface():
    mod = MediaModule({})
    mod._available = True
    p = _make_player("X", status="Paused", last_active=time.time())
    p.player_iface = MagicMock()
    p.player_iface.call_play = AsyncMock()
    p.player_iface.call_pause = AsyncMock()
    p.player_iface.call_play_pause = AsyncMock()
    p.player_iface.call_next = AsyncMock()
    p.player_iface.call_previous = AsyncMock()
    mod._players = {p.bus_name: p}
    assert await mod.action("play") is True
    p.player_iface.call_play.assert_awaited_once()
    assert await mod.action("next") is True
    p.player_iface.call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_shuffle_toggles_when_no_value_supplied():
    mod = MediaModule({})
    mod._available = True
    p = _make_player("X", status="Playing", last_active=time.time())
    p.shuffle = False
    p.player_iface = MagicMock()
    p.player_iface.set_shuffle = AsyncMock()
    mod._players = {p.bus_name: p}

    assert await mod.action("shuffle") is True
    p.player_iface.set_shuffle.assert_awaited_with(True)

    p.shuffle = True
    assert await mod.action("shuffle") is True
    p.player_iface.set_shuffle.assert_awaited_with(False)


@pytest.mark.asyncio
async def test_action_shuffle_with_explicit_value():
    mod = MediaModule({})
    mod._available = True
    p = _make_player("X", status="Playing", last_active=time.time())
    p.player_iface = MagicMock()
    p.player_iface.set_shuffle = AsyncMock()
    mod._players = {p.bus_name: p}

    assert await mod.action("shuffle", enabled=True) is True
    p.player_iface.set_shuffle.assert_awaited_with(True)


@pytest.mark.asyncio
async def test_action_loop_cycles_when_no_status_supplied():
    mod = MediaModule({})
    mod._available = True
    p = _make_player("X", status="Playing", last_active=time.time())
    p.player_iface = MagicMock()
    p.player_iface.set_loop_status = AsyncMock()
    mod._players = {p.bus_name: p}

    p.loop_status = "None"
    assert await mod.action("loop") is True
    p.player_iface.set_loop_status.assert_awaited_with("Track")

    p.loop_status = "Track"
    assert await mod.action("loop") is True
    p.player_iface.set_loop_status.assert_awaited_with("Playlist")

    p.loop_status = "Playlist"
    assert await mod.action("loop") is True
    p.player_iface.set_loop_status.assert_awaited_with("None")


@pytest.mark.asyncio
async def test_action_loop_rejects_invalid_status():
    mod = MediaModule({})
    mod._available = True
    p = _make_player("X", status="Playing", last_active=time.time())
    p.player_iface = MagicMock()
    p.player_iface.set_loop_status = AsyncMock()
    mod._players = {p.bus_name: p}

    assert await mod.action("loop", status="Bogus") is False
    p.player_iface.set_loop_status.assert_not_called()


@pytest.mark.asyncio
async def test_poll_includes_shuffle_and_loop():
    mod = MediaModule({})
    mod._available = True
    p = _make_player("X", status="Playing", last_active=time.time())
    p.shuffle = True
    p.loop_status = "Track"
    p.metadata = {"xesam:title": "Song"}
    p.player_iface = MagicMock()
    p.player_iface.get_position = AsyncMock(return_value=0)
    mod._players = {p.bus_name: p}

    data = await mod.poll()
    assert data["shuffle"] is True
    assert data["loop_status"] == "Track"


# ---------------------------------------------------------------- poll fallbacks

@pytest.mark.asyncio
async def test_poll_returns_inactive_when_no_players():
    mod = MediaModule({})
    mod._available = True
    mod._players = {}
    data = await mod.poll()
    assert data == {"available": True, "active": False}


@pytest.mark.asyncio
async def test_poll_returns_unavailable_when_module_disabled():
    mod = MediaModule({})
    mod._available = False
    mod._unavailable_reason = "no D-Bus"
    data = await mod.poll()
    assert data["available"] is False
    assert data["reason"] == "no D-Bus"
