"""Joplin as the store behind the notes widget.

Joplin's desktop app serves a REST API on localhost (its "Web Clipper"
service, port 41184 or one of the next ten). Every call carries a token,
which an app asks for once: `POST /auth`, the user confirms in Joplin,
`GET /auth/check` hands the token over. It is kept in a file of its own
with mode 0600, next to the other tokens.

`JoplinStore` offers what `NotesStore` offers, as coroutines, so the REST
routes do not care which one is behind them. The two models differ in a few
places, settled here:

* Folders are Joplin notebooks. Joplin nests them, the widget lists them
  flat, so a sub-notebook shows as "Parent / Child", joined by a right angle quote (U+203A).
* Joplin has no note outside a notebook. The widget's quick notes are one
  notebook (named in the settings, created when first needed), and a note
  "in no folder" goes there too.
* Joplin has no pinning; which notes are pinned is kept on this machine.
* Bodies are Markdown. Checklist items (`- [ ]`, `- [x]`) appear as ☐ and ☑,
  the way the widget writes them, and go back as Markdown. Everything else
  in the text stays as it is.
* Deleting a notebook moves its notes to the quick notes first, so they are
  kept, as with local folders. Joplin itself puts deleted things in its
  trash.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from .notes import MAX_NOTES, QUICK_FOLDER, Folder, Note

PORTS = range(41184, 41195)
PING_ANSWER = "JoplinClipperServer"
PAGE = 100
DEFAULT_QUICK_NOTEBOOK = "Edge Dash"
NOTE_FIELDS = "id,parent_id,title,body,user_created_time,user_updated_time"

_BOX_FROM_MD = re.compile(r"^(\s*)[-*+] \[( |x|X)\] ", re.M)
_BOX_TO_MD = re.compile(r"^(\s*)([☐☑]) ", re.M)


class JoplinError(Exception):
    """Something the widget can name: `offline`, `auth` or `refused`."""

    def __init__(self, key: str, detail: str = "") -> None:
        super().__init__(f"{key}: {detail}" if detail else key)
        self.key = key


def boxes_from_markdown(body: str) -> str:
    return _BOX_FROM_MD.sub(lambda m: m.group(1) + ("☐ " if m.group(2) == " " else "☑ "), body)


def boxes_to_markdown(body: str) -> str:
    return _BOX_TO_MD.sub(lambda m: m.group(1) + ("- [ ] " if m.group(2) == "☐" else "- [x] "), body)


def config_dir() -> Path:
    home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(home) / "edge-dashboard"


def _write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    draft = path.with_suffix(".new")
    with contextlib.suppress(FileNotFoundError):
        draft.unlink()
    fd = os.open(draft, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data))
    os.replace(draft, path)


def load_token() -> str:
    try:
        return str(json.loads((config_dir() / "joplin-token.json").read_text()).get("token") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def store_token(token: str) -> None:
    _write_private(config_dir() / "joplin-token.json", {"token": token})


def clear_token() -> None:
    with contextlib.suppress(OSError):
        (config_dir() / "joplin-token.json").unlink()


class JoplinClient:
    """The REST API of the running Joplin app."""

    def __init__(self, port: int = 0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # 0: look for Joplin on its usual ports, and look again after it
        # stopped answering (it may come back on another one).
        self.fixed = port
        self.port = port
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=8.0, transport=self._transport)

    async def find(self) -> int:
        """The port Joplin answers on, the configured one or the first of the range."""
        candidates = [self.fixed] if self.fixed else list(PORTS)
        async with self._client() as client:
            for port in candidates:
                try:
                    r = await client.get(f"http://127.0.0.1:{port}/ping")
                except httpx.HTTPError:
                    continue
                if r.status_code == 200 and PING_ANSWER in r.text:
                    self.port = port
                    return port
        raise JoplinError("offline")

    async def request(self, method: str, path: str, token: str, *,
                      params: dict | None = None, body: dict | None = None) -> Any:
        if not self.port:
            await self.find()
        query = {**(params or {}), "token": token}
        try:
            async with self._client() as client:
                r = await client.request(method, f"http://127.0.0.1:{self.port}{path}",
                                         params=query, json=body)
        except httpx.HTTPError as exc:
            if not self.fixed:
                self.port = 0
            raise JoplinError("offline", str(exc)) from exc
        if r.status_code == 403:
            raise JoplinError("auth")
        if r.status_code == 404:
            raise JoplinError("missing", path)
        if r.status_code >= 400:
            raise JoplinError("refused", f"{r.status_code} {r.text[:200]}")
        return r.json() if r.content else None

    async def pages(self, path: str, token: str, params: dict, limit: int) -> list[dict]:
        """All items of a paginated list, up to `limit`."""
        out: list[dict] = []
        page = 1
        while len(out) < limit:
            data = await self.request("GET", path, token, params={**params, "page": page, "limit": PAGE})
            items = data.get("items", []) if isinstance(data, dict) else data or []
            out.extend(items)
            if not (isinstance(data, dict) and data.get("has_more")):
                break
            page += 1
        return out[:limit]

    # -- asking for a token -------------------------------------------------

    async def auth_start(self) -> str:
        if not self.port:
            await self.find()
        async with self._client() as client:
            try:
                r = await client.post(f"http://127.0.0.1:{self.port}/auth")
            except httpx.HTTPError as exc:
                raise JoplinError("offline", str(exc)) from exc
        token = (r.json() or {}).get("auth_token") if r.status_code == 200 else None
        if not token:
            raise JoplinError("refused", f"/auth {r.status_code}")
        return token

    async def auth_check(self, auth_token: str) -> dict:
        async with self._client() as client:
            try:
                r = await client.get(f"http://127.0.0.1:{self.port}/auth/check",
                                     params={"auth_token": auth_token})
            except httpx.HTTPError as exc:
                raise JoplinError("offline", str(exc)) from exc
        return r.json() if r.status_code == 200 else {"status": "rejected"}


class PinStore:
    """Which Joplin notes are pinned; Joplin has no such property."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / "joplin-pinned.json"

    def load(self) -> set[str]:
        try:
            return set(json.loads(self.path.read_text()))
        except (OSError, ValueError, TypeError):
            return set()

    def set(self, note_id: str, pinned: bool) -> None:
        ids = self.load()
        if pinned == (note_id in ids):
            return
        ids = ids | {note_id} if pinned else ids - {note_id}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(ids)))


def _flatten(folders: list[dict]) -> list[dict]:
    """Joplin's notebooks, nested or flat, as a flat list with full names."""
    flat: list[dict] = []

    def walk(items: list[dict]) -> None:
        for item in items:
            flat.append(item)
            walk(item.get("children") or [])

    walk(folders)
    by_id = {f["id"]: f for f in flat}

    def path(folder: dict) -> str:
        names, seen = [], set()
        while folder and folder["id"] not in seen:
            seen.add(folder["id"])
            names.append(folder.get("title") or "?")
            folder = by_id.get(folder.get("parent_id") or "")
        return " \u203a ".join(reversed(names))

    return sorted(({"id": f["id"], "name": path(f), "parent_id": f.get("parent_id") or ""} for f in flat),
                  key=lambda f: f["name"].lower())


class JoplinStore:
    """The notes widget's store, kept in Joplin."""

    def __init__(self, client: JoplinClient, token: str, quick_name: str = DEFAULT_QUICK_NOTEBOOK,
                 pins: PinStore | None = None) -> None:
        self.client = client
        self.token = token
        self.quick_name = quick_name.strip() or DEFAULT_QUICK_NOTEBOOK
        self.pins = pins or PinStore()

    async def _call(self, method: str, path: str, **kwargs) -> Any:
        if not self.token:
            raise JoplinError("auth")
        return await self.client.request(method, path, self.token, **kwargs)

    async def _notebooks(self) -> list[dict]:
        data = await self._call("GET", "/folders", params={"fields": "id,parent_id,title"})
        items = data.get("items", []) if isinstance(data, dict) else data or []
        return _flatten(items)

    async def _quick_id(self, notebooks: list[dict] | None = None, *, create: bool = True) -> str:
        for folder in notebooks if notebooks is not None else await self._notebooks():
            if folder["name"] == self.quick_name:
                return folder["id"]
        if not create:
            return ""
        made = await self._call("POST", "/folders", body={"title": self.quick_name})
        return made["id"]

    def _note(self, raw: dict, quick: str, known: set[str], pinned: set[str]) -> Note:
        parent = raw.get("parent_id") or ""
        return Note(
            id=raw["id"],
            title=(raw.get("title") or "")[:200],
            body=boxes_from_markdown(raw.get("body") or "")[:50_000],
            folder=QUICK_FOLDER if parent == quick else (parent if parent in known else ""),
            pinned=raw["id"] in pinned,
            created_at=(raw.get("user_created_time") or 0) / 1000,
            updated_at=(raw.get("user_updated_time") or 0) / 1000,
        )

    async def contents(self) -> tuple[list[Note], list[Folder]]:
        notebooks = await self._notebooks()
        quick = await self._quick_id(notebooks, create=False)
        folders = [Folder(id=f["id"], name=f["name"][:60]) for f in notebooks if f["id"] != quick]
        known = {f.id for f in folders}
        raw = await self.client.pages("/notes", self.token, {
            "fields": NOTE_FIELDS, "order_by": "user_updated_time", "order_dir": "DESC"}, MAX_NOTES)
        pinned = self.pins.load()
        return [self._note(n, quick, known, pinned) for n in raw], folders

    async def _parent_for(self, folder: str) -> str:
        if folder in ("", QUICK_FOLDER):
            return await self._quick_id()
        return folder

    async def upsert(self, title: str, body: str, note_id: str | None = None, *,
                     folder: str | None = None, pinned: bool | None = None) -> Note:
        fields: dict[str, Any] = {"title": title, "body": boxes_to_markdown(body)}
        if folder is not None:
            fields["parent_id"] = await self._parent_for(folder)
        saved = None
        if note_id:
            try:
                saved = await self._call("PUT", f"/notes/{note_id}", body=fields)
            except JoplinError as exc:
                if exc.key != "missing":
                    raise
        if saved is None:
            fields.setdefault("parent_id", await self._parent_for(""))
            saved = await self._call("POST", "/notes", body=fields)
        if pinned is not None:
            self.pins.set(saved["id"], pinned)
        full = await self._call("GET", f"/notes/{saved['id']}", params={"fields": NOTE_FIELDS})
        notebooks = await self._notebooks()
        quick = await self._quick_id(notebooks, create=False)
        known = {f["id"] for f in notebooks if f["id"] != quick}
        return self._note(full, quick, known, self.pins.load())

    async def delete(self, note_id: str) -> bool:
        try:
            await self._call("DELETE", f"/notes/{note_id}")
        except JoplinError as exc:
            if exc.key == "missing":
                return False
            raise
        self.pins.set(note_id, False)
        return True

    async def add_folder(self, name: str) -> Folder:
        made = await self._call("POST", "/folders", body={"title": name.strip()[:60]})
        return Folder(id=made["id"], name=made.get("title") or name)

    async def rename_folder(self, folder_id: str, name: str) -> Folder | None:
        try:
            await self._call("PUT", f"/folders/{folder_id}", body={"title": name.strip()[:60]})
        except JoplinError as exc:
            if exc.key == "missing":
                return None
            raise
        # The list shows the full path; a sub-notebook keeps its parent's name.
        for folder in await self._notebooks():
            if folder["id"] == folder_id:
                return Folder(id=folder_id, name=folder["name"][:60])
        return Folder(id=folder_id, name=name)

    async def delete_folder(self, folder_id: str) -> bool:
        notebooks = await self._notebooks()
        if folder_id not in {f["id"] for f in notebooks}:
            return False
        if any(f["parent_id"] == folder_id for f in notebooks):
            raise ValueError("this notebook has notebooks inside; delete those in Joplin")
        quick = await self._quick_id(notebooks)
        if folder_id == quick:
            raise ValueError("the quick notes notebook cannot be deleted here")
        notes = await self.client.pages(f"/folders/{folder_id}/notes", self.token, {"fields": "id"}, 10_000)
        for note in notes:
            await self._call("PUT", f"/notes/{note['id']}", body={"parent_id": quick})
        await self._call("DELETE", f"/folders/{folder_id}")
        logger.info(f"notes: Joplin notebook {folder_id} deleted, {len(notes)} note(s) moved")
        return True
