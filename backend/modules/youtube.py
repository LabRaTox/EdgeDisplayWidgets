"""YouTube widget data module.

Resolves a configured list of video / playlist URLs (or bare IDs) to titles
and thumbnails via YouTube's public oEmbed endpoint — no API key required.
Results are cached on disk so a kiosk reboot doesn't refetch every entry.

For a playlist the module also lists its videos, from the playlist's public
feed, so the tile can open it like a folder. That feed holds at most fifteen
videos; a longer playlist still plays in full, the player fetches the rest.
A video link that carries a playlist (`watch?v=…&list=…`) becomes that
playlist, starting with that video.

Accepted entry shapes in config:
    entries:
      - https://www.youtube.com/watch?v=dQw4w9WgXcQ
      - https://youtu.be/dQw4w9WgXcQ
      - https://www.youtube.com/playlist?list=PLxxx
      - dQw4w9WgXcQ                # bare 11-char video id
      - {kind: video, id: dQw4w9WgXcQ}
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger

from .base import Module, register_module

VIDEO_OEMBED = (
    "https://www.youtube.com/oembed?format=json"
    "&url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D{id}"
)
PLAYLIST_OEMBED = (
    "https://www.youtube.com/oembed?format=json"
    "&url=https%3A%2F%2Fwww.youtube.com%2Fplaylist%3Flist%3D{id}"
)
PLAYLIST_FEED = "https://www.youtube.com/feeds/videos.xml?playlist_id={id}"
FEED_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID_RE = re.compile(r"^(PL|UU|FL|RD|LL)[A-Za-z0-9_-]{10,}$")


def _parse_entry(raw: Any) -> tuple[str, str] | None:
    """Return (kind, id) for a config entry — accepts URL, bare ID, or dict."""
    if isinstance(raw, dict):
        kind = raw.get("kind") or raw.get("type")
        ident = raw.get("id")
        url = raw.get("url")
        if kind and ident and kind in ("video", "playlist"):
            return (kind, str(ident))
        if url:
            return _parse_url(str(url))
        return None
    if isinstance(raw, str):
        return _parse_url(raw)
    return None


def _start_video(raw: Any) -> str:
    """The video a playlist link starts at, or "".

    `watch?v=X&list=Y` names both: the playlist is what the tile shows, and
    X is where playing it starts, the way YouTube itself would.
    """
    text = raw.get("url", "") if isinstance(raw, dict) else raw
    if not isinstance(text, str) or "list=" not in text:
        return ""
    # `youtu.be/X?list=Y` is what YouTube's share button gives for a video
    # inside a playlist; the video sits in the path there, not in `v=`.
    m = re.search(r"(?:[?&]v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", text)
    return m.group(1) if m else ""


def parse_playlist_feed(text: str) -> list[dict[str, str]]:
    """The videos in a playlist feed: id, title, channel, thumbnail.

    Unreadable XML is an empty list, not an error: the playlist then plays
    as one tile, as it did before it could be opened.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items = []
    for entry in root.findall("atom:entry", FEED_NS):
        video = entry.findtext("yt:videoId", "", FEED_NS)
        if not VIDEO_ID_RE.match(video):
            continue
        thumb = entry.find("media:group/media:thumbnail", FEED_NS)
        items.append({
            "id": video,
            "title": entry.findtext("atom:title", "", FEED_NS) or video,
            "author": entry.findtext("atom:author/atom:name", "", FEED_NS),
            "thumbnail": thumb.get("url") if thumb is not None else _fallback_thumbnail("video", video),
        })
    return items


def _parse_url(s: str) -> tuple[str, str] | None:
    s = s.strip()
    if not s:
        return None
    # Playlist URLs: ...?list=PLxxx or ...&list=PLxxx
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", s)
    if m:
        return ("playlist", m.group(1))
    # Video URLs: watch?v=, youtu.be/, embed/, shorts/
    m = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", s)
    if m:
        return ("video", m.group(1))
    # Bare IDs — playlist check first (longer prefix patterns are unambiguous)
    if PLAYLIST_ID_RE.match(s):
        return ("playlist", s)
    if VIDEO_ID_RE.match(s):
        return ("video", s)
    return None


@register_module
class YoutubeModule(Module):
    name = "youtube"
    default_interval = 3600.0  # re-check metadata hourly; rarely changes

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.raw_entries: list[Any] = list(config.get("entries", []) or [])
        cache_path = config.get(
            "cache_path", "~/.cache/edge-dashboard/youtube.json"
        )
        self.cache_path = Path(cache_path).expanduser()
        self._cache: dict[str, dict[str, Any]] = {}
        self._resolved: list[dict[str, Any]] = []
        self._polled = False

    async def setup(self) -> None:
        self._load_cache()
        await self._resolve_all()

    def _load_cache(self) -> None:
        try:
            if self.cache_path.is_file():
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._cache = data
        except Exception as exc:
            logger.warning(f"youtube: cache load failed: {exc}")
            self._cache = {}

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(f"youtube: cache save failed: {exc}")

    async def _resolve_all(self) -> None:
        resolved: list[dict[str, Any]] = []
        # Skip the HTTP client entirely when nothing is configured —
        # avoids opening a connection pool we'd immediately tear down.
        if not self.raw_entries:
            self._resolved = []
            return

        async with httpx.AsyncClient(timeout=10.0) as client:
            for raw in self.raw_entries:
                pair = _parse_entry(raw)
                if pair is None:
                    logger.warning(f"youtube: unparseable entry: {raw!r}")
                    continue
                kind, ident = pair
                key = f"{kind}:{ident}"
                meta = self._cache.get(key)
                if not meta:
                    meta = await self._fetch_oembed(client, kind, ident)
                    if meta:
                        self._cache[key] = meta
                if meta:
                    entry = {"kind": kind, "id": ident, **meta}
                else:
                    # Even unresolved entries are surfaced — the frontend can
                    # still build a playable link and a fallback thumbnail.
                    entry = {
                        "kind": kind,
                        "id": ident,
                        "title": ident,
                        "author": "",
                        "thumbnail": _fallback_thumbnail(kind, ident),
                    }
                if kind == "playlist":
                    entry["start"] = _start_video(raw)
                    entry["items"] = await self._fetch_items(client, ident)
                    # A playlist has no thumbnail of its own to fall back
                    # on; its first video's is the next best thing.
                    if not entry.get("thumbnail") and entry["items"]:
                        entry["thumbnail"] = entry["items"][0]["thumbnail"]
                resolved.append(entry)
        self._resolved = resolved
        self._save_cache()

    async def _fetch_items(self, client: httpx.AsyncClient, ident: str) -> list[dict[str, str]]:
        """The videos of a playlist, fresh when the feed answers, cached when not."""
        key = f"items:{ident}"
        try:
            r = await client.get(PLAYLIST_FEED.format(id=quote(ident, safe="")))
            r.raise_for_status()
            items = parse_playlist_feed(r.text)
            if items:
                self._cache[key] = {"items": items}
                return items
        except Exception as exc:
            logger.warning(f"youtube: playlist feed failed for {ident}: {exc}")
        cached = self._cache.get(key)
        return list(cached.get("items", [])) if isinstance(cached, dict) else []

    async def _fetch_oembed(
        self, client: httpx.AsyncClient, kind: str, ident: str
    ) -> dict[str, Any] | None:
        url = (VIDEO_OEMBED if kind == "video" else PLAYLIST_OEMBED).format(
            id=quote(ident, safe="")
        )
        try:
            r = await client.get(url)
            r.raise_for_status()
            d = r.json()
            return {
                "title": d.get("title") or ident,
                "author": d.get("author_name") or "",
                "thumbnail": d.get("thumbnail_url") or _fallback_thumbnail(kind, ident),
            }
        except Exception as exc:
            logger.warning(f"youtube: oembed failed for {kind} {ident}: {exc}")
            return None

    async def poll(self) -> dict[str, Any]:
        # Retry any entries that still have a placeholder title, and fetch the
        # playlists again: their videos change, their titles rarely do. The
        # first poll follows setup directly, which has just fetched them.
        if self._polled and (
            any(r.get("title") == r.get("id") for r in self._resolved)
            or any(r.get("kind") == "playlist" for r in self._resolved)
        ):
            await self._resolve_all()
        self._polled = True
        return {"entries": list(self._resolved)}


def _fallback_thumbnail(kind: str, ident: str) -> str | None:
    """YouTube's CDN exposes a deterministic per-video thumbnail URL even
    when oEmbed is unavailable; playlists have no public equivalent."""
    if kind == "video":
        return f"https://i.ytimg.com/vi/{ident}/hqdefault.jpg"
    return None
