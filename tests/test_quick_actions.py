"""Tests for the QuickActionsModule: parsing, execution, public view."""

from __future__ import annotations

import asyncio
import sys

import httpx
import pytest

from backend.modules.base import clear_registry, register_module
from backend.modules.quick_actions import QuickAction, QuickActionsModule


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    register_module(QuickActionsModule)
    yield
    clear_registry()


# ----------------------------------------------------- validation


def test_shell_action_requires_command():
    with pytest.raises(Exception):
        QuickAction.model_validate({"id": "x", "kind": "shell"})


def test_shell_command_must_be_list_of_strings():
    with pytest.raises(Exception):
        QuickAction.model_validate({"id": "x", "kind": "shell", "command": "echo hi"})
    with pytest.raises(Exception):
        QuickAction.model_validate({"id": "x", "kind": "shell", "command": ["echo", 1]})


def test_http_action_requires_url():
    with pytest.raises(Exception):
        QuickAction.model_validate({"id": "x", "kind": "http"})


def test_public_view_strips_secrets():
    a = QuickAction.model_validate({
        "id": "lights",
        "label": "Lights",
        "icon": "💡",
        "kind": "http",
        "url": "http://ha.local/api/services/light/turn_off",
        "headers": {"Authorization": "Bearer secret-token"},
        "json": {"entity_id": "all"},
    })
    view = a.public_view()
    assert "url" not in view
    assert "headers" not in view
    assert "json" not in view
    assert "json_body" not in view
    assert view == {
        "id": "lights",
        "label": "Lights",
        "icon": "💡",
        "kind": "http",
        "confirm": False,
        "color": None,
        "text_color": None,
        "w": 1,
        "h": 1,
        "page": 0,
        "x": None,
        "y": None,
    }


# ----------------------------------------------------- module behaviour


@pytest.mark.asyncio
async def test_poll_returns_only_public_fields():
    mod = QuickActionsModule({
        "actions": [
            {"id": "a", "kind": "shell", "command": ["true"], "label": "A"},
            {
                "id": "b", "kind": "http", "url": "http://example",
                "headers": {"Authorization": "secret"}, "label": "B",
            },
        ],
    })
    data = await mod.poll()
    assert {a["id"] for a in data["actions"]} == {"a", "b"}
    for a in data["actions"]:
        assert set(a.keys()) == {
            "id", "label", "icon", "kind", "confirm",
            "color", "text_color", "w", "h", "page", "x", "y",
        }


@pytest.mark.asyncio
async def test_invalid_actions_are_skipped_not_raised():
    mod = QuickActionsModule({
        "actions": [
            {"id": "ok", "kind": "shell", "command": ["true"]},
            {"id": "bad", "kind": "shell"},  # missing command
        ],
    })
    data = await mod.poll()
    assert [a["id"] for a in data["actions"]] == ["ok"]


@pytest.mark.asyncio
async def test_duplicate_ids_keep_first():
    mod = QuickActionsModule({
        "actions": [
            {"id": "dup", "kind": "shell", "command": ["true"], "label": "first"},
            {"id": "dup", "kind": "shell", "command": ["false"], "label": "second"},
        ],
    })
    assert len(mod.actions) == 1
    assert mod.actions[0].label == "first"


@pytest.mark.asyncio
async def test_run_unknown_id():
    mod = QuickActionsModule({"actions": []})
    result = await mod.run("ghost")
    assert result["ok"] is False
    assert "unknown" in result["error"].lower()


# ----------------------------------------------------- shell execution


@pytest.mark.asyncio
async def test_run_shell_success():
    mod = QuickActionsModule({
        "actions": [{"id": "hello", "kind": "shell",
                     "command": [sys.executable, "-c", "print('hi')"]}],
    })
    result = await mod.run("hello")
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "hi" in result["stdout"]


@pytest.mark.asyncio
async def test_run_shell_nonzero_exit():
    mod = QuickActionsModule({
        "actions": [{"id": "fail", "kind": "shell",
                     "command": [sys.executable, "-c", "import sys; sys.exit(3)"]}],
    })
    result = await mod.run("fail")
    assert result["ok"] is False
    assert result["exit_code"] == 3


@pytest.mark.asyncio
async def test_run_shell_command_not_found():
    mod = QuickActionsModule({
        "actions": [{"id": "ghost", "kind": "shell",
                     "command": ["/nonexistent/binary-xyz-12345"]}],
    })
    result = await mod.run("ghost")
    assert result["ok"] is False
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_run_shell_timeout():
    mod = QuickActionsModule({
        "timeout_seconds": 0.2,
        "actions": [{"id": "slow", "kind": "shell",
                     "command": [sys.executable, "-c",
                                 "import time; time.sleep(5)"]}],
    })
    result = await mod.run("slow")
    assert result["ok"] is False
    assert "timeout" in result["error"]


@pytest.mark.asyncio
async def test_shell_uses_argv_no_shell_interpretation():
    """A literal `$HOME` argument must reach the program unchanged — proving
    we're not piping through a shell."""
    mod = QuickActionsModule({
        "actions": [{"id": "echo", "kind": "shell",
                     "command": [sys.executable, "-c",
                                 "import sys; print(sys.argv[1])", "$HOME"]}],
    })
    result = await mod.run("echo")
    assert result["ok"] is True
    assert result["stdout"].strip() == "$HOME"


# ----------------------------------------------------- http execution


@pytest.mark.asyncio
async def test_run_http_success(monkeypatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"result": "ok"})

    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(
        "backend.modules.quick_actions.httpx.AsyncClient", patched_client,
    )

    mod = QuickActionsModule({
        "actions": [{
            "id": "ha",
            "kind": "http",
            "url": "http://example/api/svc",
            "method": "POST",
            "headers": {"Authorization": "Bearer xyz"},
            "json": {"entity_id": "all"},
        }],
    })
    result = await mod.run("ha")
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert seen["method"] == "POST"
    assert seen["auth"] == "Bearer xyz"


@pytest.mark.asyncio
async def test_run_http_failure_status(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(
        "backend.modules.quick_actions.httpx.AsyncClient", patched_client,
    )

    mod = QuickActionsModule({
        "actions": [{"id": "h", "kind": "http", "url": "http://example"}],
    })
    result = await mod.run("h")
    assert result["ok"] is False
    assert result["status_code"] == 500


# ----------------------------------------------------- folders (deck nesting)


def test_folder_recursive_public_view():
    a = QuickAction.model_validate({
        "id": "root", "kind": "folder", "label": "Root",
        "tiles": [
            {"id": "child", "kind": "shell", "command": ["true"], "label": "C"},
        ],
    })
    view = a.public_view()
    assert view["kind"] == "folder"
    assert [t["id"] for t in view["tiles"]] == ["child"]
    # The nested tile is itself a full public view, free of secrets.
    assert view["tiles"][0]["label"] == "C"
    assert "command" not in view["tiles"][0]


def test_folder_rejects_command():
    with pytest.raises(Exception):
        QuickAction.model_validate({"id": "f", "kind": "folder", "command": ["x"]})


def test_tiles_only_on_folders():
    with pytest.raises(Exception):
        QuickAction.model_validate({
            "id": "s", "kind": "shell", "command": ["true"],
            "tiles": [{"id": "n", "kind": "shell", "command": ["true"]}],
        })


@pytest.mark.asyncio
async def test_run_folder_is_rejected():
    mod = QuickActionsModule({
        "actions": [{"id": "grp", "kind": "folder", "tiles": [
            {"id": "leaf", "kind": "shell", "command": ["true"]},
        ]}],
    })
    # Nested leaves are runnable via the tree-wide index.
    assert (await mod.run("leaf"))["ok"] is True
    result = await mod.run("grp")
    assert result["ok"] is False
    assert "folder" in result["error"]


@pytest.mark.asyncio
async def test_duplicate_ids_pruned_across_tree():
    mod = QuickActionsModule({
        "actions": [
            {"id": "x", "kind": "shell", "command": ["true"]},
            {"id": "f", "kind": "folder", "tiles": [
                {"id": "x", "kind": "shell", "command": ["false"]},  # dup → pruned
                {"id": "y", "kind": "shell", "command": ["true"]},
            ]},
        ],
    })
    assert set(mod._index) == {"x", "f", "y"}
    assert [t.id for t in mod.actions[1].tiles] == ["y"]


# ----------------------------------------------------- live status probes


@pytest.mark.asyncio
async def test_status_shell_exit_code():
    mod = QuickActionsModule({
        "actions": [
            {"id": "on", "kind": "shell", "command": ["true"],
             "status": {"kind": "shell", "command": ["true"]}},
            {"id": "off", "kind": "shell", "command": ["true"],
             "status": {"kind": "shell", "command": ["false"]}},
        ],
    })
    data = await mod.poll()
    states = {a["id"]: a.get("state") for a in data["actions"]}
    assert states == {"on": "on", "off": "off"}
    # Probe config is never exposed; only has_status + state.
    for a in data["actions"]:
        assert a["has_status"] is True
        assert "command" not in a


@pytest.mark.asyncio
async def test_status_shell_match_regex():
    mod = QuickActionsModule({
        "actions": [{
            "id": "p", "kind": "shell", "command": ["true"],
            "status": {"kind": "shell", "command": ["sh", "-c", "echo READY"], "match": "READY"},
        }],
    })
    data = await mod.poll()
    assert data["actions"][0]["state"] == "on"


@pytest.mark.asyncio
async def test_run_reprobes_status():
    mod = QuickActionsModule({
        "actions": [{
            "id": "p", "kind": "shell", "command": ["true"],
            "status": {"kind": "shell", "command": ["true"]},
        }],
    })
    result = await mod.run("p")
    assert result["ok"] is True
    assert result["state"] == "on"


def test_invalid_status_regex_rejected():
    with pytest.raises(Exception):
        QuickAction.model_validate({
            "id": "p", "kind": "shell", "command": ["true"],
            "status": {"kind": "shell", "command": ["true"], "match": "("},
        })


# ----------------------------------------------------- detached launch


@pytest.mark.asyncio
async def test_detach_returns_immediately():
    # `sleep 5` would block for 5s if awaited; detached, run() returns at once.
    mod = QuickActionsModule({
        "timeout_seconds": 30,
        "actions": [{"id": "app", "kind": "shell", "command": ["sleep", "5"], "detach": True}],
    })
    result = await asyncio.wait_for(mod.run("app"), timeout=2.0)
    assert result["ok"] is True
    assert result["detached"] is True
