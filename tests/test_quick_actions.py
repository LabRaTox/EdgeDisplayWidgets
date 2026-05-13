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
        assert set(a.keys()) == {"id", "label", "icon", "kind", "confirm"}


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
