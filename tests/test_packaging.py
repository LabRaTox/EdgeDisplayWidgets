"""The Arch package and the checkout describe the same program.

The package has its own units and launchers (packaging/), the checkout its
unit templates (systemd/). These tests keep the two together where it
matters for running, keep every version number the same, and make sure the
PKGBUILD names an Arch package for each Python dependency.
"""

from __future__ import annotations

import configparser
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKGBUILD = (ROOT / "packaging" / "aur" / "PKGBUILD").read_text(encoding="utf-8")

#: pyproject dependency -> the Arch package that provides it.
ARCH_PACKAGES = {
    "fastapi": "python-fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "python-pydantic",
    "pyyaml": "python-yaml",
    "loguru": "python-loguru",
    "psutil": "python-psutil",
    "nvidia-ml-py": "python-nvidia-ml-py",
    "dbus-next": "python-dbus-next",
    "httpx": "python-httpx",
    "pillow": "python-pillow",
}


def pkgbuild_value(name: str) -> str:
    match = re.search(rf"^{name}=(\S+)$", PKGBUILD, re.M)
    assert match, name
    return match.group(1)


def pkgbuild_array(name: str) -> list[str]:
    match = re.search(rf"^{name}=\((.*?)^\)", PKGBUILD, re.M | re.S)
    assert match, name
    body = "\n".join(line.split("#", 1)[0] for line in match.group(1).splitlines())
    return re.findall(r"'([^']+)'", body)


def unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def test_one_version_everywhere():
    version = pkgbuild_value("pkgver")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    package = json.loads((ROOT / "gui" / "package.json").read_text())["version"]
    tauri = json.loads((ROOT / "gui" / "src-tauri" / "tauri.conf.json").read_text())["version"]
    cargo = tomllib.loads((ROOT / "gui" / "src-tauri" / "Cargo.toml").read_text())["package"]["version"]
    init = re.search(r'__version__ = "([^"]+)"', (ROOT / "backend" / "__init__.py").read_text()).group(1)
    assert {pyproject, package, tauri, cargo, init} == {version}


def test_every_python_dependency_has_its_arch_package():
    depends = pkgbuild_array("depends")
    wanted = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    for requirement in wanted:
        name = re.split(r"[\[<>=!~ ]", requirement, maxsplit=1)[0].lower()
        assert name in ARCH_PACKAGES, f"no Arch package known for {name}; add it here and to the PKGBUILD"
        assert ARCH_PACKAGES[name] in depends, f"{ARCH_PACKAGES[name]} missing from depends"


def test_packaged_units_match_the_checkout():
    for name in ("edge-dashboard.service", "edge-kiosk.service"):
        packaged = unit(ROOT / "packaging" / name)
        checkout = unit(ROOT / "systemd" / name)
        for section, key in (("Unit", "After"), ("Unit", "Wants"), ("Unit", "PartOf"),
                             ("Service", "Restart"), ("Install", "WantedBy"),
                             ("Service", "MemoryHigh"), ("Service", "MemoryMax")):
            assert packaged.get(section, key, fallback=None) == checkout.get(section, key, fallback=None), (name, key)
        exec_start = packaged.get("Service", "ExecStart")
        assert exec_start.startswith("/usr/bin/") and "__" not in packaged.get("Service", "ExecStart")


def test_every_file_the_pkgbuild_installs_exists():
    for path in re.findall(r"(?:packaging|scripts)/[\w./-]+", PKGBUILD):
        assert (ROOT / path).exists(), path
    for icon in re.findall(r":([\w@]+\.png)", PKGBUILD):
        assert (ROOT / "gui" / "src-tauri" / "icons" / icon).is_file(), icon


def test_launchers_point_at_the_installed_code():
    backend = (ROOT / "packaging" / "edge-dashboard.sh").read_text()
    kiosk = (ROOT / "packaging" / "edge-kiosk.sh").read_text()
    assert "/usr/share/edge-dashboard" in backend and "backend.main" in backend
    assert "/usr/share/edge-dashboard/shell" in kiosk and "qml_kiosk.main" in kiosk
