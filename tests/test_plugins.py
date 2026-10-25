"""Widgets from the store: installing, loading, finding, removing.

An installed widget runs its module inside the backend, so the installer is
the part that has to be strict. These tests pin down that nothing is unpacked
before the checksum matched, that an archive cannot write outside its folder,
that a widget cannot replace a built-in module or reword the dashboard's
texts, and that the kiosk finds an installed view without shadowing a
built-in one.

The example widget in `examples/plugins/moon-phase` is the archive under test,
so the example stays installable.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from backend import plugin_layout, plugins, store
from backend.modules.base import get_registry, register_module, unregister_module

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "plugins" / "moon-phase"

sys.path.insert(0, str(ROOT / "shell" / "qml_kiosk"))
from views import view_path, view_version  # noqa: E402


@pytest.fixture(autouse=True)
def _forget_loaded_widgets():
    yield
    for plugin_id in list(plugins._LOADED):
        plugins.unload_module(plugin_id)


def example_zip(**changes: Any) -> bytes:
    """The example widget as the store would ship it, optionally altered."""
    manifest = json.loads((EXAMPLE / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(changes)
    data = io.BytesIO(store.pack(EXAMPLE))
    out = io.BytesIO()
    with zipfile.ZipFile(data) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            body = src.read(item)
            if item.filename.endswith("/manifest.json"):
                body = json.dumps(manifest).encode()
            dst.writestr(item, body)
    return out.getvalue()


def install(data: bytes, **kwargs: Any) -> plugin_layout.Plugin:
    kwargs.setdefault("sha256", hashlib.sha256(data).hexdigest())
    kwargs.setdefault("expected_id", "moon-phase")
    kwargs.setdefault("app_version", "1.0.0")
    return plugins.install_archive(data, **kwargs)


# ------------------------------------------------------------------ installing

def test_example_installs_and_reads_back(plugins_dir: Path):
    plugin = install(store.pack(EXAMPLE))
    assert plugin.id == "moon-phase"
    assert plugin.view_file == plugins_dir / "moon-phase" / "Widget.qml"
    assert plugin.install["sha256"] == hashlib.sha256(store.pack(EXAMPLE)).hexdigest()
    assert [p.id for p in plugin_layout.installed()] == ["moon-phase"]


def test_wrong_checksum_leaves_nothing_behind(plugins_dir: Path):
    with pytest.raises(plugins.PluginError, match="checksum"):
        install(store.pack(EXAMPLE), sha256="0" * 64)
    # Checked before anything touches the disk: not even the folder exists.
    assert not plugins_dir.exists()


@pytest.mark.parametrize("name", ["../evil.py", "/etc/evil", "a\\..\\evil"])
def test_paths_outside_the_folder_are_refused(plugins_dir: Path, name: str):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("manifest.json", (EXAMPLE / "manifest.json").read_text())
        z.writestr(name, "x")
    with pytest.raises(plugins.PluginError, match="unsafe path"):
        install(out.getvalue())
    assert not (plugins_dir.parent / "evil.py").exists()


def test_links_are_refused():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("manifest.json", (EXAMPLE / "manifest.json").read_text())
        link = zipfile.ZipInfo("Widget.qml")
        link.external_attr = (0o120777 << 16)
        z.writestr(link, "/etc/passwd")
    with pytest.raises(plugins.PluginError, match="link"):
        install(out.getvalue())


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"app": "deckswitch"}, "not an Edge Dash plugin"),
        ({"type": "action"}, "unknown type"),
        ({"id": "other-widget"}, "expected 'moon-phase'"),
        ({"min_app_version": "9.0"}, "needs Edge Dash 9.0"),
        ({"view": "Missing.qml"}, "view"),
        ({"module": "../outside.py"}, "module"),
    ],
)
def test_manifest_that_does_not_fit_is_refused(changes: dict, match: str):
    with pytest.raises(plugins.PluginError, match=match):
        install(example_zip(**changes))


def test_failed_update_keeps_the_installed_version():
    install(example_zip(version="1.0.0"))
    with pytest.raises(plugins.PluginError):
        install(example_zip(version="1.1.0", view="Missing.qml"))
    assert plugin_layout.load("moon-phase").version == "1.0.0"
    install(example_zip(version="1.1.0"))
    assert plugin_layout.load("moon-phase").version == "1.1.0"


def test_uninstall_removes_folder_and_module(plugins_dir: Path):
    plugin = install(store.pack(EXAMPLE))
    plugins.load_module(plugin)
    assert "moon-phase" in get_registry()
    plugins.uninstall("moon-phase")
    assert "moon-phase" not in get_registry()
    assert not (plugins_dir / "moon-phase").exists()
    with pytest.raises(plugins.PluginError):
        plugins.uninstall("moon-phase")


def test_versions_compare_as_numbers():
    assert plugins.newer("1.10.0", "1.9.0")
    assert not plugins.newer("1.0.0-beta", "1.0.0")
    assert plugins.newer("2", "1.9.9")


# --------------------------------------------------------------------- modules

def test_module_registers_what_it_declares():
    names = plugins.load_module(install(store.pack(EXAMPLE)))
    assert names == ["moon-phase"]
    assert get_registry()["moon-phase"].default_interval == 3600.0


def test_module_may_not_register_undeclared_names():
    plugin = install(example_zip(modules=["something-else"]))
    with pytest.raises(plugins.PluginError, match="does not declare"):
        plugins.load_module(plugin)
    assert "moon-phase" not in get_registry()


def test_module_may_not_replace_a_builtin():
    from backend.modules.base import Module

    @register_module
    class Taken(Module):
        name = "moon-phase"

        async def poll(self):
            return {}

    try:
        with pytest.raises(ValueError, match="already registered"):
            plugins.load_module(install(store.pack(EXAMPLE)))
        assert get_registry()["moon-phase"] is Taken
    finally:
        unregister_module("moon-phase")


def test_loading_twice_replaces_the_class():
    plugin = install(store.pack(EXAMPLE))
    name = plugins.load_module(plugin)[0]
    first = get_registry()[name]
    plugins.load_module(plugin)
    assert get_registry()[name] is not first


# ------------------------------------------------------------------- texts, views

def test_widget_texts_stay_in_their_own_key_space(plugins_dir: Path):
    plugin = install(store.pack(EXAMPLE))
    locale = plugin.path / "locales" / "de.json"
    data = json.loads(locale.read_text(encoding="utf-8"))
    data["nav.layout"] = "Gekapert"
    data["widget.cpu.title"] = "Auch gekapert"
    locale.write_text(json.dumps(data), encoding="utf-8")
    strings = plugin_layout.locale("de")
    assert strings["widget.moon-phase.title"] == "Mondphase"
    assert strings["settings.mod.moon-phase.southern"] == "Südhalbkugel"
    assert "nav.layout" not in strings
    assert "widget.cpu.title" not in strings


def test_kiosk_finds_installed_view_and_versions_it():
    install(store.pack(EXAMPLE))
    assert view_path("moon-phase").name == "Widget.qml"
    assert view_version("moon-phase") == plugin_layout.load("moon-phase").install["sha256"][:12]
    assert view_version("cpu") == ""


def test_builtin_view_wins_over_an_installed_folder(plugins_dir: Path):
    """A folder named like a built-in (not possible through the store, which
    reserves those names) does not replace the built-in view."""
    install(example_zip(id="disk-usage"), expected_id="disk-usage")
    assert view_path("disk-usage").parent.name == "widgets"
    assert view_path("disk_usage") == view_path("disk-usage")


def test_folder_and_manifest_must_agree(plugins_dir: Path):
    install(store.pack(EXAMPLE))
    (plugins_dir / "moon-phase").rename(plugins_dir / "renamed")
    assert plugin_layout.load("renamed") is None
    assert plugin_layout.installed() == []


# ------------------------------------------------------------------------ store

async def test_download_only_from_the_store():
    with pytest.raises(store.StoreError, match="not on the store"):
        await store.download("https://example.com/api/download/x/1.0.0")


def test_token_file_is_private():
    store.write_token("secret")
    assert store.read_token() == "secret"
    assert store.token_file().stat().st_mode & 0o777 == 0o600
    store.write_token("")
    assert not store.token_file().exists()


def test_pack_skips_caches_and_install_record(tmp_path: Path):
    folder = tmp_path / "w"
    (folder / "__pycache__").mkdir(parents=True)
    (folder / "manifest.json").write_text("{}")
    (folder / "__pycache__" / "m.cpython-313.pyc").write_bytes(b"x")
    (folder / ".install.json").write_text("{}")
    names = zipfile.ZipFile(io.BytesIO(store.pack(folder))).namelist()
    assert names == ["w/manifest.json"]


# -------------------------------------------------------------------------- API

@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("server: { host: '127.0.0.1', port: 8765 }\nmodules: {}\npages: []\n")
    from backend import main as main_mod

    monkeypatch.setattr(main_mod, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    return main_mod.create_app(cfg)


def fake_store(monkeypatch: pytest.MonkeyPatch, data: bytes, version: str = "1.0.0") -> None:
    entry = {
        "version": version,
        "sha256": hashlib.sha256(data).hexdigest(),
        "download_url": f"{store.STORE_URL}/api/download/moon-phase/{version}",
        "warnings": [{"kind": "url", "value": "https://x", "file": "module.py", "line": 1}],
        "state": "approved",
    }

    async def plugin(slug: str):
        return {"slug": slug, "author": "someone", "latest": entry, "versions": [entry]}

    async def download(url: str):
        assert url == entry["download_url"]
        return data

    monkeypatch.setattr(store, "plugin", plugin)
    monkeypatch.setattr(store, "download", download)


def test_install_endpoint_installs_loads_and_switches_on(app, tmp_path, monkeypatch):
    fake_store(monkeypatch, store.pack(EXAMPLE))
    with TestClient(app) as client:
        r = client.post("/api/store/install", json={"slug": "moon-phase"})
        assert r.status_code == 200, r.text
        assert r.json()["modules"] == ["moon-phase"]
        assert "moon-phase" in client.get("/api/settings").json()["modules"]

        local = yaml.safe_load((tmp_path / "config.local.yaml").read_text())
        assert local["modules"]["moon-phase"]["enabled"] is True

        widgets = client.get("/api/widgets").json()
        assert "moon-phase" in widgets["widgets"]
        assert widgets["installed"] == ["moon-phase"]
        assert widgets["variants"]["moon-phase"] == ["compact"]
        assert widgets["options"]["moon-phase"][0]["key"] == "show_days"

        installed = client.get("/api/plugins").json()["plugins"]
        assert installed[0]["warnings"][0]["kind"] == "url"

        assert client.delete("/api/plugins/moon-phase").status_code == 200
        assert client.get("/api/plugins").json()["plugins"] == []


def test_install_endpoint_refuses_a_bad_archive(app, monkeypatch):
    fake_store(monkeypatch, example_zip(app="deckswitch"))
    with TestClient(app) as client:
        r = client.post("/api/store/install", json={"slug": "moon-phase"})
        assert r.status_code == 422
        assert "Edge Dash" in r.json()["detail"]


def test_upload_archive_goes_to_the_store_unchanged(app, monkeypatch):
    seen = {}

    async def upload(data: bytes, filename: str):
        seen.update(data=data, filename=filename)
        return {"slug": "moon-phase", "version": "1.0.0", "status": "pending", "warnings": 0,
                "message": "ok"}

    monkeypatch.setattr(store, "upload", upload)
    archive = store.pack(EXAMPLE)
    with TestClient(app) as client:
        r = client.post("/api/store/upload-archive", content=archive,
                        headers={"X-Filename": "moon-phase.tar.gz"})
        assert r.status_code == 201, r.text
        assert seen == {"data": archive, "filename": "moon-phase.tar.gz"}
        assert client.post("/api/store/upload-archive", content=b"").status_code == 400


def test_ids_are_checked_before_reaching_the_store(app):
    with TestClient(app) as client:
        assert client.post("/api/store/install", json={"slug": "../admin"}).status_code == 422
        assert client.delete("/api/store/mine/ok-id/1.0;rm").status_code == 422


def test_locale_endpoint_merges_widget_texts(app):
    install(store.pack(EXAMPLE))
    with TestClient(app) as client:
        de = client.get("/locales/de.json").json()
        assert de["widget.moon-phase.title"] == "Mondphase"
        assert "nav.layout" not in de or de["nav.layout"] != "Gekapert"
        assert client.get("/locales/xx.json").status_code == 404
        assert client.get("/locales/..%2Fconfig.json").status_code == 404


def test_widgets_carry_card_data_for_both_kinds(app):
    install(store.pack(EXAMPLE))
    with TestClient(app) as client:
        meta = client.get("/api/widgets").json()["meta"]
    assert meta["cpu"]["builtin"] is True
    assert meta["cpu"]["name"]["de"] == "CPU"
    assert meta["cpu"]["symbol"] == "ti:cpu"
    assert meta["cpu"]["modules"] == ["system", "sensors"]
    moon = meta["moon-phase"]
    assert moon["builtin"] is False
    assert moon["version"] == "1.0.0"
    assert moon["category"] == "time"
    assert moon["icon_url"] == ""


def test_every_builtin_manifest_describes_its_card():
    for path in sorted((ROOT / "widgets").glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for key in ("name", "summary", "category", "accent", "symbol"):
            assert manifest.get(key), f"{path.name} has no {key}"
        assert set(manifest["name"]) == {"de", "en"}, path.name
        assert set(manifest["summary"]) == {"de", "en"}, path.name


def test_install_from_upload_and_folder(app):
    with TestClient(app) as client:
        r = client.post("/api/plugins/upload", content=store.pack(EXAMPLE),
                        headers={"Content-Type": "application/zip"})
        assert r.status_code == 200, r.text
        assert plugin_layout.load("moon-phase").install["source"] == "local"
        client.delete("/api/plugins/moon-phase")

        r = client.post("/api/plugins/folder", json={"path": str(EXAMPLE)})
        assert r.status_code == 200, r.text
        assert client.post("/api/plugins/folder", json={"path": "/nonexistent"}).status_code == 422
        bad = client.post("/api/plugins/upload", content=example_zip(app="deckswitch"))
        assert bad.status_code == 422


def test_rescan_picks_up_a_copied_folder(app, plugins_dir):
    with TestClient(app) as client:
        install(store.pack(EXAMPLE))
        assert "moon-phase" not in get_registry()
        assert client.post("/api/plugins/rescan").json()["new"] == ["moon-phase"]
        assert "moon-phase" in get_registry()
        assert client.post("/api/plugins/rescan").json()["new"] == []


def test_icon_only_from_inside_the_folder(app, plugins_dir):
    install(example_zip(icon="../../etc/passwd"))
    with TestClient(app) as client:
        assert client.get("/api/plugins/moon-phase/icon").status_code == 404
    (plugins_dir / "moon-phase" / "icon.png").write_bytes(b"\x89PNG")
    manifest = json.loads((plugins_dir / "moon-phase" / "manifest.json").read_text())
    manifest["icon"] = "icon.png"
    (plugins_dir / "moon-phase" / "manifest.json").write_text(json.dumps(manifest))
    with TestClient(app) as client:
        assert client.get("/api/plugins/moon-phase/icon").status_code == 200
        assert client.get("/api/widgets").json()["meta"]["moon-phase"]["icon_url"].startswith(
            "/api/plugins/moon-phase/icon")


# ------------------------------------------------------------------------ themes

def theme_zip(**changes: Any) -> bytes:
    manifest = {"app": "edgedash", "type": "theme", "id": "mint-night", "version": "1.0.0",
                "name": {"de": "Mintnacht", "en": "Mint night"}, **changes}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mint-night/manifest.json", json.dumps(manifest))
        z.writestr("mint-night/theme.css", ":root { --bg: #021a14; --accent: #3dffb0; }\n")
        z.writestr("mint-night/fonts/Mint.ttf", b"not really a font")
    return out.getvalue()


def test_theme_installs_without_view_or_module():
    plugin = install(theme_zip(), expected_id="mint-night")
    assert plugin.type == "theme"
    assert plugin.css_file.name == "theme.css"
    assert [p.name for p in plugin.font_files] == ["Mint.ttf"]
    assert plugin.view_file is None
    assert plugins.load_module(plugin) == []
    assert view_path("mint-night") is None


@pytest.mark.parametrize("changes,match", [({"css": "missing.css"}, "css"),
                                           ({"module": "m.py"}, "cannot bring a module")])
def test_theme_that_does_not_fit_is_refused(changes, match):
    with pytest.raises(plugins.PluginError, match=match):
        install(theme_zip(**changes), expected_id="mint-night")


def test_kiosk_reads_an_installed_theme():
    import theme as theme_module

    install(theme_zip(), expected_id="mint-night")
    themes_dir = ROOT / "frontend" / "css" / "themes"
    assert theme_module.load("mint-night", themes_dir)["accent"] == "#3dffb0"
    assert "mint-night" in theme_module.available(themes_dir)
    assert theme_module.theme_file("../../etc/passwd", themes_dir) is None
    assert theme_module.theme_file("toxic", themes_dir).parent == themes_dir


def test_themes_endpoint_and_css(app):
    install(theme_zip(), expected_id="mint-night")
    with TestClient(app) as client:
        body = client.get("/api/themes").json()
        assert body["themes"][-1] == "mint-night"
        assert "toxic" in body["themes"]
        assert body["meta"]["mint-night"]["builtin"] is False
        assert body["meta"]["toxic"]["builtin"] is True
        assert "mint-night" not in client.get("/api/widgets").json()["widgets"]
        css = client.get("/css/themes/mint-night.css")
        assert css.status_code == 200 and "--accent" in css.text
        assert client.get("/css/themes/toxic.css").status_code == 200
        assert client.get("/css/themes/nope.css").status_code == 404


def test_removing_the_active_theme_falls_back_to_clean(app, tmp_path):
    install(theme_zip(), expected_id="mint-night")
    with TestClient(app) as client:
        client.post("/api/settings", json={"default_theme": "mint-night"})
        r = client.delete("/api/plugins/mint-night")
        assert r.json()["theme"] == "clean"
        assert client.get("/api/settings").json()["default_theme"] == "clean"


def test_module_imports_helpers_from_its_own_folder(plugins_dir: Path):
    """A widget may split its module; helpers are found next to it and
    leave with it."""
    out = io.BytesIO()
    manifest = json.loads((EXAMPLE / "manifest.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("Widget.qml", (EXAMPLE / "Widget.qml").read_text())
        z.writestr("helpers/__init__.py", "PHASE = 0.25\n")
        z.writestr("module.py", (
            "from backend.modules.base import Module, register_module\n"
            "from .helpers import PHASE\n"
            "@register_module\n"
            "class M(Module):\n"
            "    name = 'moon-phase'\n"
            "    async def poll(self):\n"
            "        return {'fraction': PHASE}\n"
        ))
    plugin = install(out.getvalue())
    assert plugins.load_module(plugin) == ["moon-phase"]
    assert "edge_plugins.moon_phase.helpers" in sys.modules
    plugins.uninstall("moon-phase")
    assert not [k for k in sys.modules if k.startswith("edge_plugins.moon_phase")]


def test_screenshots_by_position_only(app, plugins_dir):
    install(example_zip(screenshots=["shots/a.png", "../../etc/passwd"]))
    (plugins_dir / "moon-phase" / "shots").mkdir()
    (plugins_dir / "moon-phase" / "shots" / "a.png").write_bytes(b"\x89PNG")
    with TestClient(app) as client:
        assert client.get("/api/plugins/moon-phase/screenshot/0").status_code == 200
        assert client.get("/api/plugins/moon-phase/screenshot/1").status_code == 404
        assert client.get("/api/plugins/moon-phase/screenshot/2").status_code == 404
        meta = client.get("/api/widgets").json()["meta"]["moon-phase"]
        assert meta["screenshots"] == 2
        assert meta["description"]["de"].startswith("Wie voll")


def test_store_images_go_through_the_backend(app, monkeypatch):
    shot = f"{store.STORE_URL}/api/assets/moon-phase/1.0.0/shots/a.png"

    async def plugin(slug):
        entry = {"version": "1.0.0", "icon_url": None, "screenshot_urls": [shot], "state": "approved"}
        return {"slug": slug, "latest": entry, "versions": [entry]}

    async def image(url):
        assert url == shot
        return b"\x89PNG", "image/png"

    monkeypatch.setattr(store, "plugin", plugin)
    monkeypatch.setattr(store, "image", image)
    with TestClient(app) as client:
        r = client.get("/api/store/plugins/moon-phase/1.0.0/screenshot/0")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert client.get("/api/store/plugins/moon-phase/1.0.0/screenshot/1").status_code == 404
        assert client.get("/api/store/plugins/moon-phase/1.0.0/icon").status_code == 404
        assert client.get("/api/store/plugins/moon-phase/9.9/icon").status_code == 404


async def test_store_image_only_from_the_asset_area():
    with pytest.raises(store.StoreError, match="not on the store"):
        await store.image("https://example.com/x.png")
    with pytest.raises(store.StoreError, match="not on the store"):
        await store.image(f"{store.STORE_URL}/api/download/x/1.0.0")


def test_rating_goes_through_to_the_store(app, monkeypatch):
    calls = []

    async def rating(slug):
        calls.append(("get", slug))
        return {"up": 1, "down": 0, "mine": None, "comment": None, "comments": []}

    async def rate(slug, value, comment):
        calls.append(("put", slug, value, comment))
        return {"up": 2, "down": 0, "mine": value, "comment": comment, "comments": []}

    async def unrate(slug):
        calls.append(("delete", slug))
        return {"up": 1, "down": 0, "mine": None, "comment": None, "comments": []}

    monkeypatch.setattr(store, "rating", rating)
    monkeypatch.setattr(store, "rate", rate)
    monkeypatch.setattr(store, "unrate", unrate)
    with TestClient(app) as client:
        assert client.get("/api/store/plugins/moon-phase/rating").json()["up"] == 1
        r = client.put("/api/store/plugins/moon-phase/rating", json={"value": 1, "comment": "gut"})
        assert r.json()["mine"] == 1
        assert client.delete("/api/store/plugins/moon-phase/rating").json()["mine"] is None
        assert client.get("/api/store/plugins/..%2Fx/rating").status_code in (404, 422)
    assert calls == [("get", "moon-phase"), ("put", "moon-phase", 1, "gut"), ("delete", "moon-phase")]


async def test_vote_is_one_or_minus_one():
    with pytest.raises(store.StoreError, match="1 or -1"):
        await store.rate("moon-phase", 5)


@pytest.mark.parametrize(("answer", "expected"), [
    ({"submissions": 6, "reports": 1, "url": "https://store.example/admin/queue"},
     {"submissions": 6, "reports": 1, "url": "https://store.example/admin/queue"}),
    (store.StoreError("no right", status=403), None),     # signed in, but no reviewer
    (store.StoreError("gone", status=401), None),
])
def test_pending_review_counts(monkeypatch: pytest.MonkeyPatch, answer, expected):
    async def fake_request(method, path, auth=False, **_):
        assert (method, path, auth) == ("GET", "/api/review/pending", True)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(store, "_request", fake_request)
    store.write_token("secret")
    try:
        assert asyncio.run(store.pending()) == expected
    finally:
        store.write_token("")


def test_pending_route_survives_an_unreachable_store(app, monkeypatch: pytest.MonkeyPatch):
    async def down():
        raise store.StoreError("unreachable")

    monkeypatch.setattr(store, "pending", down)
    with TestClient(app) as client:
        r = client.get("/api/store/pending")
        assert r.status_code == 200 and r.json() == {"pending": None}
