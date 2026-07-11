"""Tests for the .desktop application scanner used by /api/apps."""

from __future__ import annotations

from backend.main import _parse_desktop, scan_desktop_apps


def test_parse_desktop_basic(tmp_path):
    f = tmp_path / "firefox.desktop"
    f.write_text(
        "[Desktop Entry]\nType=Application\nName=Firefox\n"
        "Exec=firefox %u\nIcon=firefox\n",
        encoding="utf-8",
    )
    entry = _parse_desktop(f)
    assert entry == {"name": "Firefox", "exec": ["firefox"], "icon": "firefox"}


def test_parse_desktop_skips_nodisplay_and_terminal(tmp_path):
    nod = tmp_path / "hidden.desktop"
    nod.write_text("[Desktop Entry]\nType=Application\nName=H\nExec=h\nNoDisplay=true\n", encoding="utf-8")
    term = tmp_path / "term.desktop"
    term.write_text("[Desktop Entry]\nType=Application\nName=T\nExec=t\nTerminal=true\n", encoding="utf-8")
    link = tmp_path / "link.desktop"
    link.write_text("[Desktop Entry]\nType=Link\nName=L\nURL=http://x\n", encoding="utf-8")
    assert _parse_desktop(nod) is None
    assert _parse_desktop(term) is None
    assert _parse_desktop(link) is None


def test_parse_desktop_strips_field_codes(tmp_path):
    f = tmp_path / "x.desktop"
    f.write_text('[Desktop Entry]\nType=Application\nName=X\nExec=env FOO=1 myapp --flag %F %i\n', encoding="utf-8")
    entry = _parse_desktop(f)
    assert entry["exec"] == ["env", "FOO=1", "myapp", "--flag"]


def test_scan_returns_list():
    # Smoke test against the real system dirs — must not raise, returns a list.
    apps = scan_desktop_apps()
    assert isinstance(apps, list)
    assert all("name" in a and "exec" in a for a in apps)


def test_icon_index_and_resolve(tmp_path, monkeypatch):
    # A fake icon theme + pixmaps; ensure the index finds them and resolve
    # maps a name (and absolute path) correctly.
    icons = tmp_path / "icons" / "hicolor" / "64x64" / "apps"
    icons.mkdir(parents=True)
    (icons / "myapp.png").write_bytes(b"x")
    pix = tmp_path / "pixmaps"
    pix.mkdir()
    abs_icon = pix / "other.png"
    abs_icon.write_bytes(b"y")

    import backend.main as m
    monkeypatch.setattr(m, "_icon_index_cache", None)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Point the system root globs at our temp tree by faking the dirs:
    orig_build = m.build_icon_index
    idx = orig_build()
    assert idx.get("myapp", "").endswith("hicolor/64x64/apps/myapp.png")

    assert m._resolve_icon_name("myapp", idx) == "myapp"
    assert m._resolve_icon_name("does-not-exist", idx) == ""
    # absolute path registers under its stem
    assert m._resolve_icon_name(str(abs_icon), idx) == "other"
    assert idx["other"] == str(abs_icon)
