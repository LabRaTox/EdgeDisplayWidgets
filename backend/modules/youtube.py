"""YouTube widget data module.

Resolves a configured list of video / playlist URLs (or bare IDs) to titles
and thumbnails via YouTube's public oEmbed endpoint — no API key required.
Results are cached on disk so a kiosk reboot doesn't refetch every entry.

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
                    resolved.append({"kind": kind, "id": ident, **meta})
                else:
                    # Even unresolved entries are surfaced — the frontend can
                    # still build a playable link and a fallback thumbnail.
                    resolved.append({
                        "kind": kind,
                        "id": ident,
                        "title": ident,
                        "author": "",
                        "thumbnail": _fallback_thumbnail(kind, ident),
                    })
        self._resolved = resolved
        self._save_cache()

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
        # Retry any entries that still have a placeholder title; otherwise
        # just return the cached list.
        if self._resolved and any(
            r.get("title") == r.get("id") for r in self._resolved
        ):
            await self._resolve_all()
        return {"entries": list(self._resolved)}


def _fallback_thumbnail(kind: str, ident: str) -> str | None:
    """YouTube's CDN exposes a deterministic per-video thumbnail URL even
    when oEmbed is unavailable; playlists have no public equivalent."""
    if kind == "video":
        return f"https://i.ytimg.com/vi/{ident}/hqdefault.jpg"
    return None
