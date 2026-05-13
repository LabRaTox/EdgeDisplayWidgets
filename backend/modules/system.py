"""System metrics: CPU%, per-core, RAM, swap, disk usage, network rates."""

from __future__ import annotations

import platform
import re
import time
from typing import Any

import psutil

from .base import Module, register_module


def _read_cpu_model() -> str | None:
    """Return a human-readable CPU name, or ``None`` if not discoverable."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    _, _, value = line.partition(":")
                    return _clean_cpu_model(value.strip()) or None
    except OSError:
        pass
    fallback = platform.processor() or platform.machine()
    return _clean_cpu_model(fallback) or None


def _clean_cpu_model(raw: str) -> str:
    s = raw.replace("(R)", "").replace("(TM)", "").replace("(r)", "").replace("(tm)", "")
    s = re.sub(r"\s+\d+-Core Processor\b", "", s)
    s = re.sub(r"\s+(CPU|Processor)\b", "", s)
    s = re.sub(r"\s*@\s*[\d.]+\s*[GM]Hz\b", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


@register_module
class SystemModule(Module):
    """Aggregate of psutil readouts.

    Network rates are computed from byte-counter deltas across polls; the
    first poll after ``setup()`` reports zero rates (no baseline yet).
    """

    name = "system"
    default_interval = 1.0

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.disk_path: str = config.get("disk_path", "/")
        self._last_net = None  # psutil._common.snetio | None
        self._last_ts: float | None = None
        self._cpu_model: str | None = None

    async def setup(self) -> None:
        # Prime psutil's CPU percent so subsequent calls return real deltas
        # instead of 0.0 on the very first poll.
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(percpu=True, interval=None)
        self._last_net = psutil.net_io_counters()
        self._last_ts = time.monotonic()
        self._cpu_model = _read_cpu_model()

    async def poll(self) -> dict[str, Any]:
        overall = float(psutil.cpu_percent(interval=None))
        per_core = [float(p) for p in psutil.cpu_percent(percpu=True, interval=None)]

        try:
            freq = psutil.cpu_freq()
            freq_mhz = float(freq.current) if freq else None
        except Exception:
            freq_mhz = None

        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()

        try:
            du = psutil.disk_usage(self.disk_path)
            disk = {
                "path": self.disk_path,
                "used": int(du.used),
                "total": int(du.total),
                "percent": float(du.percent),
            }
        except Exception:
            disk = None

        now = time.monotonic()
        counters = psutil.net_io_counters()
        rx_rate = tx_rate = 0.0
        if self._last_net is not None and self._last_ts is not None:
            dt = max(1e-6, now - self._last_ts)
            rx_rate = (counters.bytes_recv - self._last_net.bytes_recv) / dt
            tx_rate = (counters.bytes_sent - self._last_net.bytes_sent) / dt
        self._last_net = counters
        self._last_ts = now

        return {
            "cpu": {
                "percent": overall,
                "per_core": per_core,
                "count": len(per_core),
                "freq_mhz": freq_mhz,
                "model": self._cpu_model,
            },
            "ram": {
                "used": int(vm.used),
                "total": int(vm.total),
                "percent": float(vm.percent),
            },
            "swap": {
                "used": int(sm.used),
                "total": int(sm.total),
                "percent": float(sm.percent),
            },
            "disk": disk,
            "network": {
                "rx_bytes_per_s": max(0.0, rx_rate),
                "tx_bytes_per_s": max(0.0, tx_rate),
                "rx_total": int(counters.bytes_recv),
                "tx_total": int(counters.bytes_sent),
            },
        }
