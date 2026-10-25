"""Notes persistence — JSON file under XDG_DATA_HOME.

Stores plain-text notes and the folders they are sorted into, one file for
the whole dashboard. The frontend talks to this via REST (`/api/notes`), not
WebSocket, because notes only change on user action and don't need
broadcast semantics.

A note's `folder` is a folder id, `"quick"` for the built-in quick notes, or
empty for none. Files written before folders existed have neither folders
nor the new note fields; they load with the defaults.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

MAX_TITLE_LEN = 200
MAX_BODY_LEN = 50_000
MAX_NOTES = 500
MAX_FOLDERS = 50
MAX_FOLDER_NAME_LEN = 60

#: The folder every dashboard has; it is not stored and cannot be deleted.
QUICK_FOLDER = "quick"


class Note(BaseModel):
    id: str
    title: str = Field(default="", max_length=MAX_TITLE_LEN)
    body: str = Field(default="", max_length=MAX_BODY_LEN)
    folder: str = ""
    pinned: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0


class Folder(BaseModel):
    id: str
    name: str = Field(default="", max_length=MAX_FOLDER_NAME_LEN)


def default_notes_path() -> Path:
    """Resolve the on-disk notes file, honouring XDG_DATA_HOME."""
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "edge-dashboard" / "notes.json"


class NotesStore:
    """File-backed list of notes with simple atomic writes."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_notes_path()

    # ------------------------------------------------------------------ io
    def _read(self) -> tuple[list[Note], list[Folder]]:
        if not self.path.is_file():
            return [], []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"notes: failed to read {self.path}: {exc}")
            return [], []
        items = raw.get("notes") if isinstance(raw, dict) else raw
        folder_items = raw.get("folders") if isinstance(raw, dict) else []
        notes: list[Note] = []
        for item in items if isinstance(items, list) else []:
            try:
                notes.append(Note.model_validate(item))
            except Exception as exc:
                logger.warning(f"notes: dropping invalid entry: {exc}")
        folders: list[Folder] = []
        for item in folder_items if isinstance(folder_items, list) else []:
            try:
                folders.append(Folder.model_validate(item))
            except Exception as exc:
                logger.warning(f"notes: dropping invalid folder: {exc}")
        # A note in a folder that no longer exists is in none.
        known = {f.id for f in folders} | {QUICK_FOLDER}
        for note in notes:
            if note.folder and note.folder not in known:
                note.folder = ""
        return notes, folders

    def load(self) -> list[Note]:
        return self._read()[0]

    def contents(self) -> tuple[list[Note], list[Folder]]:
        """Notes and folders from one read of the file."""
        return self._read()

    def folders(self) -> list[Folder]:
        return self._read()[1]

    def _write(self, notes: list[Note], folders: list[Folder] | None = None) -> None:
        if folders is None:
            folders = self.folders()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"notes": [n.model_dump() for n in notes],
                   "folders": [f.model_dump() for f in folders]}
        # Atomic write: stage to .tmp then rename, so a crash mid-write can't
        # corrupt the file the next reload reads.
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.path)

    # ---------------------------------------------------------- operations
    def list(self) -> list[Note]:
        return self.load()

    def upsert(self, title: str, body: str, note_id: str | None = None, *,
               folder: str | None = None, pinned: bool | None = None) -> Note:
        """Create or update a note. `folder` and `pinned` left as None keep
        what the note has (or the defaults for a new one)."""
        notes, folders = self._read()
        if folder is not None and folder and folder not in {f.id for f in folders} | {QUICK_FOLDER}:
            raise ValueError(f"unknown folder {folder}")
        now = time.time()
        for i, n in enumerate(notes):
            if note_id and n.id == note_id:
                notes[i] = n.model_copy(update={
                    "title": title, "body": body, "updated_at": now,
                    "folder": n.folder if folder is None else folder,
                    "pinned": n.pinned if pinned is None else pinned,
                    "created_at": n.created_at or n.updated_at or now,
                })
                self._write(notes, folders)
                return notes[i]
        if not note_id and len(notes) >= MAX_NOTES:
            raise ValueError(f"note limit reached ({MAX_NOTES})")
        # An id supplied but unknown is taken as a new note with that id.
        new = Note(id=note_id or secrets.token_urlsafe(8), title=title, body=body,
                   folder=folder or "", pinned=bool(pinned), created_at=now, updated_at=now)
        notes.append(new)
        self._write(notes, folders)
        return new

    def delete(self, note_id: str) -> bool:
        notes, folders = self._read()
        kept = [n for n in notes if n.id != note_id]
        if len(kept) == len(notes):
            return False
        self._write(kept, folders)
        return True

    def add_folder(self, name: str) -> Folder:
        notes, folders = self._read()
        if len(folders) >= MAX_FOLDERS:
            raise ValueError(f"folder limit reached ({MAX_FOLDERS})")
        folder = Folder(id=secrets.token_urlsafe(6), name=name.strip()[:MAX_FOLDER_NAME_LEN])
        folders.append(folder)
        self._write(notes, folders)
        return folder

    def rename_folder(self, folder_id: str, name: str) -> Folder | None:
        notes, folders = self._read()
        for i, f in enumerate(folders):
            if f.id == folder_id:
                folders[i] = Folder(id=f.id, name=name.strip()[:MAX_FOLDER_NAME_LEN])
                self._write(notes, folders)
                return folders[i]
        return None

    def delete_folder(self, folder_id: str) -> bool:
        """Remove a folder; its notes stay, in no folder."""
        notes, folders = self._read()
        kept = [f for f in folders if f.id != folder_id]
        if len(kept) == len(folders):
            return False
        for note in notes:
            if note.folder == folder_id:
                note.folder = ""
        self._write(notes, kept)
        return True


def public_view(notes: list[Note], folders: list[Folder] | None = None) -> dict[str, Any]:
    return {"notes": [n.model_dump() for n in notes],
            "folders": [f.model_dump() for f in folders or []]}
