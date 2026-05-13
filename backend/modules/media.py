"""MPRIS2 media module via D-Bus.

Tracks every MPRIS player on the session bus, subscribes to PropertiesChanged
so state is always fresh, and picks the *most-recently-active* player as the
current one (matches KDE Plasma / GNOME Shell semantics).

Album art (`mpris:artUrl`) is fetched and cached in-process under an opaque
token; the frontend pulls bytes from `/api/media/art/<token>` rather than
following the original URL (which is often `file:///` and unreachable from
a browser context).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
import urllib.parse
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loguru import logger

from .base import Module, register_module

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
PLAYER_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PROPS_IFACE = "org.freedesktop.DBus.Properties"


def _unwrap(value: Any) -> Any:
    """dbus-next returns Variant objects; recursively unwrap them."""
    try:
        from dbus_next.signature import Variant
    except ImportError:
        return value
    if isinstance(value, Variant):
        return _unwrap(value.value)
    if isinstance(value, list):
        return [_unwrap(v) for v in value]
    if isinstance(value, dict):
        return {k: _unwrap(v) for k, v in value.items()}
    return value


def _guess_mime(suffix: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(suffix.lower(), "image/jpeg")


def _is_within(path: Path, root: Path) -> bool:
    """True when `path` (already resolved) sits inside `root`."""
    try:
        path.relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


class ArtCache:
    """Bounded LRU for fetched album-art bytes, keyed by a stable token."""

    def __init__(self, capacity: int = 10) -> None:
        self.cap = capacity
        self._entries: OrderedDict[str, tuple[bytes, str]] = OrderedDict()

    def get(self, token: str) -> tuple[bytes, str] | None:
        item = self._entries.get(token)
        if item is None:
            return None
        self._entries.move_to_end(token)
        return item

    @staticmethod
    def token_for(art_url: str) -> str:
        return hashlib.sha1(art_url.encode("utf-8")).hexdigest()[:16]

    async def store(self, art_url: str) -> str | None:
        if not art_url:
            return None
        token = self.token_for(art_url)
        if token in self._entries:
            self._entries.move_to_end(token)
            return token
        try:
            data, mime = await self._fetch(art_url)
        except Exception as exc:
            logger.warning(f"album art fetch failed for {art_url[:80]}: {exc}")
            return None
        self._entries[token] = (data, mime)
        while len(self._entries) > self.cap:
            self._entries.popitem(last=False)
        return token

    @staticmethod
    async def _fetch(url: str) -> tuple[bytes, str]:
        if url.startswith("file://"):
            raw = Path(urllib.parse.unquote(url[7:]))
            # MPRIS publishers (including untrusted browser plug-ins on the
            # same desktop) can put arbitrary local paths in `mpris:artUrl`,
            # so we resolve+whitelist to cover only the directories where
            # real album-art caches live. Without this a malicious player
            # could ask us to serve /etc/shadow through /api/media/art/<id>.
            path = raw.resolve(strict=False)
            allowed_roots = [
                Path.home() / ".cache",
                Path("/tmp"),
                Path("/var/cache"),
                Path("/var/tmp"),
                Path("/usr/share"),  # icon themes, some MPRIS publishers
            ]
            if not any(_is_within(path, root) for root in allowed_roots):
                raise PermissionError(f"art path outside allowed roots: {path}")
            # Cap at 8 MiB so a single track can't OOM the cache.
            MAX_ART_BYTES = 8 * 1024 * 1024
            stat = await asyncio.to_thread(path.stat)
            if stat.st_size > MAX_ART_BYTES:
                raise ValueError(f"art file too large ({stat.st_size} bytes)")
            data = await asyncio.to_thread(path.read_bytes)
            return data, _guess_mime(path.suffix)
        if url.startswith("data:"):
            header, _, payload = url[5:].partition(",")
            mime = (header.split(";")[0] or "application/octet-stream").strip()
            if "base64" in header:
                data = base64.b64decode(payload)
            else:
                data = urllib.parse.unquote_to_bytes(payload)
            return data, mime
        if url.startswith(("http://", "https://")):
            import httpx

            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as cli:
                r = await cli.get(url)
                r.raise_for_status()
                mime = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                return r.content, mime
        raise ValueError(f"unsupported art URL scheme: {url[:32]}…")


class _Player:
    """Mutable cached state of one MPRIS player on the bus."""

    def __init__(self, bus_name: str) -> None:
        self.bus_name = bus_name
        self.identity: str = bus_name.removeprefix(MPRIS_PREFIX)
        self.proxy = None
        self.player_iface = None
        self.props_iface = None
        self.props_listener = None  # callback ref so we can detach later
        self.metadata: dict[str, Any] = {}
        self.playback_status: str = "Stopped"
        self.position_us: int = 0
        self.position_ts: float = 0.0
        self.rate: float = 1.0
        self.can_play: bool = True
        self.can_pause: bool = True
        self.can_next: bool = True
        self.can_prev: bool = True
        self.can_seek: bool = True
        self.shuffle: bool = False
        self.loop_status: str = "None"  # None | Track | Playlist
        self.last_active_ts: float = 0.0


@register_module
class MediaModule(Module):
    name = "media"
    default_interval = 0.5

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._bus = None
        self._players: dict[str, _Player] = {}
        self._art_cache = ArtCache(capacity=int(config.get("art_cache", 10)))
        self._available: bool = False
        self._unavailable_reason: str | None = None
        self._owner_changed_listener = None
        self._dbus_iface = None

    # ----------------------------------------------------------------- setup
    async def setup(self) -> None:
        try:
            from dbus_next.aio import MessageBus
            from dbus_next.constants import BusType
        except ImportError as exc:
            self._unavailable_reason = f"dbus-next not installed: {exc}"
            logger.warning(f"media disabled: {self._unavailable_reason}")
            return
        try:
            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
        except Exception as exc:
            self._unavailable_reason = f"D-Bus session unavailable: {exc}"
            logger.warning(f"media disabled: {self._unavailable_reason}")
            return

        await self._scan_players()
        await self._watch_name_changes()
        self._available = True
        logger.info(
            f"media module connected to D-Bus, {len(self._players)} player(s) on bus"
        )

    async def _scan_players(self) -> None:
        try:
            iface = await self._dbus_proxy()
            names = await iface.call_list_names()
        except Exception as exc:
            logger.exception(f"media: list_names failed: {exc}")
            return
        for name in names:
            if name.startswith(MPRIS_PREFIX):
                await self._add_player(name)

    async def _watch_name_changes(self) -> None:
        try:
            iface = await self._dbus_proxy()
        except Exception as exc:
            logger.exception(f"media: name-watch setup failed: {exc}")
            return

        def on_owner_changed(name: str, old_owner: str, new_owner: str) -> None:
            if not name.startswith(MPRIS_PREFIX):
                return
            if new_owner and not old_owner:
                asyncio.create_task(self._add_player(name))
            elif old_owner and not new_owner:
                asyncio.create_task(self._remove_player(name))

        iface.on_name_owner_changed(on_owner_changed)
        self._owner_changed_listener = on_owner_changed
        self._dbus_iface = iface

    async def _dbus_proxy(self):
        intr = await self._bus.introspect("org.freedesktop.DBus", "/org/freedesktop/DBus")
        obj = self._bus.get_proxy_object("org.freedesktop.DBus", "/org/freedesktop/DBus", intr)
        return obj.get_interface("org.freedesktop.DBus")

    # ------------------------------------------------------------ players
    async def _add_player(self, bus_name: str) -> None:
        if bus_name in self._players:
            return
        try:
            intr = await self._bus.introspect(bus_name, PLAYER_PATH)
            proxy = self._bus.get_proxy_object(bus_name, PLAYER_PATH, intr)
            player = _Player(bus_name)
            player.proxy = proxy
            player.player_iface = proxy.get_interface(PLAYER_IFACE)
            player.props_iface = proxy.get_interface(PROPS_IFACE)

            try:
                root_iface = proxy.get_interface(ROOT_IFACE)
                player.identity = await root_iface.get_identity()
            except Exception:
                pass

            await self._refresh_player(player)

            def make_cb(p: _Player):
                def cb(interface_name: str, changed: dict, invalidated: list) -> None:
                    if interface_name != PLAYER_IFACE:
                        return
                    self._apply_changes(p, changed)

                return cb

            cb = make_cb(player)
            player.props_iface.on_properties_changed(cb)
            player.props_listener = cb
            self._players[bus_name] = player
            logger.info(f"media: discovered player '{player.identity}' ({bus_name})")
        except Exception as exc:
            msg = str(exc)
            # Chromium and some other apps expose the MPRIS root but not the
            # Player interface until media actually starts. That's expected,
            # not an error worth shouting about.
            if "interface not found" in msg.lower() and "MediaPlayer2.Player" in msg:
                logger.debug(f"media: skipping {bus_name} (no Player interface)")
            else:
                logger.warning(f"media: failed to attach player {bus_name}: {exc}")

    async def _remove_player(self, bus_name: str) -> None:
        player = self._players.pop(bus_name, None)
        if player is None:
            return
        try:
            if player.props_iface and player.props_listener:
                player.props_iface.off_properties_changed(player.props_listener)
        except Exception:
            pass
        logger.info(f"media: player '{player.identity}' disappeared")

    async def _refresh_player(self, player: _Player) -> None:
        iface = player.player_iface
        try:
            player.metadata = _unwrap(await iface.get_metadata())
        except Exception:
            pass
        try:
            player.playback_status = await iface.get_playback_status()
        except Exception:
            pass
        try:
            player.rate = float(await iface.get_rate())
        except Exception:
            pass
        try:
            player.position_us = int(await iface.get_position())
            player.position_ts = time.time()
        except Exception:
            pass
        for attr, getter in (
            ("can_play", "get_can_play"),
            ("can_pause", "get_can_pause"),
            ("can_next", "get_can_go_next"),
            ("can_prev", "get_can_go_previous"),
            ("can_seek", "get_can_seek"),
        ):
            try:
                setattr(player, attr, bool(await getattr(iface, getter)()))
            except Exception:
                pass
        # Shuffle / LoopStatus are optional in the MPRIS spec — many players
        # omit them. Failing reads stay at their defaults.
        try:
            player.shuffle = bool(await iface.get_shuffle())
        except Exception:
            pass
        try:
            player.loop_status = str(await iface.get_loop_status())
        except Exception:
            pass
        if player.playback_status in ("Playing", "Paused"):
            player.last_active_ts = time.time()

    def _apply_changes(self, player: _Player, changed: dict) -> None:
        for k, raw in changed.items():
            v = _unwrap(raw)
            if k == "PlaybackStatus":
                player.playback_status = str(v)
                if player.playback_status == "Playing":
                    player.last_active_ts = time.time()
            elif k == "Metadata":
                player.metadata = v if isinstance(v, dict) else {}
            elif k == "Rate":
                try:
                    player.rate = float(v)
                except Exception:
                    pass
            elif k == "Position":
                try:
                    player.position_us = int(v)
                    player.position_ts = time.time()
                except Exception:
                    pass
            elif k == "CanPlay":
                player.can_play = bool(v)
            elif k == "CanPause":
                player.can_pause = bool(v)
            elif k == "CanGoNext":
                player.can_next = bool(v)
            elif k == "CanGoPrevious":
                player.can_prev = bool(v)
            elif k == "CanSeek":
                player.can_seek = bool(v)
            elif k == "Shuffle":
                player.shuffle = bool(v)
            elif k == "LoopStatus":
                player.loop_status = str(v)

    # ------------------------------------------------------------- pick
    def pick_active(self) -> _Player | None:
        if not self._players:
            return None
        # Players that were ever active rank by recency (most-recent wins).
        active = [p for p in self._players.values() if p.last_active_ts > 0]
        if active:
            active.sort(key=lambda p: p.last_active_ts, reverse=True)
            playing = next((p for p in active if p.playback_status == "Playing"), None)
            return playing or active[0]
        # Fallback: any player that's not Stopped, else the first found.
        non_stopped = [p for p in self._players.values() if p.playback_status != "Stopped"]
        if non_stopped:
            return non_stopped[0]
        return next(iter(self._players.values()))

    # ---------------------------------------------------------- payload
    async def poll(self) -> dict[str, Any]:
        if not self._available:
            return {"available": False, "reason": self._unavailable_reason or "unknown"}
        if not self._players:
            return {"available": True, "active": False}

        player = self.pick_active()
        if player is None:
            return {"available": True, "active": False}

        # Position doesn't fire signals; refresh on every poll.
        try:
            player.position_us = int(await player.player_iface.get_position())
            player.position_ts = time.time()
        except Exception:
            pass

        meta = player.metadata or {}
        title = str(meta.get("xesam:title", "") or "")
        artist = meta.get("xesam:artist", []) or []
        if isinstance(artist, list):
            artist = ", ".join(str(a) for a in artist)
        elif not isinstance(artist, str):
            artist = str(artist)
        album = str(meta.get("xesam:album", "") or "")
        try:
            length_us = int(meta.get("mpris:length", 0) or 0)
        except (TypeError, ValueError):
            length_us = 0

        art_url = str(meta.get("mpris:artUrl", "") or "")
        art_token = await self._art_cache.store(art_url) if art_url else None

        return {
            "available": True,
            "active": True,
            "player": player.identity,
            "playback_status": player.playback_status,
            "title": title,
            "artist": artist,
            "album": album,
            "length_us": length_us,
            "position_us": player.position_us,
            "position_ts": player.position_ts,
            "rate": player.rate,
            "art_token": art_token,
            "can_play": player.can_play,
            "can_pause": player.can_pause,
            "can_next": player.can_next,
            "can_prev": player.can_prev,
            "can_seek": player.can_seek,
            "shuffle": player.shuffle,
            "loop_status": player.loop_status,
        }

    # ----------------------------------------------------------- actions
    ACTIONS = {
        "play", "pause", "play_pause", "stop",
        "next", "prev", "seek", "set_position",
        "shuffle", "loop",
    }
    LOOP_VALUES = ("None", "Track", "Playlist")

    async def action(self, name: str, **kwargs: Any) -> bool:
        if not self._available or name not in self.ACTIONS:
            return False
        player = self.pick_active()
        if player is None:
            return False
        iface = player.player_iface
        try:
            if name == "play":
                await iface.call_play()
            elif name == "pause":
                await iface.call_pause()
            elif name == "play_pause":
                await iface.call_play_pause()
            elif name == "stop":
                await iface.call_stop()
            elif name == "next":
                await iface.call_next()
            elif name == "prev":
                await iface.call_previous()
            elif name == "seek":
                offset_us = int(kwargs.get("offset_us", 0))
                await iface.call_seek(offset_us)
            elif name == "set_position":
                pos_us = int(kwargs.get("position_us", 0))
                track_id = (player.metadata or {}).get("mpris:trackid", "")
                if not track_id:
                    return False
                await iface.call_set_position(track_id, pos_us)
            elif name == "shuffle":
                # Default to a toggle if no explicit value is supplied.
                enabled = kwargs.get("enabled")
                if enabled is None:
                    enabled = not player.shuffle
                await iface.set_shuffle(bool(enabled))
            elif name == "loop":
                status = kwargs.get("status")
                if status is None:
                    # Cycle: None -> Track -> Playlist -> None
                    cycle = {"None": "Track", "Track": "Playlist", "Playlist": "None"}
                    status = cycle.get(player.loop_status, "None")
                if status not in self.LOOP_VALUES:
                    return False
                await iface.set_loop_status(status)
            return True
        except Exception as exc:
            logger.warning(f"media action '{name}' failed: {exc}")
            return False

    def get_art(self, token: str) -> tuple[bytes, str] | None:
        return self._art_cache.get(token)

    # ---------------------------------------------------------- teardown
    async def teardown(self) -> None:
        # Detach signal handlers first; ignore any errors.
        for player in list(self._players.values()):
            try:
                if player.props_iface and player.props_listener:
                    player.props_iface.off_properties_changed(player.props_listener)
            except Exception:
                pass
        self._players.clear()
        try:
            if self._dbus_iface and self._owner_changed_listener:
                self._dbus_iface.off_name_owner_changed(self._owner_changed_listener)
        except Exception:
            pass
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception:
                pass
            self._bus = None
