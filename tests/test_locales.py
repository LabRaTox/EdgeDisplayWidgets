"""Tests for the display's translation files.

`frontend/locales/<code>.json` is read by the kiosk and, through
`loadDashboardStrings`, by the settings window. A missing key is not an error
anywhere: `Bridge.tr` returns the key itself, so the display shows
`widget.sensors.title` instead of a word. These tests make that visible here
rather than on the panel.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "frontend" / "locales"
QML = ROOT / "shell" / "qml_kiosk" / "qml"

#: `bridge.tr("literal")`. Keys built at runtime end at a dot and are checked
#: separately, since the parser cannot know what is appended.
TR_CALL = re.compile(r'bridge\.tr\(\s*"([^"]+)"')


def strings(code: str) -> dict[str, str]:
    return json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def qml_keys() -> set[str]:
    keys: set[str] = set()
    for path in QML.rglob("*.qml"):
        keys |= set(TR_CALL.findall(path.read_text(encoding="utf-8")))
    return keys


def test_both_languages_have_the_same_keys():
    de, en = set(strings("de")), set(strings("en"))
    assert de == en, f"only in de: {sorted(de - en)}, only in en: {sorted(en - de)}"


@pytest.mark.parametrize("code", ["de", "en"])
def test_no_string_is_empty(code: str):
    empty = [k for k, v in strings(code).items() if not v.strip()]
    assert not empty, f"{code}: empty strings for {empty}"


def test_every_literal_key_exists():
    known = set(strings("de"))
    missing = sorted(k for k in qml_keys() if not k.endswith(".") and k not in known)
    assert not missing, f"used in QML but not translated: {missing}"


def test_every_runtime_prefix_has_entries():
    """A key built at runtime, such as `widget.weather.code.` plus a number.
    The prefix itself is never a key, but something has to start with it."""
    known = set(strings("de"))
    prefixes = sorted(k for k in qml_keys() if k.endswith("."))
    assert prefixes, "no runtime-built keys found; the parser may have gone stale"
    for prefix in prefixes:
        assert any(k.startswith(prefix) for k in known), f"nothing starts with {prefix}"
