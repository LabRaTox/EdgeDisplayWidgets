"""What a plugin needs besides its own files.

Any plugin may name its needs in the manifest:

    "dependencies": {
      "python": ["icalendar>=6.0"],
      "system": ["ffmpeg", {"arch": "python-gobject", "debian": "python3-gi"}]
    }

`python` lists packages from PyPI. They need no special rights: each plugin
gets a folder of its own under `<plugins>/.deps/`, filled with `uv` and put
at the end of `sys.path` when the plugin loads, so a plugin can add packages
but never replace one the backend runs on. Only finished wheels are taken,
so nothing from a package runs during the installation. Two plugins that ask
for different versions of one package share the one that loads first.

`system` lists packages of the distribution. A plain name means the same on
all of them; where the names differ, an object gives one per family: `arch`,
`debian` (Ubuntu too) and `fedora`. Those need root, so `pkexec` asks the
user. If that is not possible or the user declines, the error carries the
command to run by hand. On an image-based Fedora such as Bazzite a package
only arrives with the next boot, so there it is always the user's turn.
Without a package manager we know, each name is looked for as a program.

Everything has to be there before a plugin is installed: `ensure` raises
when something is missing, and the installer stops there.
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import importlib.metadata
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

from . import host, plugin_layout

#: How long one installation may take, the password dialog included.
TIMEOUT_S = 300
#: A package name. No leading dash, so a name can never be an option.
_SYSTEM_NAME = re.compile(r"^[A-Za-z0-9@_+][A-Za-z0-9@._+:-]{0,127}$")
#: The families a `system` entry can name a package for.
FAMILIES = ("arch", "debian", "fedora")
#: Marks a system that boots an image, as `ostree` itself documents it.
OSTREE_BOOTED = Path("/run/ostree-booted")
#: Where `uv` ends up when no package brought it. A systemd unit has none of
#: these on its PATH, so the login shell finding `uv` proves nothing here.
UV_PLACES = ("~/.local/bin/uv", "~/.cargo/bin/uv", "/home/linuxbrew/.linuxbrew/bin/uv")


class DependencyError(Exception):
    """A plugin's needs are malformed or could not be met."""


def _list(section: dict[str, Any], key: str) -> list[Any]:
    values = section.get(key, [])
    if not isinstance(values, list):
        raise DependencyError(f"dependencies.{key} must be a list")
    return values


def declared(manifest: dict[str, Any]) -> dict[str, list[Any]]:
    """The manifest's `dependencies`, checked.

    Python packages must come from the package index under their name: a
    direct URL would skip every look the store takes at a plugin.
    """
    section = manifest.get("dependencies", {})
    if not isinstance(section, dict):
        raise DependencyError("dependencies must be an object")
    python = _list(section, "python")
    system = _list(section, "system")
    for spec in python:
        if not isinstance(spec, str):
            raise DependencyError(f"invalid Python dependency {spec!r}")
        try:
            requirement = Requirement(spec)
        except InvalidRequirement as exc:
            raise DependencyError(f"invalid Python dependency {spec!r}") from exc
        if requirement.url:
            raise DependencyError(f"Python dependency {spec!r} points at a URL")
    for entry in system:
        names = entry.values() if isinstance(entry, dict) else [entry]
        if not names or (isinstance(entry, dict) and set(entry) - set(FAMILIES)):
            raise DependencyError(f"invalid system dependency {entry!r}")
        for name in names:
            if not isinstance(name, str) or not _SYSTEM_NAME.match(name):
                raise DependencyError(f"invalid system dependency {entry!r}")
    return {"python": python, "system": system}


def folder(plugin_id: str) -> Path:
    """Where a plugin's Python packages live."""
    return plugin_layout.plugins_dir() / ".deps" / plugin_id


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return host.run(command, timeout=TIMEOUT_S)


def _satisfied(spec: str, search: list[str]) -> bool:
    requirement = Requirement(spec)
    if requirement.marker is not None and not requirement.marker.evaluate():
        return True
    # An extra adds packages of its own, which the version alone does not show.
    if requirement.extras:
        return False
    found = next(iter(importlib.metadata.distributions(name=requirement.name, path=search)), None)
    if found is None:
        return False
    return requirement.specifier.contains(found.version, prereleases=True)


def missing_python(plugin_id: str, specs: list[str]) -> list[str]:
    # What another plugin brought does not count: it leaves with that plugin.
    others = str(folder(plugin_id).parent)
    search = [str(folder(plugin_id)), *(path for path in sys.path if not path.startswith(others))]
    return [spec for spec in specs if not _satisfied(spec, search)]


def _pacman_missing(names: list[str]) -> list[str]:
    # `pacman -T` prints what is not installed, one name per line.
    return _run(["pacman", "-T", *names]).stdout.split()


def _dpkg_missing(names: list[str]) -> list[str]:
    def present(name: str) -> bool:
        return "install ok installed" in _run(["dpkg-query", "-W", "-f=${Status}", name]).stdout

    return [name for name in names if not present(name)]


def _rpm_missing(names: list[str]) -> list[str]:
    return [name for name in names if _run(["rpm", "-q", "--whatprovides", name]).returncode != 0]


@dataclasses.dataclass(frozen=True)
class PackageManager:
    family: str
    missing: Callable[[list[str]], list[str]]
    #: What to run by hand.
    manual: tuple[str, ...]
    #: What `pkexec` runs; empty where installing cannot finish on its own.
    automatic: tuple[str, ...] = ()
    #: Said after the command when the package takes more than that.
    afterwards: str = " and install again"

    def command(self, names: list[str]) -> str:
        return shlex.join([*self.manual, *names])


PACMAN = PackageManager("arch", _pacman_missing, ("sudo", "pacman", "-S", "--needed"),
                        ("pacman", "-S", "--needed", "--noconfirm"))
APT = PackageManager("debian", _dpkg_missing, ("sudo", "apt", "install"),
                     ("apt-get", "install", "-y"))
DNF = PackageManager("fedora", _rpm_missing, ("sudo", "dnf", "install"),
                     ("dnf", "install", "-y"))
RPM_OSTREE = PackageManager("fedora", _rpm_missing, ("sudo", "rpm-ostree", "install"),
                            afterwards=", restart and install again")


def package_manager() -> PackageManager | None:
    """The one that owns this system. An image comes first: `dnf` can be
    present there, but it cannot change the image."""
    if OSTREE_BOOTED.exists() and shutil.which("rpm-ostree"):
        return RPM_OSTREE
    if shutil.which("pacman"):
        return PACMAN
    if shutil.which("apt-get") and shutil.which("dpkg-query"):
        return APT
    if shutil.which("dnf"):
        return DNF
    return None


def _names_for(entries: list[Any], family: str) -> list[str]:
    """The package names on this family. An entry without a name for it stops
    the installation, since guessing could fetch something else entirely."""
    names = []
    for entry in entries:
        if isinstance(entry, str):
            names.append(entry)
        elif family in entry:
            names.append(entry[family])
        else:
            raise DependencyError(f"needs {' / '.join(entry.values())}, "
                                  f"which has no package named for {family}")
    return names


def _without_manager(entries: list[Any]) -> None:
    def present(entry: Any) -> bool:
        names = entry.values() if isinstance(entry, dict) else [entry]
        return any(shutil.which(name) for name in names)

    left = [entry for entry in entries if not present(entry)]
    if left:
        names = [" / ".join(e.values()) if isinstance(e, dict) else e for e in left]
        raise DependencyError(f"needs {', '.join(names)}, install them and try again")


def ensure_system(entries: list[Any]) -> None:
    """Have every system package there, or say what the user has to do."""
    if not entries:
        return
    manager = package_manager()
    if manager is None:
        _without_manager(entries)
        return
    names = _names_for(entries, manager.family)
    left = manager.missing(names)
    if left and manager.automatic and shutil.which("pkexec"):
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            _run(["pkexec", *manager.automatic, *left])
        # Judged by the result: pkexec's exit code does not tell a declined
        # password from a package manager that stopped halfway.
        left = manager.missing(left)
    if left:
        raise DependencyError(
            f"needs {', '.join(left)}. Run this{manager.afterwards}: {manager.command(left)}"
        )


def find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    places = (Path(place).expanduser() for place in UV_PLACES)
    return next((str(place) for place in places if place.is_file()), None)


def install_python(plugin_id: str, specs: list[str]) -> None:
    """Fill the plugin's folder anew. The old one stays until that worked."""
    uv = find_uv()
    if uv is None:
        raise DependencyError(f"needs {', '.join(specs)}, and installing them takes uv, "
                              "which is not on this machine")
    target = folder(plugin_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".staging-{uuid.uuid4().hex}"
    try:
        try:
            result = _run([uv, "pip", "install", "--quiet", "--python", sys.executable,
                           "--target", str(staging), "--only-binary", ":all:", *specs])
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DependencyError(f"could not install {', '.join(specs)}: {exc}") from exc
        if result.returncode != 0:
            lines = result.stderr.strip().splitlines()
            reason = lines[-1].strip() if lines else f"uv exited with {result.returncode}"
            raise DependencyError(f"could not install {', '.join(specs)}: {reason}")
        deactivate(plugin_id)
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def ensure(plugin_id: str, manifest: dict[str, Any]) -> None:
    """Meet a plugin's needs, or raise. System packages first: they are the
    part that can stop the installation, and it should stop before anything
    was downloaded."""
    needs = declared(manifest)
    ensure_system(needs["system"])
    if missing_python(plugin_id, needs["python"]):
        install_python(plugin_id, needs["python"])


def activate(plugin_id: str) -> None:
    """Make a plugin's packages importable. At the end of the path, see above."""
    path = str(folder(plugin_id))
    if folder(plugin_id).is_dir() and path not in sys.path:
        sys.path.append(path)
        importlib.invalidate_caches()


def deactivate(plugin_id: str) -> None:
    path = str(folder(plugin_id))
    if path in sys.path:
        sys.path.remove(path)
        importlib.invalidate_caches()


def remove(plugin_id: str) -> None:
    """Drop a plugin's packages together with the plugin."""
    deactivate(plugin_id)
    shutil.rmtree(folder(plugin_id), ignore_errors=True)
