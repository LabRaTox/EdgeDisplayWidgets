"""Keeps every test away from this machine's installed widgets, store login and notes.

The plugins folder and the token file default to places under the home
directory. A test that installs or signs in would otherwise write there, and
one that lists widgets would see whatever is installed on the developer's
machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _sandbox_plugins_and_token(tmp_path_factory: pytest.TempPathFactory,
                               monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path_factory.mktemp("edge-home")
    monkeypatch.setenv("EDGE_PLUGINS_DIR", str(base / "plugins"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base / "config"))
    # The notes file lives under the data directory.
    monkeypatch.setenv("XDG_DATA_HOME", str(base / "data"))


@pytest.fixture
def plugins_dir() -> Path:
    import os

    return Path(os.environ["EDGE_PLUGINS_DIR"])
