"""Notes persistence — JSON file under XDG_DATA_HOME.

Stores a small set of plain-text notes, one file for the whole dashboard.
The frontend talks to this via REST (`/api/notes`), not WebSocket, because
notes only change on user action and don't need broadcast semantics.
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
MAX_NOTES = 50


class Note(BaseModel):
    id: str
    title: str = Field(default="", max_length=MAX_TITLE_LEN)
    body: str = Field(default="", max_length=MAX_BODY_LEN)
    updated_at: float = 0.0


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
    def load(self) -> list[Note]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"notes: failed to read {self.path}: {exc}")
            return []
        items = raw.get("notes") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return []
        out: list[Note] = []
        for item in items:
            try:
                out.append(Note.model_validate(item))
            except Exception as exc:
                logger.warning(f"notes: dropping invalid entry: {exc}")
        return out

    def _write(self, notes: list[Note]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"notes": [n.model_dump() for n in notes]}
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

    def upsert(self, title: str, body: str, note_id: str | None = None) -> Note:
        notes = self.load()
        now = time.time()
        if note_id:
            for i, n in enumerate(notes):
                if n.id == note_id:
                    notes[i] = Note(id=note_id, title=title, body=body, updated_at=now)
                    self._write(notes)
                    return notes[i]
            # ID supplied but unknown — treat as new note with that id.
            new = Note(id=note_id, title=title, body=body, updated_at=now)
        else:
            if len(notes) >= MAX_NOTES:
                raise ValueError(f"note limit reached ({MAX_NOTES})")
            new = Note(
                id=secrets.token_urlsafe(8), title=title, body=body, updated_at=now,
            )
        notes.append(new)
        self._write(notes)
        return new

    def delete(self, note_id: str) -> bool:
        notes = self.load()
        kept = [n for n in notes if n.id != note_id]
        if len(kept) == len(notes):
            return False
        self._write(kept)
        return True


def public_view(notes: list[Note]) -> dict[str, Any]:
    return {"notes": [n.model_dump() for n in notes]}
