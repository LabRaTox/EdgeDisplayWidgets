"""Which QML file draws which widget.

The window finds a widget's view by name: the id from the layout becomes a
file name, and that file is loaded. `disk_usage` is `DiskUsage.qml`.

Kept apart from the bridge because it is a question about a path and not about
Qt, which also makes it testable without a Qt application.
"""

from __future__ import annotations

import pathlib
import re

#: A widget id, as it may appear in the config. Checked before it is turned
#: into a file name, because the config is a file anyone can edit and
#: `../../something` would otherwise be a path.
SAFE_WIDGET = re.compile(r"^[a-z][a-z0-9_]*$")

VIEWS_DIR = pathlib.Path(__file__).resolve().parent / "qml" / "widgets"

#: Building blocks in the same directory that are not widgets themselves.
SHARED = frozenset({"MetricWidget", "Temperatures"})


def view_path(widget_id: str) -> pathlib.Path | None:
    """The QML file for one widget id, or None when there is none."""
    if not SAFE_WIDGET.match(widget_id):
        return None
    name = "".join(part.capitalize() for part in widget_id.split("_"))
    path = VIEWS_DIR / f"{name}.qml"
    return path if path.is_file() else None


def widget_id(file_name: str) -> str:
    """The id a view file belongs to: `DiskUsage.qml` is `disk_usage`."""
    stem = file_name.removesuffix(".qml")
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in stem).lstrip("_")
