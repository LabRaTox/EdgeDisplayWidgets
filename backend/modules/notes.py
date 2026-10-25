"""Where the notes widget keeps its notes: a local file, or Joplin.

The REST routes under `/api/notes` ask this module for the store and stay
the same either way (see `store`). What the module itself sends is small:
which store, whether it is reachable, and a revision that goes up whenever
the notes changed, here or elsewhere. The widget reloads on a new revision,
so a note edited in Joplin on the desktop shows on the display a few
seconds later.

Changes are noticed by the file's modification time, or by Joplin's event
list (`/events`, which only covers notes; notebooks are compared by hand).

Connecting to Joplin is a command from the tile: the module asks Joplin for
a token, Joplin shows the request, and the module waits up to two minutes
for the answer. A token can also be typed into the settings (Joplin shows
it under Web Clipper); that one wins over the stored one.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, ClassVar

from loguru import logger

from .. import joplin
from ..notes import NotesStore
from .base import Module, SettingField, register_module

PAIRING_TIMEOUT_S = 120
PAIRING_POLL_S = 2.0


@register_module
class NotesModule(Module):
    name: ClassVar[str] = "notes"
    default_interval: ClassVar[float] = 5.0

    settings_schema: ClassVar[list[SettingField]] = [
        SettingField(key="storage", type="select", default="local", options=["local", "joplin"],
                     option_label_keys=["settings.mod.notes.storage.local",
                                        "settings.mod.notes.storage.joplin"],
                     label_key="settings.mod.notes.storage",
                     help_key="settings.mod.notes.storage_help"),
        SettingField(key="joplin_token", type="text", secret=True, default="",
                     label_key="settings.mod.notes.joplin_token",
                     help_key="settings.mod.notes.joplin_token_help"),
        SettingField(key="joplin_notebook", type="text", default=joplin.DEFAULT_QUICK_NOTEBOOK,
                     label_key="settings.mod.notes.joplin_notebook",
                     help_key="settings.mod.notes.joplin_notebook_help"),
        SettingField(key="joplin_port", type="int", default=0, min=0, max=65535,
                     label_key="settings.mod.notes.joplin_port",
                     help_key="settings.mod.notes.joplin_port_help"),
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.storage = "joplin" if config.get("storage") == "joplin" else "local"
        self.quick_name = str(config.get("joplin_notebook") or joplin.DEFAULT_QUICK_NOTEBOOK)
        # Typed into the settings; without it, the one "connect" stored.
        self.token_setting = str(config.get("joplin_token") or "").strip()
        self.local = NotesStore()
        self.client = joplin.JoplinClient(int(config.get("joplin_port") or 0))
        self.state = "local" if self.storage == "local" else "offline"
        self.error = ""
        self.revision = 0
        self._mtime: float | None = None
        self._cursor: str | None = None
        self._notebooks: str | None = None
        self._pairing: asyncio.Task | None = None

    # -- the store for the routes ------------------------------------------

    def token(self) -> str:
        return self.token_setting or joplin.load_token()

    @property
    def store(self) -> NotesStore | joplin.JoplinStore:
        if self.storage == "local":
            return self.local
        return joplin.JoplinStore(self.client, self.token(), self.quick_name)

    def changed(self) -> None:
        """The routes call this after a write, so other tiles reload too."""
        self.revision += 1
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(self.emit(self.payload()))

    def payload(self) -> dict[str, Any]:
        return {"storage": self.storage, "state": self.state, "error": self.error,
                "revision": self.revision, "quick_notebook": self.quick_name}

    # -- watching for changes ------------------------------------------------

    async def poll(self) -> dict[str, Any]:
        if self.storage == "local":
            self._watch_file()
        elif self._pairing is None or self._pairing.done():
            await self._watch_joplin()
        return self.payload()

    def _watch_file(self) -> None:
        try:
            mtime = self.local.path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if self._mtime is not None and mtime != self._mtime:
            self.revision += 1
        self._mtime = mtime

    async def _watch_joplin(self) -> None:
        token = self.token()
        try:
            if not token:
                await self.client.find()
                self.state = "needs_auth"
                return
            await self._check_events(token)
            self.state = "connected"
            self.error = ""
        except joplin.JoplinError as exc:
            self.state = "needs_auth" if exc.key == "auth" else "offline"
            self._cursor = None

    async def _check_events(self, token: str) -> None:
        params = {"cursor": self._cursor} if self._cursor else {}
        data = await self.client.request("GET", "/events", token, params=params) or {}
        news = bool(data.get("items")) and self._cursor is not None
        self._cursor = str(data.get("cursor") or self._cursor or "")
        # Events cover notes only; notebooks are compared as a whole.
        folders = await self.client.request("GET", "/folders", token, params={"fields": "id,parent_id,title"})
        fingerprint = repr(folders)
        if self._notebooks is not None and fingerprint != self._notebooks:
            news = True
        self._notebooks = fingerprint
        if news:
            self.revision += 1

    # -- connecting ----------------------------------------------------------

    async def command(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "connect":
            if self.storage != "joplin":
                return {"ok": False, "error": "not_joplin"}
            if self._pairing is None or self._pairing.done():
                self._pairing = asyncio.create_task(self._pair(), name="joplin-pairing")
            return {"ok": True}
        if action == "disconnect":
            joplin.clear_token()
            self.state = "needs_auth"
            await self.emit(self.payload())
            return {"ok": True}
        raise NotImplementedError

    async def _pair(self) -> None:
        self.state = "pairing"
        self.error = ""
        await self.emit(self.payload())
        try:
            auth = await self.client.auth_start()
            for _ in range(int(PAIRING_TIMEOUT_S / PAIRING_POLL_S)):
                await asyncio.sleep(PAIRING_POLL_S)
                answer = await self.client.auth_check(auth)
                status = answer.get("status")
                if status == "accepted" and answer.get("token"):
                    joplin.store_token(answer["token"])
                    logger.info("notes: connected to Joplin")
                    self.state = "connected"
                    self._cursor = None
                    self.revision += 1
                    break
                if status == "rejected":
                    self.state, self.error = "needs_auth", "rejected"
                    break
            else:
                self.state, self.error = "needs_auth", "timeout"
        except joplin.JoplinError as exc:
            self.state, self.error = "offline", exc.key
        await self.emit(self.payload())

    async def teardown(self) -> None:
        if self._pairing is not None and not self._pairing.done():
            self._pairing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pairing
