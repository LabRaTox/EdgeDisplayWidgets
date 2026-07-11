#!/usr/bin/env python3
"""Vendor emoji-picker-element (the Quick Actions emoji tab).

The picker is an ES-module Web Component whose ``picker.js`` imports
``./database.js`` — so BOTH files must be vendored together, plus an emojibase
data file for the actual emoji. They're served from our own origin so the
kiosk needs no CDN at runtime (same approach as the Tabler icons).

    python scripts/fetch_emoji_picker.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

PICKER_VERSION = "1.21.1"   # emoji-picker-element
DATA_VERSION = "1.7.0"      # emoji-picker-element-data (emojibase, English)

PICKER_BASE = f"https://cdn.jsdelivr.net/npm/emoji-picker-element@{PICKER_VERSION}"
DATA_URL = (
    f"https://cdn.jsdelivr.net/npm/emoji-picker-element-data@{DATA_VERSION}"
    "/en/emojibase/data.json"
)

OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "frontend" / "vendor" / "emoji-picker-element"
)

# picker.js -> database.js is the whole module closure (database.js is bundled
# and imports nothing further).
FILES = {
    "picker.js": f"{PICKER_BASE}/picker.js",
    "database.js": f"{PICKER_BASE}/database.js",
    "data.json": DATA_URL,
}


def _fetch(url: str) -> bytes:
    print(f"  GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "edge-dashboard-fetch"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (pinned host)
        return resp.read()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fetching emoji-picker-element v{PICKER_VERSION} -> {OUT_DIR}")
    for name, url in FILES.items():
        data = _fetch(url)
        (OUT_DIR / name).write_bytes(data)
        print(f"  wrote {name} ({len(data) / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
