"""Tests for the YoutubeModule (oEmbed resolver + URL parser)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from backend.modules.base import clear_registry, register_module
from backend.modules.youtube import YoutubeModule, _parse_url


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    register_module(YoutubeModule)
    yield
    clear_registry()


def test_parse_url_handles_common_video_forms():
    cases = [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", ("video", "dQw4w9WgXcQ")),
        ("https://youtu.be/dQw4w9WgXcQ", ("video", "dQw4w9WgXcQ")),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", ("video", "dQw4w9WgXcQ")),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", ("video", "dQw4w9WgXcQ")),
        ("dQw4w9WgXcQ", ("video", "dQw4w9WgXcQ")),
    ]
    for raw, expected in cases:
        assert _parse_url(raw) == expected, f"failed for {raw!r}"


def test_parse_url_handles_playlists():
    cases = [
        (
            "https://www.youtube.com/playlist?list=PLBCF2DAC6FFB574DE",
            ("playlist", "PLBCF2DAC6FFB574DE"),
        ),
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmRdnEQy6nuLMHjMZOz59Oq8B9nUj",
            ("playlist", "PLrAXtmRdnEQy6nuLMHjMZOz59Oq8B9nUj"),
        ),
        ("PLrAXtmRdnEQy6nuLMHjMZOz59Oq8B9nUj", ("playlist", "PLrAXtmRdnEQy6nuLMHjMZOz59Oq8B9nUj")),
    ]
    for raw, expected in cases:
        assert _parse_url(raw) == expected, f"failed for {raw!r}"


def test_parse_url_rejects_garbage():
    for raw in ["", "  ", "not-a-url", "https://example.com/foo"]:
        assert _parse_url(raw) is None, f"should reject {raw!r}"


@pytest.mark.asyncio
async def test_poll_resolves_via_oembed(tmp_path: Path, monkeypatch):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "title": "Rick Astley - Never Gonna Give You Up",
                "author_name": "Rick Astley",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
            },
        )

    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("backend.modules.youtube.httpx.AsyncClient", patched_client)

    mod = YoutubeModule({
        "entries": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        "cache_path": str(tmp_path / "youtube.json"),
    })
    await mod.setup()
    data = await mod.poll()

    assert len(data["entries"]) == 1
    e = data["entries"][0]
    assert e["kind"] == "video"
    assert e["id"] == "dQw4w9WgXcQ"
    assert e["title"].startswith("Rick Astley")
    assert e["thumbnail"].endswith("hqdefault.jpg")
    assert len(seen) == 1  # one oembed call
    # Second poll should not refetch (everything is resolved).
    await mod.poll()
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_oembed_failure_keeps_entry_with_fallback_thumb(tmp_path: Path, monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("backend.modules.youtube.httpx.AsyncClient", patched_client)

    mod = YoutubeModule({
        "entries": ["dQw4w9WgXcQ"],
        "cache_path": str(tmp_path / "youtube.json"),
    })
    await mod.setup()
    data = await mod.poll()
    assert len(data["entries"]) == 1
    e = data["entries"][0]
    assert e["kind"] == "video"
    assert e["id"] == "dQw4w9WgXcQ"
    # Title falls back to the id; CDN thumbnail still works.
    assert e["title"] == "dQw4w9WgXcQ"
    assert e["thumbnail"].endswith("hqdefault.jpg")


@pytest.mark.asyncio
async def test_cache_persists_across_instances(tmp_path: Path, monkeypatch):
    call_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(
            200, json={"title": "X", "author_name": "Y", "thumbnail_url": "Z"}
        )

    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("backend.modules.youtube.httpx.AsyncClient", patched_client)

    cache_path = str(tmp_path / "youtube.json")
    mod_a = YoutubeModule({"entries": ["dQw4w9WgXcQ"], "cache_path": cache_path})
    await mod_a.setup()
    assert call_count["n"] == 1

    mod_b = YoutubeModule({"entries": ["dQw4w9WgXcQ"], "cache_path": cache_path})
    await mod_b.setup()
    # Second instance reads the on-disk cache instead of hitting oEmbed.
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_empty_entries_returns_empty(tmp_path: Path):
    mod = YoutubeModule({"entries": [], "cache_path": str(tmp_path / "yt.json")})
    await mod.setup()
    data = await mod.poll()
    assert data == {"entries": []}


@pytest.mark.asyncio
async def test_unparseable_entry_is_skipped(tmp_path: Path, monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"title": "ok", "author_name": "", "thumbnail_url": "t"}
        )

    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("backend.modules.youtube.httpx.AsyncClient", patched_client)

    mod = YoutubeModule({
        "entries": ["not-a-url", "dQw4w9WgXcQ", "also bad"],
        "cache_path": str(tmp_path / "yt.json"),
    })
    await mod.setup()
    data = await mod.poll()
    assert [e["id"] for e in data["entries"]] == ["dQw4w9WgXcQ"]


FEED = (Path(__file__).resolve().parent / "data" / "youtube" / "playlist-feed.xml").read_text()


def fake_youtube(monkeypatch, *, oembed_ok: bool = True, feed_ok: bool = True) -> list[str]:
    """Answers oEmbed and the playlist feed from the fixture; returns the URLs asked for."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if "feeds/videos.xml" in url:
            return httpx.Response(200, text=FEED) if feed_ok else httpx.Response(500)
        if not oembed_ok:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json={"title": "Test Playlist", "author_name": "Someone",
                                         "thumbnail_url": ""})

    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("backend.modules.youtube.httpx.AsyncClient", patched_client)
    return seen


def test_playlist_feed_is_parsed():
    from backend.modules.youtube import parse_playlist_feed

    items = parse_playlist_feed(FEED)
    assert [i["id"] for i in items] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert items[0] == {"id": "aaaaaaaaaaa", "title": "First video", "author": "Channel A",
                        "thumbnail": "https://i3.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"}
    assert parse_playlist_feed("not xml") == []


def test_video_link_with_playlist_starts_at_that_video():
    from backend.modules.youtube import _start_video

    link = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLtestplaylist0001&index=3"
    assert _parse_url(link) == ("playlist", "PLtestplaylist0001")
    assert _start_video(link) == "dQw4w9WgXcQ"
    assert _start_video("https://www.youtube.com/playlist?list=PLtestplaylist0001") == ""
    assert _start_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == ""


async def test_playlist_entry_carries_its_videos(tmp_path: Path, monkeypatch):
    seen = fake_youtube(monkeypatch)
    mod = YoutubeModule({
        "entries": ["https://www.youtube.com/watch?v=bbbbbbbbbbb&list=PLtestplaylist0001"],
        "cache_path": str(tmp_path / "youtube.json"),
    })
    await mod.setup()
    entry = (await mod.poll())["entries"][0]
    assert entry["kind"] == "playlist"
    assert entry["start"] == "bbbbbbbbbbb"
    assert [i["id"] for i in entry["items"]] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    # No thumbnail from oEmbed: the first video's stands in.
    assert entry["thumbnail"].endswith("aaaaaaaaaaa/hqdefault.jpg")
    feeds = [u for u in seen if "feeds/videos.xml" in u]
    assert len(feeds) == 1
    await mod.poll()   # the next poll fetches the feed again: playlists change
    assert len([u for u in seen if "feeds/videos.xml" in u]) == 2


async def test_playlist_keeps_its_last_videos_when_the_feed_fails(tmp_path: Path, monkeypatch):
    cache = str(tmp_path / "youtube.json")
    fake_youtube(monkeypatch)
    first = YoutubeModule({"entries": ["PLtestplaylist0001"], "cache_path": cache})
    await first.setup()
    fake_youtube(monkeypatch, feed_ok=False)
    second = YoutubeModule({"entries": ["PLtestplaylist0001"], "cache_path": cache})
    await second.setup()
    entry = (await second.poll())["entries"][0]
    assert len(entry["items"]) == 2


async def test_video_entries_have_no_items(tmp_path: Path, monkeypatch):
    fake_youtube(monkeypatch)
    mod = YoutubeModule({"entries": ["dQw4w9WgXcQ"], "cache_path": str(tmp_path / "y.json")})
    await mod.setup()
    entry = (await mod.poll())["entries"][0]
    assert "items" not in entry and "start" not in entry
