#!/usr/bin/env python3
"""Vendor Tabler Icons for the Quick Actions icon picker.

Downloads a *pinned* Tabler release and writes two self-hosted assets into
``frontend/vendor/tabler/`` so the kiosk has no runtime dependency on a CDN
(same philosophy as the self-hosted emoji-picker):

    tabler-sprite.svg   the full outline sprite — referenced from the UI via
                        <use href=".../tabler-sprite.svg#tabler-NAME">
    icons-index.json    a compact search index: {version, icons:[{n, k}]}
                        where `n` is the icon name and `k` is a space-joined
                        keyword blob (name words + tags + category) the picker
                        filters on.

Re-run after bumping ``TABLER_VERSION`` to update the vendored copy.

    python scripts/fetch_tabler_icons.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

TABLER_VERSION = "3.34.0"

SPRITE_URL = (
    f"https://cdn.jsdelivr.net/npm/@tabler/icons-sprite@{TABLER_VERSION}"
    "/dist/tabler-sprite.svg"
)
META_URL = f"https://cdn.jsdelivr.net/npm/@tabler/icons@{TABLER_VERSION}/icons.json"

OUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "vendor" / "tabler"


def _fetch(url: str) -> bytes:
    print(f"  GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "edge-dashboard-fetch"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (pinned host)
        return resp.read()


def _build_index(meta_raw: bytes) -> dict:
    meta = json.loads(meta_raw)
    icons = []
    for name, info in meta.items():
        styles = info.get("styles", {})
        # The sprite ships only outline symbols; skip anything without one.
        if "outline" not in styles:
            continue
        tags = info.get("tags", []) or []
        category = info.get("category", "") or ""
        # Keyword blob: name (with dashes as spaces) + tags + category, deduped.
        words = []
        for chunk in [name.replace("-", " "), *tags, category]:
            for w in str(chunk).lower().split():
                if w and w not in words:
                    words.append(w)
        icons.append({"n": name, "k": " ".join(words)})
    icons.sort(key=lambda x: x["n"])
    return {"version": TABLER_VERSION, "icons": icons}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fetching Tabler Icons v{TABLER_VERSION} -> {OUT_DIR}")

    sprite = _fetch(SPRITE_URL)
    (OUT_DIR / "tabler-sprite.svg").write_bytes(sprite)
    print(f"  wrote tabler-sprite.svg ({len(sprite) / 1024:.0f} KiB)")

    index = _build_index(_fetch(META_URL))
    index_path = OUT_DIR / "icons-index.json"
    index_path.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    print(f"  wrote icons-index.json ({len(index['icons'])} icons)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
