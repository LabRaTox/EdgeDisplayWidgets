"""Tests for the notes REST endpoints + JSON-file persistence."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.modules import heartbeat as heartbeat_module
from backend.modules.base import clear_registry, get_registry
from backend.notes import MAX_NOTES, NotesStore


@pytest.fixture(autouse=True)
def _ensure_heartbeat_registered():
    clear_registry()
    importlib.reload(heartbeat_module)
    assert "heartbeat" in get_registry()
    yield


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    from backend import main as main_mod
    from backend import notes as notes_mod

    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    # Pin notes storage to the tmp dir so the test doesn't touch real data.
    monkeypatch.setattr(notes_mod, "default_notes_path", lambda: tmp_path / "notes.json")
    return main_mod.create_app(cfg)


def test_list_starts_empty(app):
    with TestClient(app) as client:
        r = client.get("/api/notes")
        assert r.status_code == 200
        assert r.json() == {"notes": [], "folders": [], "storage": "local"}


def test_create_then_list(app):
    with TestClient(app) as client:
        r = client.post("/api/notes", json={"title": "Einkauf", "body": "Milch\nBrot"})
        assert r.status_code == 200
        note = r.json()
        assert note["title"] == "Einkauf"
        assert note["body"] == "Milch\nBrot"
        assert note["id"]
        assert note["updated_at"] > 0

        r = client.get("/api/notes")
        notes = r.json()["notes"]
        assert len(notes) == 1
        assert notes[0]["id"] == note["id"]


def test_update_existing(app):
    with TestClient(app) as client:
        r = client.post("/api/notes", json={"title": "v1", "body": "x"})
        nid = r.json()["id"]
        r = client.post("/api/notes", json={"id": nid, "title": "v2", "body": "y"})
        assert r.status_code == 200
        assert r.json()["title"] == "v2"
        r = client.get("/api/notes")
        assert len(r.json()["notes"]) == 1
        assert r.json()["notes"][0]["title"] == "v2"


def test_delete(app):
    with TestClient(app) as client:
        nid = client.post("/api/notes", json={"title": "x"}).json()["id"]
        r = client.delete(f"/api/notes/{nid}")
        assert r.status_code == 200
        r = client.delete(f"/api/notes/{nid}")
        assert r.status_code == 404


def test_persists_across_app_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        """
modules: { heartbeat: { enabled: true, interval: 0.05 } }
pages: [{ id: main, grid: { columns: "1fr", rows: "1fr", areas: ["hb"] },
          widgets: [{ id: heartbeat, area: hb }] }]
"""
    )
    from backend import main as main_mod
    from backend import notes as notes_mod

    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    monkeypatch.setattr(
        notes_mod, "default_notes_path", lambda: tmp_path / "notes.json",
    )
    app1 = main_mod.create_app(cfg)
    with TestClient(app1) as client:
        client.post("/api/notes", json={"title": "persisted", "body": "yes"})

    app2 = main_mod.create_app(cfg)
    with TestClient(app2) as client:
        notes = client.get("/api/notes").json()["notes"]
        assert [n["title"] for n in notes] == ["persisted"]


def test_invalid_payload_rejected(app):
    with TestClient(app) as client:
        r = client.post(
            "/api/notes",
            headers={"Content-Type": "application/json"},
            content=b"not json",
        )
        assert r.status_code == 400


def test_note_limit_enforced(tmp_path: Path):
    store = NotesStore(path=tmp_path / "notes.json")
    for i in range(MAX_NOTES):
        store.upsert(title=f"n{i}", body="")
    with pytest.raises(ValueError, match="note limit"):
        store.upsert(title="overflow", body="")


def test_corrupt_file_treated_as_empty(tmp_path: Path):
    p = tmp_path / "notes.json"
    p.write_text("this is not JSON", encoding="utf-8")
    store = NotesStore(path=p)
    assert store.list() == []
    # Recovery: a write should produce a valid file again.
    store.upsert(title="recovered", body="")
    assert len(store.list()) == 1


def test_old_file_without_folders_loads(tmp_path: Path):
    p = tmp_path / "notes.json"
    p.write_text('{"notes": [{"id": "a", "title": "t", "body": "b", "updated_at": 5}]}', encoding="utf-8")
    store = NotesStore(path=p)
    note = store.list()[0]
    assert note.folder == "" and note.pinned is False
    assert store.folders() == []
    # Updating fills in the creation time from the old timestamp.
    assert store.upsert(title="t2", body="b", note_id="a").created_at == 5


def test_folder_and_pin_kept_unless_given(tmp_path: Path):
    store = NotesStore(path=tmp_path / "notes.json")
    work = store.add_folder("  Arbeit ")
    assert work.name == "Arbeit"
    note = store.upsert(title="x", body="", folder=work.id, pinned=True)
    again = store.upsert(title="y", body="z", note_id=note.id)
    assert again.folder == work.id and again.pinned is True
    moved = store.upsert(title="y", body="z", note_id=note.id, folder="quick", pinned=False)
    assert moved.folder == "quick" and moved.pinned is False
    with pytest.raises(ValueError, match="unknown folder"):
        store.upsert(title="y", body="z", note_id=note.id, folder="nope")


def test_deleting_a_folder_keeps_its_notes(tmp_path: Path):
    store = NotesStore(path=tmp_path / "notes.json")
    folder = store.add_folder("Privat")
    note = store.upsert(title="x", body="", folder=folder.id)
    assert store.delete_folder(folder.id)
    assert store.folders() == []
    assert store.list()[0].id == note.id and store.list()[0].folder == ""
    assert not store.delete_folder(folder.id)


def test_folder_routes(app):
    with TestClient(app) as client:
        r = client.post("/api/notes/folders", json={"name": "Arbeit"})
        assert r.status_code == 200
        folder = r.json()
        assert client.post("/api/notes/folders", json={"name": " "}).status_code == 400
        r = client.post(f"/api/notes/folders/{folder['id']}", json={"name": "Job"})
        assert r.json()["name"] == "Job"
        note = client.post("/api/notes", json={"title": "a", "body": "", "folder": folder["id"],
                                               "pinned": True}).json()
        assert note["folder"] == folder["id"] and note["pinned"] is True
        data = client.get("/api/notes").json()
        assert data["folders"] == [{"id": folder["id"], "name": "Job"}]
        assert client.post("/api/notes", json={"title": "a", "folder": "nope"}).status_code == 400
        assert client.delete(f"/api/notes/folders/{folder['id']}").status_code == 200
        assert client.delete(f"/api/notes/folders/{folder['id']}").status_code == 404
        assert client.get("/api/notes").json()["notes"][0]["folder"] == ""
