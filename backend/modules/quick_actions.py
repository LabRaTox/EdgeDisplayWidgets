"""Quick Actions module: configurable touch buttons → shell or HTTP.

Security model
--------------
The frontend only ever sees an *opaque action id* per button (plus its label
and icon). When tapped, it POSTs the id back to ``/api/quick_actions/<id>/run``
and the backend looks the action up in its config and executes it.

That indirection means:
    - The list of executable commands is defined exclusively in
      ``config.yaml`` / ``config.local.yaml`` — the frontend cannot supply a
      command string.
    - Shell actions are run via ``subprocess_exec`` (argv list, no shell
      interpreter): no globbing, no variable interpolation, no pipes.
    - HTTP headers configured for an action are *not* exposed in the public
      action list (see ``QuickAction.public_view``).

Failure modes are surfaced as a structured ``{ok, error}`` result rather
than HTTP 5xx so the widget can show inline feedback per button.
"""

from __future__ import annotations

import asyncio
import shlex
from typing import Any, Literal

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import Module, register_module


class QuickAction(BaseModel):
    """One configured action.

    ``json`` in YAML maps to ``json_body`` here to avoid shadowing the
    built-in ``BaseModel.json`` method.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    label: str = ""
    icon: str = ""
    kind: Literal["shell", "http"]
    confirm: bool = False

    # shell
    command: list[str] | None = None

    # http
    url: str | None = None
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    json_body: Any = Field(default=None, alias="json")

    @model_validator(mode="after")
    def _check_kind_fields(self) -> QuickAction:
        if self.kind == "shell":
            if not self.command or not isinstance(self.command, list):
                raise ValueError(
                    f"action '{self.id}': kind=shell requires a non-empty `command` argv list"
                )
            if any(not isinstance(a, str) for a in self.command):
                raise ValueError(
                    f"action '{self.id}': every element of `command` must be a string"
                )
        elif self.kind == "http":
            if not self.url:
                raise ValueError(f"action '{self.id}': kind=http requires `url`")
        return self

    def public_view(self) -> dict[str, Any]:
        """The dict shape sent to the frontend — strictly free of secrets."""
        return {
            "id": self.id,
            "label": self.label,
            "icon": self.icon,
            "kind": self.kind,
            "confirm": self.confirm,
        }


@register_module
class QuickActionsModule(Module):
    name = "quick_actions"
    # Action list is static between hot-reloads; a long interval is fine
    # but we keep a small one so a config edit + hub-reload shows up quickly.
    default_interval = 60.0

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.timeout_seconds: float = float(config.get("timeout_seconds", 30.0))
        self.output_limit: int = int(config.get("output_limit", 2000))
        self.actions: list[QuickAction] = []
        for raw in config.get("actions", []) or []:
            try:
                self.actions.append(QuickAction.model_validate(raw))
            except Exception as exc:
                # Don't echo `exc` directly — Pydantic includes the offending
                # input_value, which would leak Authorization headers / URLs.
                action_id = raw.get("id", "<no id>") if isinstance(raw, dict) else "<not a mapping>"
                logger.warning(f"quick_actions: skipping invalid action '{action_id}': {type(exc).__name__}")
        # Reject duplicate ids — the lookup would otherwise be non-deterministic.
        seen: set[str] = set()
        dedup: list[QuickAction] = []
        for a in self.actions:
            if a.id in seen:
                logger.warning(f"quick_actions: duplicate id '{a.id}' — keeping first")
                continue
            seen.add(a.id)
            dedup.append(a)
        self.actions = dedup

    async def poll(self) -> dict[str, Any]:
        return {"actions": [a.public_view() for a in self.actions]}

    # ------------------------------------------------------- execution
    def _lookup(self, action_id: str) -> QuickAction | None:
        return next((a for a in self.actions if a.id == action_id), None)

    async def run(self, action_id: str) -> dict[str, Any]:
        action = self._lookup(action_id)
        if action is None:
            return {"ok": False, "error": f"unknown action '{action_id}'"}
        logger.info(f"quick_actions: running '{action_id}' (kind={action.kind})")
        try:
            if action.kind == "shell":
                return await self._run_shell(action)
            if action.kind == "http":
                return await self._run_http(action)
        except Exception as exc:
            logger.exception(f"quick_actions: '{action_id}' crashed: {exc}")
            return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": f"unsupported kind '{action.kind}'"}

    async def _run_shell(self, action: QuickAction) -> dict[str, Any]:
        # `command` is validated to be a non-empty list[str] above. Using
        # `create_subprocess_exec` instead of `_shell` means there's no shell
        # interpreter between us and execve — no injection possible.
        try:
            proc = await asyncio.create_subprocess_exec(
                *action.command,  # type: ignore[arg-type]
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return {"ok": False, "error": f"command not found: {exc.filename}"}
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "error": f"timeout after {self.timeout_seconds}s"}
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[: self.output_limit],
            "stderr": stderr.decode("utf-8", errors="replace")[: self.output_limit],
            "command_summary": shlex.join(action.command or []),
        }

    async def _run_http(self, action: QuickAction) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                r = await client.request(
                    action.method.upper(),
                    action.url,  # validated non-empty
                    headers=action.headers,
                    params=action.params,
                    json=action.json_body if action.json_body is not None else None,
                )
            except httpx.TimeoutException:
                return {"ok": False, "error": f"timeout after {self.timeout_seconds}s"}
            except httpx.HTTPError as exc:
                return {"ok": False, "error": f"http error: {exc}"}
        return {
            "ok": r.is_success,
            "status_code": r.status_code,
            "body": r.text[: self.output_limit],
        }
