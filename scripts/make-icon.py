#!/usr/bin/env python3
"""Render the app icon into every file the settings window ships with.

The icon itself is defined once, in ``backend/brand.py`` — the tray draws
from the same code. This script exists so the window, its taskbar entry and
the tray cannot drift apart: run it after changing the shapes there.

    uv run python scripts/make-icon.py

Every PNG already present in ``gui/src-tauri/icons`` is re-rendered at its
current size, rather than at a list of sizes kept here. Tauri's icon set has
grown and shrunk between versions; reading the sizes off the files means this
keeps working when it changes again.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import brand  # noqa: E402

ICON_DIR = ROOT / "gui" / "src-tauri" / "icons"
PUBLIC_DIR = ROOT / "gui" / "public"

#: Sizes inside the .ico, which Windows picks from by context.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    if not ICON_DIR.is_dir():
        print(f"icon directory not found: {ICON_DIR}", file=sys.stderr)
        return 1

    written = 0
    for path in sorted(ICON_DIR.glob("*.png")):
        with Image.open(path) as existing:
            width, height = existing.size
        if width != height:
            print(f"skipped (not square): {path.name}")
            continue
        brand.icon_image(width).save(path)
        print(f"{path.name}: {width}x{width}")
        written += 1

    ico = ICON_DIR / "icon.ico"
    if ico.exists():
        largest = max(ICO_SIZES)
        brand.icon_image(largest).save(
            ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES]
        )
        print(f"icon.ico: {', '.join(f'{s}x{s}' for s in ICO_SIZES)}")
        written += 1

    icns = ICON_DIR / "icon.icns"
    if icns.exists():
        # Pillow's ICNS writer needs a 1024 source and is not available on
        # every platform. macOS is not a target here, so a failure is worth a
        # line, not an error.
        try:
            brand.icon_image(1024).save(icns, format="ICNS")
            print("icon.icns: 1024x1024")
            written += 1
        except (OSError, ValueError) as exc:
            print(f"icon.icns skipped: {exc}")

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    svg = PUBLIC_DIR / "icon.svg"
    svg.write_text(brand.icon_svg(64), encoding="utf-8")
    print(f"{svg.relative_to(ROOT)}")
    written += 1

    print(f"\n{written} file(s) written from backend/brand.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
