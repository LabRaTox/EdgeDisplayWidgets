"""Tests that the documentation still describes what the code does.

The prose goes stale silently: nothing breaks when a table lists a widget's
modules wrongly, or names a file that was renamed. These check the parts that
can be checked mechanically, so a rename shows up here instead of misleading
the next reader.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "widgets"
READMES = [ROOT / "README.md", ROOT / "README.de.md"]
DOCS = READMES + sorted((ROOT / "docs").glob("*.md"))

sys.path.insert(0, str(ROOT / "shell" / "qml_kiosk"))
from views import SHARED, view_path  # noqa: E402

#: `| `widget` | `module`, `module` | what it shows |`
ROW = re.compile(r"^\| `([a-z_]+)` \| ([^|]+) \|", re.M)

#: A path into the repository, in backticks.
PATH = re.compile(r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_./-]+)`")

#: Paths that are external, or relative to somewhere other than the root.
PATH_SKIP = ("http", "~/", "/usr", "/etc", "/api", "/ws", "/vendor/", "org.",
             "127.0",
             # Relative to `cd gui`, which the surrounding block establishes.
             "src-tauri/")
#: These two describe what was removed; naming deleted files is their job.
HISTORY = {"decisions.md", "entscheidungen.md"}


def table_rows(text: str) -> dict[str, set[str]]:
    """Widget rows of a documentation table, mapped to the modules they name."""
    return {
        widget: set(re.findall(r"`([a-z_]+)`", modules))
        for widget, modules in ROW.findall(text)
        if (MANIFESTS / f"{widget}.json").is_file()
    }


@pytest.mark.parametrize("readme", READMES, ids=lambda p: p.name)
def test_widget_table_matches_the_manifests(readme: Path):
    rows = table_rows(readme.read_text(encoding="utf-8"))
    assert rows, f"{readme.name}: no widget table found"
    for path in sorted(MANIFESTS.glob("*.json")):
        declared = set(json.loads(path.read_text(encoding="utf-8")).get("modules") or [])
        assert path.stem in rows, f"{readme.name}: {path.stem} is missing from the table"
        assert rows[path.stem] == declared, (
            f"{readme.name}: {path.stem} lists {sorted(rows[path.stem])}, "
            f"manifest says {sorted(declared)}"
        )


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_path_named_in_the_docs_exists(doc: Path):
    if doc.name in HISTORY:
        pytest.skip("describes what was removed, on purpose")
    missing = [
        m for m in PATH.findall(doc.read_text(encoding="utf-8"))
        if not m.startswith(PATH_SKIP) and "<" not in m
        and not (ROOT / m.rstrip("/")).exists()
    ]
    assert not missing, f"{doc.name}: no such path: {missing}"


def test_every_widget_in_a_manifest_can_be_drawn():
    """A widget the editor offers has to have a view, or its tile stays empty."""
    missing = [p.stem for p in sorted(MANIFESTS.glob("*.json")) if view_path(p.stem) is None]
    assert not missing, f"no QML view for: {missing}"


#: `readonly property var moduleNames: ["a", "b"]`
MODULE_NAMES = re.compile(r"readonly\s+property\s+var\s+moduleNames\s*:\s*\[([^\]]*)\]")


def test_manifest_modules_match_the_view():
    """`modules` in the manifest and `moduleNames` in the QML say the same
    thing in two places. The manifest is what the docs are checked against,
    the QML is what actually decides which frames a widget receives, so they
    have to agree or one of them is a lie."""
    for path in sorted(MANIFESTS.glob("*.json")):
        declared = set(json.loads(path.read_text(encoding="utf-8")).get("modules") or [])
        view = view_path(path.stem)
        assert view is not None, f"{path.stem} has no view"
        found = MODULE_NAMES.search(view.read_text(encoding="utf-8"))
        used = set(re.findall(r"""['"]([^'"]+)['"]""", found.group(1))) if found else set()
        assert declared == used, (
            f"{path.stem}: manifest says {sorted(declared)}, "
            f"{view.name} says {sorted(used)}"
        )


#: `| `--accent` | what it colours |`, several per cell in places.
THEME_VAR = re.compile(r"`--([a-z0-9-]+)`")


@pytest.mark.parametrize("doc", [ROOT / "docs/themes.md", ROOT / "docs/themes.de.md"],
                         ids=lambda p: p.name)
def test_documented_theme_variables_have_an_effect(doc: Path):
    """A variable in the table has to be one the kiosk reads or a theme sets.
    Documenting one that nothing looks at sends a theme author chasing an
    effect that cannot happen."""
    from theme import BASE

    themes = ROOT / "frontend" / "css" / "themes"
    defined = set()
    for css in themes.glob("*.css"):
        defined |= set(re.findall(r"--([a-z0-9-]+)\s*:", css.read_text(encoding="utf-8")))

    documented = set(THEME_VAR.findall(doc.read_text(encoding="utf-8")))
    inert = sorted(v for v in documented if v not in BASE and v not in defined)
    assert not inert, f"{doc.name}: nothing reads or sets: {inert}"


def test_one_character_stands_for_a_missing_value():
    """Widgets show a dash where they have no value yet. One character for it,
    not two that look almost alike: an en dash next to an em dash in the same
    row is the kind of thing nobody spots and nobody can unsee."""
    views = ROOT / "shell" / "qml_kiosk" / "qml"
    wrong = [
        f"{path.relative_to(ROOT)}:{n}"
        for path in sorted(views.rglob("*.qml"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if '"\u2014"' in line or "u2013" in line or "u2014" in line
    ]
    assert not wrong, f"use \u2013 for a missing value: {wrong}"


def test_shared_building_blocks_are_not_widgets():
    """`SHARED` names the QML files that are not widgets. If one of them ever
    gains a manifest, the list is wrong rather than the file."""
    for stem in SHARED:
        assert not (MANIFESTS / f"{stem.lower()}.json").is_file(), (
            f"{stem} is listed as a shared block but has a manifest"
        )
