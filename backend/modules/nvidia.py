"""NVIDIA GPU metrics via NVML. Disables itself gracefully when no GPU is found."""

from __future__ import annotations

from typing import Any

from loguru import logger

from .base import Module, register_module


@register_module
class NvidiaModule(Module):
    """Reports GPU%, VRAM, temperature, power, fan, and clocks for one device.

    If pynvml init fails (no GPU, no driver, container without /dev/nvidia*),
    the module logs once at setup and returns an ``{"available": false}``
    payload from each subsequent poll. The Hub keeps polling so the frontend
    sees the disabled state, but no NVML calls are made.
    """

    name = "nvidia"
    default_interval = 1.0

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.device_index: int = int(config.get("device_index", 0))
        self._available = False
        self._handle = None
        self._unavailable_reason: str | None = None
        self._device_name: str = ""
        self._pynvml: Any = None

    async def setup(self) -> None:
        try:
            import pynvml
        except ImportError as exc:
            self._unavailable_reason = f"pynvml not installed: {exc}"
            logger.warning(f"nvidia module disabled: {self._unavailable_reason}")
            return
        try:
            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(self.device_index)
            name = pynvml.nvmlDeviceGetName(self._handle)
            self._device_name = name.decode() if isinstance(name, bytes) else str(name)
            self._pynvml = pynvml
            self._available = True
            logger.info(
                f"nvidia module active: device {self.device_index} ({self._device_name})"
            )
        except Exception as exc:
            self._unavailable_reason = f"NVML init failed: {exc}"
            logger.warning(f"nvidia module disabled: {self._unavailable_reason}")

    async def teardown(self) -> None:
        if self._available and self._pynvml is not None:
            try:
                self._pynvml.nvmlShutdown()
            except Exception:
                pass

    async def poll(self) -> dict[str, Any]:
        if not self._available:
            return {
                "available": False,
                "reason": self._unavailable_reason or "unknown",
            }

        nv = self._pynvml
        h = self._handle
        try:
            util = nv.nvmlDeviceGetUtilizationRates(h)
            mem = nv.nvmlDeviceGetMemoryInfo(h)
            temp = nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU)
        except Exception as exc:
            return {"available": False, "reason": f"NVML read failed: {exc}"}

        try:
            power_w = nv.nvmlDeviceGetPowerUsage(h) / 1000.0
        except Exception:
            power_w = None

        try:
            fan_percent: int | None = int(nv.nvmlDeviceGetFanSpeed(h))
        except Exception:
            fan_percent = None

        try:
            gfx_mhz: int | None = int(nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_GRAPHICS))
            mem_mhz: int | None = int(nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_MEM))
        except Exception:
            gfx_mhz = mem_mhz = None

        total = int(mem.total)
        return {
            "available": True,
            "name": self._device_name,
            "gpu_percent": int(util.gpu),
            "vram": {
                "used": int(mem.used),
                "total": total,
                "percent": (mem.used / total * 100.0) if total else 0.0,
            },
            "temp_c": int(temp),
            "power_w": power_w,
            "fan_percent": fan_percent,
            "clocks": {"graphics_mhz": gfx_mhz, "memory_mhz": mem_mhz},
        }
