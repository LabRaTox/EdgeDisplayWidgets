"""Which QML file draws which widget.

The window finds a widget's view by name: the id from the layout becomes a
file name, and that file is loaded. `disk_usage` is `DiskUsage.qml`.

A widget installed from the store has its view in its own folder instead,
named by its manifest (see `backend/plugin_layout.py`). Built-in views are
looked up first, so an installed widget can never take over a built-in id.

Kept apart from the bridge because it is a question about a path and not about
Qt, which also makes it testable without a Qt application.
"""

from __future__ import annotations

import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    # For `backend.plugin_layout`, which is standard library only and shared
    # with the backend. Nothing else from `backend` is imported here.
    sys.path.append(str(_ROOT))

from backend import plugin_layout  # noqa: E402

#: A widget id, as it may appear in the config. Checked before it is turned
#: into a file name, because the config is a file anyone can edit and
#: `../../something` would otherwise be a path.
SAFE_WIDGET = re.compile(r"^[a-z][a-z0-9_-]*$")

VIEWS_DIR = pathlib.Path(__file__).resolve().parent / "qml" / "widgets"

#: Building blocks in the same directory that are not widgets themselves.
SHARED = frozenset({"MetricWidget", "Temperatures"})


def view_path(widget_id: str) -> pathlib.Path | None:
    """The QML file for one widget id, or None when there is none."""
    if not SAFE_WIDGET.match(widget_id):
        return None
    name = "".join(part.capitalize() for part in re.split(r"[-_]", widget_id))
    path = VIEWS_DIR / f"{name}.qml"
    if path.is_file():
        return path
    plugin = plugin_layout.load(widget_id)
    return plugin.view_file if plugin else None


def view_version(widget_id: str) -> str:
    """The installed version of a store widget, "" for a built-in one.

    The window appends it to the view's URL. QML caches a component by its
    URL, so an updated widget would otherwise keep showing its old view
    until the kiosk restarts.
    """
    path = view_path(widget_id)
    if path is None or path.parent == VIEWS_DIR:
        return ""
    plugin = plugin_layout.load(widget_id)
    if plugin is None or plugin.view_file != path:
        return ""
    return str(plugin.install.get("sha256", ""))[:12] or plugin.version


def widget_id(file_name: str) -> str:
    """The id a view file belongs to: `DiskUsage.qml` is `disk_usage`."""
    stem = file_name.removesuffix(".qml")
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in stem).lstrip("_")
