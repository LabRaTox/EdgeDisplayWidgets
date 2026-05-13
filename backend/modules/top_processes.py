"""Top N processes by CPU% (psutil-backed).

`Process.cpu_percent(interval=None)` reports usage since the previous call
for that Process instance — the first call always returns 0. We prime every
existing process on setup and re-prime newcomers each poll, so the widget
shows realistic numbers from the first frame onwards.

Per-process percentages are reported as a fraction of the *whole system*
(0–100 across all cores), matching the system CPU widget. A single
core-saturating process therefore reads as `100 / cpu_count`%.
"""

from __future__ import annotations

import asyncio
from typing import Any

import psutil

from .base import Module, register_module


@register_module
class TopProcessesModule(Module):
    name = "top_processes"
    default_interval = 3.0

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.limit: int = int(config.get("limit", 5))
        # Cache to keep per-process CPU% deltas accurate across polls.
        self._known_pids: set[int] = set()
        self._cpu_count: int = psutil.cpu_count(logical=True) or 1

    async def setup(self) -> None:
        await asyncio.to_thread(self._prime)

    def _prime(self) -> None:
        for proc in psutil.process_iter(["pid"]):
            try:
                proc.cpu_percent(interval=None)
                self._known_pids.add(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    async def poll(self) -> dict[str, Any]:
        rows = await asyncio.to_thread(self._collect)
        return {"processes": rows, "cpu_count": self._cpu_count}

    def _collect(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        live_pids: set[int] = set()
        for proc in psutil.process_iter(["pid", "name", "username"]):
            pid = proc.info["pid"]
            live_pids.add(pid)
            try:
                raw_cpu = proc.cpu_percent(interval=None)
                if pid not in self._known_pids:
                    # Newcomer: first read is always 0, so skip it this round.
                    self._known_pids.add(pid)
                    continue
                mem = proc.memory_info()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            rows.append({
                "pid": pid,
                "name": proc.info["name"] or "?",
                "user": proc.info["username"] or "",
                "cpu_percent": raw_cpu / self._cpu_count,
                "rss": int(mem.rss),
            })

        # Drop pids that have exited so the prime-cache doesn't grow forever.
        self._known_pids &= live_pids

        rows.sort(key=lambda r: r["cpu_percent"], reverse=True)
        return rows[: self.limit]
