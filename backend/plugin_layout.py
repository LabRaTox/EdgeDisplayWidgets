"""Where installed widgets live and what is in their folder.

Widgets and themes from the store are installed into one folder each,
outside the repository. A widget:

    ~/.local/share/edge-dashboard/plugins/<id>/
        manifest.json     what the store published, unchanged
        Widget.qml        the view (the manifest's `view` may name another)
        module.py         optional, the manifest's `module`
        locales/de.json   optional, texts in the widget's own key space
        .install.json     written by the installer: version, checksum, findings

A theme (`"type": "theme"` in the manifest) brings a stylesheet instead, in
the same form as the files in `frontend/css/themes/`, and optionally the
fonts it names:

    ~/.local/share/edge-dashboard/plugins/<id>/
        manifest.json
        theme.css         the manifest's `css` may name another
        fonts/*.ttf       optional, registered with the kiosk

Both the backend and the kiosk read this layout, and the kiosk runs on the
system Python without the backend's dependencies. That is why this file uses
the standard library only and nothing else from `backend` imports into it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The app name the store files these widgets under.
APP = "edgedash"

#: A store id: what the store accepts as a slug, and therefore the only shape
#: a folder name here can have. Checked before an id becomes a path.
SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{2,39}$")

#: Written by the installer, read by everyone else. Starts with a dot so it
#: can never clash with a file the widget brings.
INSTALL_FILE = ".install.json"

DEFAULT_VIEW = "Widget.qml"
DEFAULT_CSS = "theme.css"

#: What an installed plugin can be.
TYPES = ("widget", "theme")

#: Font files a theme may bring along in `fonts/`.
FONT_SUFFIXES = (".ttf", ".otf", ".woff2")


def plugins_dir() -> Path:
    """The folder that holds one subfolder per installed widget.

    Read on every call rather than once at import, so a test can point
    `EDGE_PLUGINS_DIR` somewhere else without reloading anything.
    """
    explicit = os.environ.get("EDGE_PLUGINS_DIR")
    if explicit:
        return Path(explicit)
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "edge-dashboard" / "plugins"


def inside(base: Path, relative: object) -> Path | None:
    """`base / relative`, if that is a file that stays inside `base`."""
    if not isinstance(relative, str) or not relative or relative.startswith("/"):
        return None
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@dataclass
class Plugin:
    """One installed widget, as read from its folder."""

    id: str
    path: Path
    manifest: dict[str, Any]
    install: dict[str, Any] = field(default_factory=dict)

    @property
    def version(self) -> str:
        return str(self.manifest.get("version", ""))

    @property
    def type(self) -> str:
        return str(self.manifest.get("type", "widget"))

    @property
    def css_file(self) -> Path | None:
        if self.type != "theme":
            return None
        return inside(self.path, self.manifest.get("css", DEFAULT_CSS))

    @property
    def font_files(self) -> list[Path]:
        if self.type != "theme" or not (self.path / "fonts").is_dir():
            return []
        found = (inside(self.path, f"fonts/{p.name}") for p in sorted((self.path / "fonts").iterdir()))
        return [p for p in found if p is not None and p.suffix.lower() in FONT_SUFFIXES]

    @property
    def view_file(self) -> Path | None:
        if self.type != "widget":
            return None
        return inside(self.path, self.manifest.get("view", DEFAULT_VIEW))

    @property
    def module_file(self) -> Path | None:
        if "module" not in self.manifest:
            return None
        return inside(self.path, self.manifest["module"])

    @property
    def modules(self) -> list[str]:
        """The backend modules this widget subscribes to, as declared."""
        raw = self.manifest.get("modules") or []
        return [m for m in raw if isinstance(m, str)] if isinstance(raw, list) else []

    def text(self, key: str, language: str) -> str:
        """A manifest text in one language: `name` and `summary` may be a
        plain string or one string per language code."""
        value = self.manifest.get(key)
        if isinstance(value, dict):
            return str(value.get(language) or value.get("en") or next(iter(value.values()), ""))
        return str(value or "")

    def locale(self, language: str) -> dict[str, str]:
        """The widget's own texts, restricted to the keys that belong to it.

        A widget may name its title, its options and the settings of its own
        modules. It may not reword anything else: a `nav.layout` in a widget's
        locale file is dropped, not merged over the dashboard's.
        """
        directory = self.path / "locales"
        path = directory / f"{language}.json"
        if not path.is_file():
            path = directory / "en.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        prefixes = tuple(
            [f"widget.{self.id}.", f"settings.widget.{self.id}."]
            + [f"settings.mod.{name}." for name in self.modules]
        )
        return {k: str(v) for k, v in data.items()
                if isinstance(k, str) and k.startswith(prefixes) and isinstance(v, str)}


def read_manifest(directory: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load(plugin_id: str) -> Plugin | None:
    """One installed widget, or None.

    The folder name, the manifest's `id` and the app must all agree. A folder
    that someone copied in by hand under another name is not picked up.
    """
    if not SAFE_ID.match(plugin_id):
        return None
    directory = plugins_dir() / plugin_id
    manifest = read_manifest(directory)
    if manifest is None or manifest.get("id") != plugin_id or manifest.get("app") != APP:
        return None
    try:
        install = json.loads((directory / INSTALL_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        install = {}
    return Plugin(plugin_id, directory, manifest, install if isinstance(install, dict) else {})


def installed(kind: str | None = None) -> list[Plugin]:
    """Every installed plugin, sorted by id; with `kind`, only widgets or themes."""
    base = plugins_dir()
    if not base.is_dir():
        return []
    found = (load(p.name) for p in sorted(base.iterdir()) if p.is_dir())
    return [p for p in found if p is not None and (kind is None or p.type == kind)]


def locale(language: str) -> dict[str, str]:
    """The texts of every installed widget for one language, merged."""
    merged: dict[str, str] = {}
    for plugin in installed("widget"):
        merged.update(plugin.locale(language))
    return merged
