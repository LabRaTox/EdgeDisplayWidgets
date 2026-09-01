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

Deck features
-------------
Actions form a *tree*: a ``kind="folder"`` tile carries nested ``tiles`` that
the widget opens as a sub-deck. Each action may also declare a ``status``
probe (shell/http) the module polls so the tile can show live on/off state.
Probe config (like commands/URLs/headers) is never exposed — only the derived
``state`` reaches the frontend.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shlex
import time
from collections.abc import Iterator
from typing import Any, ClassVar, Literal

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .base import Module, SettingField, register_module

# `color` / `text_color` are handed to the display and painted as given, so
# restrict them to plain hex: a value that is not a colour would otherwise
# reach a colour property, and the kiosk checks again for the same reason.
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class StatusProbe(BaseModel):
    """How to determine an action's live on/off state.

    The probe output is matched against ``match`` (a regex) when given —
    ``on`` if it matches, else ``off``. Without ``match`` the state is derived
    from success (shell exit 0 / HTTP 2xx). Probe errors yield ``unknown``.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    kind: Literal["shell", "http"]
    command: list[str] | None = None
    url: str | None = None
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    match: str | None = None

    @model_validator(mode="after")
    def _check(self) -> StatusProbe:
        if self.kind == "shell" and not self.command:
            raise ValueError("status probe kind=shell requires `command`")
        if self.kind == "http" and not self.url:
            raise ValueError("status probe kind=http requires `url`")
        if self.match is not None:
            try:
                re.compile(self.match)
            except re.error as exc:
                raise ValueError(f"status probe `match` is not a valid regex: {exc}")
        return self


class QuickAction(BaseModel):
    """One configured tile — an action, or a folder of nested tiles.

    ``json`` in YAML maps to ``json_body`` here to avoid shadowing the
    built-in ``BaseModel.json`` method.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    label: str = ""
    icon: str = ""
    kind: Literal["shell", "http", "folder"]
    confirm: bool = False

    # --- tile appearance + placement (Stream-Deck-style deck) ---
    # Background + foreground colours (hex, optional → theme defaults), the tile
    # span in grid cells (1..4), and an optional fixed position on the deck:
    # `page` + (`x`, `y`) cell coordinates. When x/y are None the widget
    # auto-flows the tile into the next free cell.
    color: str | None = None
    text_color: str | None = None
    w: int = Field(default=1, ge=1, le=4)
    h: int = Field(default=1, ge=1, le=4)
    page: int = Field(default=0, ge=0, le=64)
    x: int | None = Field(default=None, ge=0, le=16)
    y: int | None = Field(default=None, ge=0, le=64)

    # folder-only: where the auto-generated "back" tile sits within this
    # folder's sub-deck (reserved on every page so it's always reachable).
    back_x: int = Field(default=0, ge=0, le=16)
    back_y: int = Field(default=0, ge=0, le=16)

    # --- live status probe (optional) ---
    status: StatusProbe | None = None

    @field_validator("color", "text_color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not _HEX_COLOR.match(v):
            raise ValueError("colour must be a hex value like #rgb or #rrggbb")
        return v

    # shell
    command: list[str] | None = None
    # Fire-and-forget: launch in a new session and return immediately instead
    # of waiting for exit (e.g. starting a GUI program).
    detach: bool = False

    # http
    url: str | None = None
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    json_body: Any = Field(default=None, alias="json")

    # folder
    tiles: list[QuickAction] = Field(default_factory=list)

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
        elif self.kind == "folder":
            if self.command or self.url:
                raise ValueError(
                    f"action '{self.id}': kind=folder must not set `command`/`url`"
                )
        if self.tiles and self.kind != "folder":
            raise ValueError(f"action '{self.id}': only folders may contain `tiles`")
        return self

    def public_view(self) -> dict[str, Any]:
        """The dict shape sent to the frontend — strictly free of secrets.

        Recursive for folders. ``state`` is a placeholder the module overwrites
        with the freshly polled value; the probe config itself never leaves the
        backend.
        """
        view: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "icon": self.icon,
            "kind": self.kind,
            "confirm": self.confirm,
            "color": self.color,
            "text_color": self.text_color,
            "w": self.w,
            "h": self.h,
            "page": self.page,
            "x": self.x,
            "y": self.y,
        }
        if self.status is not None:
            view["has_status"] = True
            view["state"] = "unknown"
        if self.kind == "folder":
            view["tiles"] = [t.public_view() for t in self.tiles]
            view["back_x"] = self.back_x
            view["back_y"] = self.back_y
        return view


def _walk(actions: list[QuickAction]) -> Iterator[QuickAction]:
    """Depth-first iterator over an action tree (folders + their tiles)."""
    for a in actions:
        yield a
        if a.kind == "folder":
            yield from _walk(a.tiles)


@register_module
class QuickActionsModule(Module):
    name = "quick_actions"
    # Action list is static between hot-reloads; a long interval is fine
    # but we keep a small one so a config edit + hub-reload shows up quickly.
    # Lower the configured interval to make live-status tiles more responsive.
    default_interval = 60.0
    # Shortest gap between two signal-driven probe passes, in seconds.
    MIN_REPROBE_GAP = 2.0
    # The tile grid itself (`columns`/`rows`) and individual tiles are edited in
    # the widget's own edit mode; only the global timeouts are surfaced here.
    settings_schema: ClassVar[list[SettingField]] = [
        SettingField(
            key="timeout_seconds",
            type="float",
            label_key="settings.mod.quick_actions.timeout_seconds",
            default=30.0,
            min=1,
            step=1,
        ),
        SettingField(
            key="status_timeout_seconds",
            type="float",
            label_key="settings.mod.quick_actions.status_timeout_seconds",
            default=8.0,
            min=1,
            step=1,
        ),
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.timeout_seconds: float = float(config.get("timeout_seconds", 30.0))
        self.status_timeout: float = float(config.get("status_timeout_seconds", 8.0))
        self.output_limit: int = int(config.get("output_limit", 2000))
        # Fixed deck grid: the widget places tiles on a `columns`×`rows` page
        # and paginates the overflow. Shared by every folder level.
        self.columns: int = min(max(int(config.get("columns", 4)), 1), 8)
        self.rows: int = min(max(int(config.get("rows", 3)), 1), 8)
        self.actions: list[QuickAction] = []
        for raw in config.get("actions", []) or []:
            try:
                self.actions.append(QuickAction.model_validate(raw))
            except Exception as exc:
                # Don't echo `exc` directly — Pydantic includes the offending
                # input_value, which would leak Authorization headers / URLs.
                action_id = raw.get("id", "<no id>") if isinstance(raw, dict) else "<not a mapping>"
                logger.warning(f"quick_actions: skipping invalid action '{action_id}': {type(exc).__name__}")
        # Prune duplicate ids across the whole tree (folders included) — the
        # run-by-id lookup would otherwise be non-deterministic. First wins.
        seen: set[str] = set()

        def prune(items: list[QuickAction]) -> list[QuickAction]:
            kept: list[QuickAction] = []
            for a in items:
                if a.id in seen:
                    logger.warning(f"quick_actions: duplicate id '{a.id}' — keeping first")
                    continue
                seen.add(a.id)
                if a.kind == "folder":
                    a.tiles = prune(a.tiles)
                kept.append(a)
            return kept

        self.actions = prune(self.actions)
        self._index: dict[str, QuickAction] = {a.id: a for a in _walk(self.actions)}
        self._buses: list[Any] = []
        self._reprobe_task: asyncio.Task[None] | None = None
        self._last_reprobe: float = 0.0

    # --------------------------------------------------------- live status
    async def setup(self) -> None:
        """Listen for systemd job completions so tiles stop lagging a minute behind.

        The deck's status probes are generic shell/HTTP calls, and running them
        on a clock is why a tile can show a stale state for up to a full
        interval. systemd announces every finished start/stop/restart as a
        ``JobRemoved`` signal on the Manager interface — one subscription per
        bus covers *every* unit, so we don't have to guess which probe watches
        which unit. A signal just means "something changed, look again".

        Entirely optional: without D-Bus, without systemd, or without the
        permission to subscribe, the poll interval carries on as before.
        """
        if not any(a.status is not None for a in _walk(self.actions)):
            return  # no live-status tiles — nothing to watch for
        try:
            from dbus_next.aio import MessageBus
            from dbus_next.constants import BusType
        except ImportError as exc:
            logger.debug(f"quick_actions: no live status ({exc})")
            return

        for bus_type in (BusType.SESSION, BusType.SYSTEM):
            try:
                bus = await MessageBus(bus_type=bus_type).connect()
                intr = await bus.introspect(
                    "org.freedesktop.systemd1", "/org/freedesktop/systemd1"
                )
                obj = bus.get_proxy_object(
                    "org.freedesktop.systemd1", "/org/freedesktop/systemd1", intr
                )
                manager = obj.get_interface("org.freedesktop.systemd1.Manager")
                # Without Subscribe() systemd only emits job signals to clients
                # that asked for them.
                await manager.call_subscribe()
                manager.on_job_removed(self._on_job_removed)
                self._buses.append(bus)
                logger.debug(f"quick_actions: watching {bus_type.name.lower()} bus for unit changes")
            except Exception as exc:
                logger.debug(
                    f"quick_actions: {bus_type.name.lower()} bus unavailable "
                    f"({type(exc).__name__}: {exc})"
                )

    def _on_job_removed(self, _job_id: int, _job_path: str, _unit: str, _result: str) -> None:
        self._schedule_reprobe()

    def _schedule_reprobe(self) -> None:
        """Re-run the probes once, shortly. Bursts collapse into one pass."""
        if self._reprobe_task is not None and not self._reprobe_task.done():
            return
        self._reprobe_task = asyncio.create_task(self._reprobe_soon())

    async def _reprobe_soon(self) -> None:
        try:
            # Let the burst finish (a restart is a stop job plus a start job),
            # then keep a floor between passes: probes spawn subprocesses, and
            # a busy machine can fire job signals continuously.
            await asyncio.sleep(0.4)
            wait = self.MIN_REPROBE_GAP - (time.monotonic() - self._last_reprobe)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_reprobe = time.monotonic()
            await self.emit(await self.poll())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug(f"quick_actions: re-probe failed: {type(exc).__name__}: {exc}")

    async def teardown(self) -> None:
        if self._reprobe_task is not None:
            self._reprobe_task.cancel()
            self._reprobe_task = None
        for bus in self._buses:
            with contextlib.suppress(Exception):
                bus.disconnect()
        self._buses.clear()

    async def poll(self) -> dict[str, Any]:
        states = await self._probe_all()
        views = [a.public_view() for a in self.actions]
        if states:
            self._apply_states(views, states)
        return {"actions": views, "columns": self.columns, "rows": self.rows}

    def _apply_states(self, views: list[dict[str, Any]], states: dict[str, str]) -> None:
        for v in views:
            if v["id"] in states:
                v["state"] = states[v["id"]]
            if v.get("kind") == "folder":
                self._apply_states(v.get("tiles", []), states)

    # ------------------------------------------------------- status probes
    async def _probe_all(self) -> dict[str, str]:
        probed = [a for a in _walk(self.actions) if a.status is not None]
        if not probed:
            return {}
        sem = asyncio.Semaphore(8)

        async def one(action: QuickAction) -> tuple[str, str]:
            async with sem:
                return action.id, await self._probe(action.status)  # type: ignore[arg-type]

        results = await asyncio.gather(*(one(a) for a in probed), return_exceptions=True)
        states: dict[str, str] = {}
        for r in results:
            if isinstance(r, tuple):
                states[r[0]] = r[1]
        return states

    async def _probe(self, probe: StatusProbe) -> str:
        try:
            if probe.kind == "shell":
                return await self._probe_shell(probe)
            return await self._probe_http(probe)
        except Exception as exc:  # never let a probe crash the poll
            logger.debug(f"quick_actions: status probe failed: {type(exc).__name__}: {exc}")
            return "unknown"

    @staticmethod
    def _derive_state(probe: StatusProbe, text: str, ok_default: bool) -> str:
        if probe.match:
            try:
                return "on" if re.search(probe.match, text) else "off"
            except re.error:
                return "unknown"
        return "on" if ok_default else "off"

    async def _probe_shell(self, probe: StatusProbe) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *(probe.command or []),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return "unknown"
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.status_timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return "unknown"
        return self._derive_state(probe, stdout.decode("utf-8", errors="replace"), proc.returncode == 0)

    async def _probe_http(self, probe: StatusProbe) -> str:
        async with httpx.AsyncClient(timeout=self.status_timeout) as client:
            r = await client.request(
                probe.method.upper(), probe.url, headers=probe.headers, params=probe.params,
            )
        return self._derive_state(probe, r.text, r.is_success)

    # ------------------------------------------------------- execution
    def _lookup(self, action_id: str) -> QuickAction | None:
        return self._index.get(action_id)

    async def run(self, action_id: str) -> dict[str, Any]:
        action = self._lookup(action_id)
        if action is None:
            return {"ok": False, "error": f"unknown action '{action_id}'"}
        if action.kind == "folder":
            return {"ok": False, "error": f"'{action_id}' is a folder, not an action"}
        logger.info(f"quick_actions: running '{action_id}' (kind={action.kind})")
        try:
            if action.kind == "shell":
                result = await self._run_shell(action)
            elif action.kind == "http":
                result = await self._run_http(action)
            else:
                return {"ok": False, "error": f"unsupported kind '{action.kind}'"}
        except Exception as exc:
            logger.exception(f"quick_actions: '{action_id}' crashed: {exc}")
            return {"ok": False, "error": str(exc)}
        # Re-probe so the tile reflects the new state immediately, without
        # waiting for the next poll cycle.
        if action.status is not None:
            result["state"] = await self._probe(action.status)
            # The caller sees the new state in this response; every other
            # client (the kiosk, a second window) only learns about it if we
            # broadcast it.
            self._schedule_reprobe()
        return result

    async def _run_shell(self, action: QuickAction) -> dict[str, Any]:
        # `command` is validated to be a non-empty list[str] above. Using
        # `create_subprocess_exec`/Popen (argv list) instead of a shell means
        # there's no shell interpreter between us and execve — no injection.
        if action.detach:
            # Launch detached (new session) and return at once — the process
            # outlives this request; we don't capture output or wait.
            import subprocess

            try:
                subprocess.Popen(
                    action.command,  # type: ignore[arg-type]
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError as exc:
                return {"ok": False, "error": f"command not found: {exc.filename}"}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "detached": True, "command_summary": shlex.join(action.command or [])}
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
        except TimeoutError:
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
