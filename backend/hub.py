"""Module hub: discovery, polling, WebSocket broadcast, last-value cache."""

from __future__ import annotations

import asyncio
import importlib
import json
import pkgutil
import time
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from . import modules as modules_pkg
from .modules.base import Module, get_registry

if TYPE_CHECKING:
    from .config import AppConfig


class WSLike(Protocol):
    """Minimal interface the Hub needs from a WebSocket-shaped object.

    Decoupled from FastAPI so unit tests can pass plain stubs.
    """

    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


class Hub:
    """Central coordinator for module polling and WS broadcast."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.modules: dict[str, Module] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._last: dict[str, dict[str, Any]] = {}
        self._clients: set[WSLike] = set()
        self._lock = asyncio.Lock()
        self._running = False

    # ----------------------------------------------------------------- discovery
    @staticmethod
    def discover() -> None:
        """Import every backend.modules.<x> so @register_module decorators run."""
        for info in pkgutil.iter_modules(modules_pkg.__path__):
            if info.name.startswith("_") or info.name == "base":
                continue
            full = f"{modules_pkg.__name__}.{info.name}"
            try:
                importlib.import_module(full)
            except Exception as exc:
                logger.exception(f"failed to import module '{full}': {exc}")

    def _instantiate(self) -> None:
        registry = get_registry()
        cfg_modules = self.config.modules

        for name, mod_cfg in cfg_modules.items():
            if not mod_cfg.enabled:
                logger.info(f"module '{name}' disabled in config")
                continue
            cls = registry.get(name)
            if cls is None:
                logger.warning(f"module '{name}' enabled in config but no producer found")
                continue
            try:
                self.modules[name] = cls(mod_cfg.model_dump())
            except Exception as exc:
                logger.exception(f"failed to instantiate module '{name}': {exc}")

        for name in registry:
            if name not in cfg_modules:
                logger.debug(f"module '{name}' available but not in config (skipped)")

    # ----------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self._running:
            return
        self.discover()
        self._instantiate()
        for module in self.modules.values():
            try:
                await module.setup()
            except Exception as exc:
                logger.exception(f"setup failed for '{module.name}': {exc}")
                continue
            self._tasks.append(
                asyncio.create_task(self._run(module), name=f"poll:{module.name}")
            )
        self._running = True
        logger.info(
            f"hub started with {len(self.modules)} module(s): {sorted(self.modules.keys())}"
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for module in self.modules.values():
            try:
                await module.teardown()
            except Exception as exc:
                logger.exception(f"teardown failed for '{module.name}': {exc}")
        async with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for ws in clients:
            try:
                await ws.close()
            except Exception:
                pass
        logger.info("hub stopped")

    # ----------------------------------------------------------------- polling
    async def _run(self, module: Module) -> None:
        """Poll one module on its interval and broadcast each result."""
        interval = max(0.05, module.interval)  # safety floor
        while True:
            started = time.monotonic()
            try:
                data = await module.poll()
                payload: dict[str, Any] = {
                    "module": module.name,
                    "data": data,
                    "ts": time.time(),
                }
                self._last[module.name] = payload
                await self._broadcast(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(f"poll failed for '{module.name}': {exc}")
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0.0, interval - elapsed))

    # ----------------------------------------------------------------- websocket
    async def connect(self, ws: WSLike) -> None:
        """Register a new client and replay last-known values per module."""
        async with self._lock:
            self._clients.add(ws)
        snapshot = list(self._last.values())
        for payload in snapshot:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception as exc:
                logger.warning(f"failed to replay snapshot to new client: {exc}")
                async with self._lock:
                    self._clients.discard(ws)
                return

    async def disconnect(self, ws: WSLike) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            if not self._clients:
                return
            clients = list(self._clients)
        message = json.dumps(payload)
        dead: list[WSLike] = []
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    # ------------------------------------------------------------------ reload
    async def reload(self, new_config: AppConfig) -> None:
        """Replace the running module set according to ``new_config``.

        Polling tasks are cancelled and modules torn down, then re-instantiated
        from the registry with the new config. WebSocket clients stay connected;
        they just don't receive frames during the transition. The cached
        last-values are cleared so a stale snapshot doesn't get replayed.
        """
        if not self._running:
            self.config = new_config
            return

        # Cancel polling tasks
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # Teardown old modules
        for module in list(self.modules.values()):
            try:
                await module.teardown()
            except Exception as exc:
                logger.exception(f"teardown failed for '{module.name}': {exc}")
        self.modules.clear()
        self._last.clear()

        # Apply new config + re-instantiate from registry (no re-discovery — the
        # module classes are already imported and live in `_REGISTRY`).
        self.config = new_config
        self._instantiate()

        for module in self.modules.values():
            try:
                await module.setup()
            except Exception as exc:
                logger.exception(f"setup failed for '{module.name}': {exc}")
                continue
            self._tasks.append(
                asyncio.create_task(self._run(module), name=f"poll:{module.name}")
            )
        logger.info(
            f"hub reloaded with {len(self.modules)} module(s): "
            f"{sorted(self.modules.keys())}"
        )

    # ----------------------------------------------------------------- introspection
    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Last-known payload for every module (for REST debugging / new clients)."""
        return dict(self._last)

    @property
    def client_count(self) -> int:
        return len(self._clients)
