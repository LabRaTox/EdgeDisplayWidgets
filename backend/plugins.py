"""Installing, removing and loading widgets from the store.

The folder layout is in `plugin_layout`, which the kiosk shares. This file is
the backend's half: it unpacks archives and imports the Python a widget
brings.

**Installing is strict, on purpose.** An installed widget's module runs inside
this process with the user's rights, the same as a DECK//SWITCH plugin does in
the deck software. The checksum the store published is therefore checked
*before* the archive is opened, and nothing in the archive may point outside
the folder it is unpacked into. The store's review stands between an author
and this machine; the checksum makes sure that what arrives is what was
reviewed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import stat
import sys
import time
import types
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from loguru import logger

from . import plugin_layout
from .modules.base import get_registry, unregister_module
from .plugin_layout import APP, INSTALL_FILE, SAFE_ID, Plugin

#: The same limits as the store and the deck software's installer: what the
#: store accepts must unpack here, and nothing larger than that may.
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_UNPACKED_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 20_000

#: Python names under which installed modules are imported. Kept apart from
#: `backend.modules` so a widget can never stand in for a built-in module.
PACKAGE = "edge_plugins"


class PluginError(Exception):
    """An archive or a widget that cannot be installed; the text says why."""


def version_tuple(version: str) -> tuple[int, ...]:
    """`"1.10.2"` as `(1, 10, 2)`, compared the way the store compares.

    Digits at the start of each part count, the rest does not: `1.0.0-beta`
    is `1.0.0`. Comparing strings would make `1.10` older than `1.9`.
    """
    parts = []
    for piece in str(version or "").split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def newer(candidate: str, current: str) -> bool:
    a, b = version_tuple(candidate), version_tuple(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


# --------------------------------------------------------------------- checks

def check_manifest(manifest: dict[str, Any], *, expected_id: str, app_version: str) -> None:
    """Refuse a manifest that is not an Edge Dash widget, or not this one."""
    if manifest.get("app") != APP:
        raise PluginError(f"not an Edge Dash plugin (app: {manifest.get('app')!r})")
    if manifest.get("type", "widget") not in plugin_layout.TYPES:
        raise PluginError(f"unknown type {manifest.get('type')!r}")
    if manifest.get("type") == "theme" and "module" in manifest:
        raise PluginError("a theme cannot bring a module")
    plugin_id = manifest.get("id")
    if not isinstance(plugin_id, str) or not SAFE_ID.match(plugin_id):
        raise PluginError(f"invalid id {plugin_id!r}")
    if expected_id and plugin_id != expected_id:
        # The store is asked for one widget and hands over another: install
        # neither, whatever the reason.
        raise PluginError(f"archive contains '{plugin_id}', expected '{expected_id}'")
    needed = str(manifest.get("min_app_version") or "")
    if needed and newer(needed, app_version):
        raise PluginError(f"needs Edge Dash {needed} or newer, this is {app_version}")


def _check_checksum(data: bytes, expected: str) -> None:
    actual = hashlib.sha256(data).hexdigest()
    if not expected or actual != expected.lower():
        raise PluginError("checksum does not match; the archive was not opened")


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Every entry, after refusing anything that could leave the folder.

    Absolute paths, `..`, backslashes and links are not unpacked at all.
    A zip carries a link as a file whose mode says so; extracting it as a
    file would be harmless, but a widget that relies on one is broken anyway.
    """
    entries = archive.infolist()
    if len(entries) > MAX_ENTRIES:
        raise PluginError(f"archive has more than {MAX_ENTRIES} entries")
    if sum(e.file_size for e in entries) > MAX_UNPACKED_BYTES:
        raise PluginError("archive is too large once unpacked")
    for entry in entries:
        name = entry.filename
        path = PurePosixPath(name)
        if "\\" in name or path.is_absolute() or ".." in path.parts:
            raise PluginError(f"unsafe path in archive: {name}")
        mode = entry.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise PluginError(f"link in archive: {name}")
    return entries


def _find_root(staging: Path) -> Path:
    """The folder holding `manifest.json`: the top level or one folder below."""
    if (staging / "manifest.json").is_file():
        return staging
    candidates = [p for p in staging.iterdir() if p.is_dir() and (p / "manifest.json").is_file()]
    if len(candidates) != 1:
        raise PluginError("archive must contain exactly one manifest.json")
    return candidates[0]


# ------------------------------------------------------------ install, remove

def install_archive(
    data: bytes,
    *,
    sha256: str,
    expected_id: str,
    app_version: str,
    meta: dict[str, Any] | None = None,
) -> Plugin:
    """Unpack a store archive into the plugins folder, replacing any older copy.

    The new copy is unpacked next to the old one and only swapped in once it
    passed every check, so a failed update leaves the installed version as it
    was.
    """
    if len(data) > MAX_ARCHIVE_BYTES:
        raise PluginError("archive is larger than 64 MB")
    _check_checksum(data, sha256)

    base = plugin_layout.plugins_dir()
    base.mkdir(parents=True, exist_ok=True)
    staging = base / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                archive.extractall(staging, members=_safe_members(archive))
        except zipfile.BadZipFile as exc:
            raise PluginError(f"not a zip archive: {exc}") from exc

        root = _find_root(staging)
        manifest = plugin_layout.read_manifest(root)
        if manifest is None:
            raise PluginError("manifest.json is not readable")
        check_manifest(manifest, expected_id=expected_id, app_version=app_version)
        plugin_id = manifest["id"]

        candidate = Plugin(plugin_id, root, manifest)
        if candidate.type == "theme":
            css = candidate.css_file
            if css is None or css.suffix != ".css":
                raise PluginError(f"css {manifest.get('css', plugin_layout.DEFAULT_CSS)!r} is missing")
        else:
            view = candidate.view_file
            if view is None or view.suffix != ".qml":
                raise PluginError(f"view {manifest.get('view', plugin_layout.DEFAULT_VIEW)!r} is missing")
            if "module" in manifest and candidate.module_file is None:
                raise PluginError(f"module {manifest['module']!r} is missing")

        record = {"version": manifest.get("version", ""), "sha256": sha256.lower(),
                  "installed_at": time.time(), **(meta or {})}
        (root / INSTALL_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")

        target = base / plugin_id
        old = base / f".old-{uuid.uuid4().hex}"
        if target.exists():
            target.rename(old)
        try:
            root.rename(target)
        except OSError:
            if old.exists():
                old.rename(target)
            raise
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    installed = plugin_layout.load(plugin_id)
    if installed is None:  # pragma: no cover, checked above
        raise PluginError("widget could not be read back after installing")
    logger.info(f"installed widget '{plugin_id}' {installed.version}")
    return installed


def uninstall(plugin_id: str) -> None:
    if not SAFE_ID.match(plugin_id):
        raise PluginError(f"invalid id {plugin_id!r}")
    unload_module(plugin_id)
    target = plugin_layout.plugins_dir() / plugin_id
    if not target.is_dir():
        raise PluginError(f"'{plugin_id}' is not installed")
    shutil.rmtree(target)
    logger.info(f"removed widget '{plugin_id}'")


# ------------------------------------------------------------- module loading

#: Which module names each installed widget registered, so they can be taken
#: out again on removal or update.
_LOADED: dict[str, list[str]] = {}


def _import_name(plugin_id: str) -> str:
    return f"{PACKAGE}.{plugin_id.replace('-', '_')}"


def unload_module(plugin_id: str) -> None:
    for name in _LOADED.pop(plugin_id, []):
        unregister_module(name)
    _forget(_import_name(plugin_id))


def _forget(name: str) -> None:
    """Drop a widget's module and everything it imported from its folder."""
    for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        del sys.modules[key]


def _ensure_namespace() -> None:
    """`edge_plugins` as an empty package, the parent of every widget's module.

    A widget's module is imported as a package rooted at its own folder, so
    it can bring helpers and import them relatively (`from .client import
    fetch`). Relative imports need the parent package to exist.
    """
    if PACKAGE not in sys.modules:
        namespace = types.ModuleType(PACKAGE)
        namespace.__path__ = []  # a package, but nothing to find in it
        sys.modules[PACKAGE] = namespace


def load_module(plugin: Plugin) -> list[str]:
    """Import a widget's module and return the module names it registered.

    A widget may register only what its manifest lists under `modules`, and
    nothing that already exists. Registering `weather` would otherwise
    replace the built-in weather module for every widget that uses it.
    """
    unload_module(plugin.id)
    path = plugin.module_file if plugin.type == "widget" else None
    if path is None:
        # Recorded all the same: a rescan tells new plugins from known ones
        # by this map, and a theme or a widget without a module is known too.
        _LOADED[plugin.id] = []
        return []

    before = set(get_registry())
    name = _import_name(plugin.id)
    _ensure_namespace()
    # A package rooted at the widget's folder: `from .helpers import x` in
    # the module finds `helpers.py` or `helpers/` next to it, and nothing
    # outside the folder.
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(plugin.path)]
    )
    if spec is None or spec.loader is None:
        raise PluginError(f"cannot import {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        _forget(name)
        for added in set(get_registry()) - before:
            unregister_module(added)
        raise

    added = sorted(set(get_registry()) - before)
    undeclared = [n for n in added if n not in plugin.modules]
    if undeclared:
        for n in added:
            unregister_module(n)
        _forget(name)
        raise PluginError(f"'{plugin.id}' registers modules it does not declare: {undeclared}")
    _LOADED[plugin.id] = added
    return added


def load_all() -> None:
    """Import the modules of every installed widget, at startup.

    One broken widget is logged and skipped, the same as a built-in module
    that fails to import.
    """
    for plugin in plugin_layout.installed():
        try:
            names = load_module(plugin)
        except Exception as exc:
            logger.exception(f"failed to load widget '{plugin.id}': {exc}")
            continue
        if names:
            logger.info(f"widget '{plugin.id}' registered {', '.join(names)}")
