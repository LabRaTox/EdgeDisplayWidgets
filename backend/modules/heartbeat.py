"""Heartbeat — proof-of-life producer; doubles as a kiosk connection indicator."""

from __future__ import annotations

import time
from typing import Any

from .base import Module, register_module


@register_module
class HeartbeatModule(Module):
    """Emits an incrementing sequence + uptime each tick.

    Useful in production to detect frontend-WS staleness at a glance and
    in tests to validate end-to-end message flow without depending on
    real hardware.
    """

    name = "heartbeat"
    default_interval = 1.0

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._seq = 0
        self._started: float | None = None

    async def setup(self) -> None:
        self._started = time.time()

    async def poll(self) -> dict[str, Any]:
        self._seq += 1
        started = self._started or time.time()
        return {
            "seq": self._seq,
            "uptime": time.time() - started,
            "started_at": started,
        }
