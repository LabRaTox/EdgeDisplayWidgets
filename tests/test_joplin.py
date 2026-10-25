"""Joplin as the notes store, against a fake of Joplin's REST API.

Nothing here talks to a real Joplin: the client gets an httpx mock
transport, and the route test points at a port nobody listens on.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import joplin
from backend.joplin import JoplinClient, JoplinError, JoplinStore, PinStore
from backend.notes import QUICK_FOLDER


class FakeJoplin:
    """Enough of Joplin's Data API for the store: notebooks, notes, events, auth."""

    TOKEN = "secret"

    def __init__(self) -> None:
        self.folders = {"f1": {"id": "f1", "title": "Arbeit", "parent_id": ""},
                        "f2": {"id": "f2", "title": "Projekte", "parent_id": "f1"}}
        self.notes = {"n1": {"id": "n1", "parent_id": "f2", "title": "Plan",
                             "body": "# Plan\n- [ ] eins\n  - [x] zwei\ntext",
                             "user_created_time": 1000, "user_updated_time": 5000}}
        self.events = 7
        self.auth_status = "waiting"
        self.counter = 0

    def _id(self) -> str:
        self.counter += 1
        return f"x{self.counter}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        q = dict(request.url.params)
        if path == "/ping":
            return httpx.Response(200, text="JoplinClipperServer")
        if path == "/auth":
            return httpx.Response(200, json={"auth_token": "pair"})
        if path == "/auth/check":
            body = {"status": self.auth_status}
            if self.auth_status == "accepted":
                body["token"] = self.TOKEN
            return httpx.Response(200, json=body)
        if q.get("token") != self.TOKEN:
            return httpx.Response(403, json={"error": "Invalid token"})
        data = json.loads(request.content) if request.content else {}
        parts = path.strip("/").split("/")
        m = request.method
        if parts == ["events"]:
            if "cursor" not in q:
                return httpx.Response(200, json={"items": [], "has_more": False, "cursor": str(self.events)})
            items = [{"id": i} for i in range(int(q["cursor"]), self.events)]
            return httpx.Response(200, json={"items": items, "has_more": False, "cursor": str(self.events)})
        if parts == ["folders"] and m == "GET":
            return httpx.Response(200, json={"items": list(self.folders.values()), "has_more": False})
        if parts == ["folders"] and m == "POST":
            fid = self._id()
            self.folders[fid] = {"id": fid, "title": data["title"], "parent_id": ""}
            return httpx.Response(200, json=self.folders[fid])
        if parts[0] == "folders" and len(parts) == 2:
            if parts[1] not in self.folders:
                return httpx.Response(404, json={"error": "Not found"})
            if m == "PUT":
                self.folders[parts[1]]["title"] = data["title"]
                return httpx.Response(200, json=self.folders[parts[1]])
            if m == "DELETE":
                del self.folders[parts[1]]
                return httpx.Response(200)
        if parts[0] == "folders" and len(parts) == 3 and parts[2] == "notes":
            items = [{"id": n["id"]} for n in self.notes.values() if n["parent_id"] == parts[1]]
            return httpx.Response(200, json={"items": items, "has_more": False})
        if parts == ["notes"] and m == "GET":
            items = sorted(self.notes.values(), key=lambda n: -n["user_updated_time"])
            page, limit = int(q.get("page", 1)), int(q.get("limit", 100))
            chunk = items[(page - 1) * limit: page * limit]
            return httpx.Response(200, json={"items": chunk, "has_more": page * limit < len(items)})
        if parts == ["notes"] and m == "POST":
            nid = self._id()
            self.notes[nid] = {"id": nid, "parent_id": data.get("parent_id", ""), "title": data["title"],
                               "body": data["body"], "user_created_time": 9000, "user_updated_time": 9000}
            return httpx.Response(200, json=self.notes[nid])
        if parts[0] == "notes" and len(parts) == 2:
            note = self.notes.get(parts[1])
            if note is None:
                return httpx.Response(404, json={"error": "Not found"})
            if m == "GET":
                return httpx.Response(200, json=note)
            if m == "PUT":
                note.update(data)
                note["user_updated_time"] += 1
                return httpx.Response(200, json=note)
            if m == "DELETE":
                del self.notes[parts[1]]
                return httpx.Response(200)
        return httpx.Response(500, json={"error": f"fake has no {m} {path}"})


@pytest.fixture
def fake() -> FakeJoplin:
    return FakeJoplin()


@pytest.fixture
def store(fake: FakeJoplin, tmp_path: Path) -> JoplinStore:
    client = JoplinClient(41184, transport=httpx.MockTransport(fake.handler))
    return JoplinStore(client, FakeJoplin.TOKEN, "Edge Dash", PinStore(tmp_path / "pins.json"))


def run(coro):
    return asyncio.run(coro)


def test_checklists_round_trip():
    md = "- [ ] a\n  * [x] b\n+ [X] c\n- not a box\ntext - [ ] inline"
    boxes = joplin.boxes_from_markdown(md)
    assert boxes == "☐ a\n  ☑ b\n☑ c\n- not a box\ntext - [ ] inline"
    assert joplin.boxes_to_markdown(boxes) == "- [ ] a\n  - [x] b\n- [x] c\n- not a box\ntext - [ ] inline"


def test_contents_maps_notebooks_and_notes(store: JoplinStore):
    notes, folders = run(store.contents())
    assert [(f.id, f.name) for f in folders] == [("f1", "Arbeit"), ("f2", "Arbeit \u203a Projekte")]
    note = notes[0]
    assert note.folder == "f2" and note.title == "Plan"
    assert note.body == "# Plan\n☐ eins\n  ☑ zwei\ntext"
    assert note.updated_at == 5 and note.created_at == 1
    assert note.pinned is False


def test_new_quick_note_creates_the_notebook(store: JoplinStore, fake: FakeJoplin):
    note = run(store.upsert("Neu", "☐ Milch", folder=QUICK_FOLDER, pinned=True))
    quick = next(f for f in fake.folders.values() if f["title"] == "Edge Dash")
    assert fake.notes[note.id]["parent_id"] == quick["id"]
    assert fake.notes[note.id]["body"] == "- [ ] Milch"
    assert note.folder == QUICK_FOLDER and note.pinned is True and note.body == "☐ Milch"
    # The quick notebook is not listed as a folder of its own.
    _, folders = run(store.contents())
    assert all(f.name != "Edge Dash" for f in folders)
    # A note "in no folder" lands there as well, and only one notebook exists.
    other = run(store.upsert("Ohne", "", folder=""))
    assert other.folder == QUICK_FOLDER
    assert sum(1 for f in fake.folders.values() if f["title"] == "Edge Dash") == 1


def test_update_keeps_folder_unless_given(store: JoplinStore, fake: FakeJoplin):
    note = run(store.upsert("Plan 2", "x", note_id="n1"))
    assert fake.notes["n1"]["parent_id"] == "f2" and note.title == "Plan 2"
    moved = run(store.upsert("Plan 2", "x", note_id="n1", folder="f1"))
    assert moved.folder == "f1"
    # An id Joplin does not know becomes a new note.
    fresh = run(store.upsert("Weg", "", note_id="gone"))
    assert fresh.id != "gone" and fresh.id in fake.notes


def test_delete_and_pins(store: JoplinStore, fake: FakeJoplin):
    run(store.upsert("Plan", "x", note_id="n1", pinned=True))
    assert run(store.contents())[0][0].pinned is True
    assert run(store.delete("n1")) is True
    assert "n1" not in fake.notes and store.pins.load() == set()
    assert run(store.delete("n1")) is False


def test_deleting_a_notebook_keeps_its_notes(store: JoplinStore, fake: FakeJoplin):
    with pytest.raises(ValueError, match="notebooks inside"):
        run(store.delete_folder("f1"))
    assert run(store.delete_folder("f2")) is True
    quick = next(f for f in fake.folders.values() if f["title"] == "Edge Dash")
    assert fake.notes["n1"]["parent_id"] == quick["id"]
    assert "f2" not in fake.folders
    assert run(store.delete_folder("f2")) is False


def test_folders_add_and_rename(store: JoplinStore, fake: FakeJoplin):
    folder = run(store.add_folder("Privat"))
    assert fake.folders[folder.id]["title"] == "Privat"
    renamed = run(store.rename_folder("f2", "Ideen"))
    assert renamed.name == "Arbeit \u203a Ideen"
    assert run(store.rename_folder("nope", "x")) is None


def test_wrong_token_is_auth(fake: FakeJoplin, tmp_path: Path):
    client = JoplinClient(41184, transport=httpx.MockTransport(fake.handler))
    bad = JoplinStore(client, "wrong", pins=PinStore(tmp_path / "p.json"))
    with pytest.raises(JoplinError) as info:
        run(bad.contents())
    assert info.value.key == "auth"


def test_token_file_is_private():
    joplin.store_token("abc")
    path = joplin.config_dir() / "joplin-token.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert joplin.load_token() == "abc"
    joplin.clear_token()
    assert joplin.load_token() == ""


# -- the module ----------------------------------------------------------------

def make_module(fake: FakeJoplin, **config):
    from backend.modules.notes import NotesModule

    module = NotesModule({"storage": "joplin", **config})
    module.client = JoplinClient(41184, transport=httpx.MockTransport(fake.handler))
    return module


def test_pairing_stores_the_token(fake: FakeJoplin, monkeypatch: pytest.MonkeyPatch):
    from backend.modules import notes as notes_module

    monkeypatch.setattr(notes_module, "PAIRING_POLL_S", 0.01)

    async def go():
        module = make_module(fake)
        await module.poll()
        assert module.state == "needs_auth"
        assert (await module.command("connect", {}))["ok"]
        await asyncio.sleep(0.05)
        assert module.state == "pairing"
        fake.auth_status = "accepted"
        await asyncio.sleep(0.05)
        assert module.state == "connected"
        assert joplin.load_token() == FakeJoplin.TOKEN
        await module.teardown()
    run(go())


def test_rejected_pairing(fake: FakeJoplin, monkeypatch: pytest.MonkeyPatch):
    from backend.modules import notes as notes_module

    monkeypatch.setattr(notes_module, "PAIRING_POLL_S", 0.01)
    fake.auth_status = "rejected"

    async def go():
        module = make_module(fake)
        await module.command("connect", {})
        await asyncio.sleep(0.05)
        assert module.state == "needs_auth" and module.error == "rejected"
        assert joplin.load_token() == ""
    run(go())


def test_changes_in_joplin_raise_the_revision(fake: FakeJoplin):
    joplin.store_token(FakeJoplin.TOKEN)

    async def go():
        module = make_module(fake)
        await module.poll()
        assert module.state == "connected"
        start = module.revision
        await module.poll()
        assert module.revision == start               # nothing happened
        fake.events = 9                               # a note changed in Joplin
        await module.poll()
        assert module.revision == start + 1
        fake.folders["f3"] = {"id": "f3", "title": "Neu", "parent_id": ""}
        await module.poll()
        assert module.revision == start + 2           # notebooks have no events
    run(go())


def test_local_file_changes_raise_the_revision():
    from backend.modules.notes import NotesModule

    async def go():
        module = NotesModule({"storage": "local"})
        await module.poll()
        start = module.revision
        module.local.upsert(title="x", body="")
        os.utime(module.local.path, (1, 1))
        await module.poll()
        assert module.revision == start + 1
        assert module.payload()["state"] == "local"
    run(go())


def test_routes_report_joplin_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "c.yaml"
    # Port 9 (discard) is not Joplin, so no real Joplin on this machine is reached.
    cfg.write_text("""
server: { host: "127.0.0.1", port: 8765 }
default_theme: clean
modules:
  notes: { enabled: true, storage: joplin, joplin_port: 9, interval: 60 }
pages: []
""")
    import importlib

    from backend import main as main_mod
    from backend.modules import notes as notes_module
    from backend.modules.base import get_registry

    # Other tests empty the registry; put the notes module back.
    if "notes" not in get_registry():
        importlib.reload(notes_module)
    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    joplin.store_token("abc")
    with TestClient(main_mod.create_app(cfg)) as client:
        r = client.get("/api/notes")
        assert r.status_code == 503 and r.json()["detail"] == "joplin_offline"


def test_token_from_the_settings_wins(fake: FakeJoplin):
    joplin.store_token("stale")

    async def go():
        module = make_module(fake, joplin_token=FakeJoplin.TOKEN)
        await module.poll()
        assert module.state == "connected"
        notes, _ = await module.store.contents()
        assert notes[0].title == "Plan"
    run(go())
