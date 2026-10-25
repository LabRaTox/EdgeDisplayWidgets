"""Graphics cards: NVIDIA through NVML, AMD through the amdgpu driver's sysfs files.

One module for every card in the machine, whatever its maker. Each poll
answers with all of them, and the GPU tile picks the one its `card` option
names. Without a choice it shows the first dedicated card, because on a
desktop with an APU the integrated unit is rarely the one anyone watches.

A card is known by its PCI address (`0000:13:00.0`). That does not change
across reboots or driver updates, unlike the order NVML counts devices in,
and it is the same kind of id for both makers.

Nothing here needs root. NVML comes with the NVIDIA driver; for AMD the
kernel publishes everything under `/sys/class/drm/card*/device`.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import threading
from pathlib import Path
from typing import Any

from loguru import logger

from .base import Module, register_module

#: Where the kernel lists graphics devices. A class attribute on the module,
#: so tests can point it at a fake tree.
DRM = Path("/sys/class/drm")

#: The PCI id database, for a readable name of an AMD card. sysfs knows only
#: the numbers.
PCI_IDS = Path("/usr/share/hwdata/pci.ids")

AMD_VENDOR = "0x1002"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _number(path: Path) -> float | None:
    text = _read(path)
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def pci_name(vendor: str, device: str, ids: Path = PCI_IDS) -> str | None:
    """`Radeon 610M` for 1002:164e, from the PCI id database.

    The database writes the marketing name in brackets after the chip's code
    name (`Raphael [Radeon 610M]`); that is the one people know. Without
    brackets the code name is all there is.
    """
    vendor, device = vendor.lower().removeprefix("0x"), device.lower().removeprefix("0x")
    try:
        lines = ids.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    in_vendor = False
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if not line.startswith("\t"):
            in_vendor = line.lower().startswith(vendor + " ")
            continue
        if in_vendor and not line.startswith("\t\t") and line[1:5].lower() == device:
            name = line[5:].strip()
            bracket = re.search(r"\[(.+)\]", name)
            return bracket.group(1) if bracket else name
    return None


class AmdCard:
    """One amdgpu device, read from sysfs on every poll."""

    def __init__(self, device: Path) -> None:
        self.device = device
        self.id = device.resolve().name  # the PCI address
        hwmons = sorted((device / "hwmon").glob("hwmon*"))
        self.hwmon = hwmons[0] if hwmons else None
        uevent = _read(device / "uevent") or ""
        pci = re.search(r"PCI_ID=([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})", uevent)
        named = pci_name(pci.group(1), pci.group(2)) if pci else None
        self.name = f"AMD {named}" if named else "AMD GPU"
        # The driver does not say whether a device is an APU. What gives it
        # away is the cooling: a dedicated card has a fan and a power limit,
        # the graphics part of a processor has neither of its own.
        self.integrated = self.hwmon is None or not (
            (self.hwmon / "fan1_input").exists() or (self.hwmon / "power1_cap").exists()
        )

    def _hwmon(self, name: str) -> float | None:
        return _number(self.hwmon / name) if self.hwmon else None

    def _labelled(self, prefix: str, label: str) -> float | None:
        """`temp2_input` when `temp2_label` says `junction`, and so on."""
        if not self.hwmon:
            return None
        for path in sorted(self.hwmon.glob(f"{prefix}*_label")):
            if _read(path) == label:
                return _number(path.with_name(path.name.replace("_label", "_input")))
        return None

    def read(self) -> dict[str, Any]:
        used = _number(self.device / "mem_info_vram_used")
        total = _number(self.device / "mem_info_vram_total")
        temp = self._labelled("temp", "edge") or self._hwmon("temp1_input")
        power = self._hwmon("power1_average") or self._hwmon("power1_input")
        fan = None
        rpm, top = self._hwmon("fan1_input"), self._hwmon("fan1_max")
        if rpm is not None and top:
            fan = round(rpm / top * 100)
        elif self._hwmon("pwm1") is not None:
            fan = round(self._hwmon("pwm1") / 255 * 100)
        sclk = self._labelled("freq", "sclk")
        mclk = self._labelled("freq", "mclk")
        busy = _number(self.device / "gpu_busy_percent")
        return {
            "id": self.id,
            "name": self.name,
            "vendor": "amd",
            "integrated": self.integrated,
            "gpu_percent": int(busy) if busy is not None else None,
            "vram": {
                "used": int(used or 0),
                "total": int(total or 0),
                "percent": (used / total * 100.0) if used is not None and total else 0.0,
            },
            # hwmon counts in thousandths: millidegrees, microwatts, hertz.
            "temp_c": round(temp / 1000) if temp is not None else None,
            "power_w": power / 1_000_000 if power is not None else None,
            "fan_percent": fan,
            "clocks": {
                "graphics_mhz": round(sclk / 1_000_000) if sclk else None,
                "memory_mhz": round(mclk / 1_000_000) if mclk else None,
            },
        }


class NvidiaCard:
    """One device through NVML."""

    def __init__(self, nv: Any, handle: Any) -> None:
        self.nv = nv
        self.handle = handle
        name = nv.nvmlDeviceGetName(handle)
        self.name = name.decode() if isinstance(name, bytes) else str(name)
        bus = nv.nvmlDeviceGetPciInfo(handle).busId
        bus = bus.decode() if isinstance(bus, bytes) else str(bus)
        # NVML writes eight digits for the domain (`00000000:01:00.0`), the
        # kernel four. The shorter form is what sysfs and lspci show.
        domain, _, rest = bus.lower().partition(":")
        self.id = f"{domain[-4:]}:{rest}"
        self.integrated = False

    def read(self) -> dict[str, Any]:
        nv, h = self.nv, self.handle
        util = nv.nvmlDeviceGetUtilizationRates(h)
        mem = nv.nvmlDeviceGetMemoryInfo(h)
        temp = nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU)

        def optional(call):
            try:
                return call()
            except Exception:
                return None

        power = optional(lambda: nv.nvmlDeviceGetPowerUsage(h) / 1000.0)
        fan = optional(lambda: int(nv.nvmlDeviceGetFanSpeed(h)))
        gfx = optional(lambda: int(nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_GRAPHICS)))
        memclk = optional(lambda: int(nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_MEM)))
        total = int(mem.total)
        return {
            "id": self.id,
            "name": self.name,
            "vendor": "nvidia",
            "integrated": False,
            "gpu_percent": int(util.gpu),
            "vram": {
                "used": int(mem.used),
                "total": total,
                "percent": (mem.used / total * 100.0) if total else 0.0,
            },
            "temp_c": int(temp),
            "power_w": power,
            "fan_percent": fan,
            "clocks": {"graphics_mhz": gfx, "memory_mhz": memclk},
        }


#: NVML is one library per process, shared by every instance of the module.
#: A reload tears the old instance down while its last poll may still be
#: reading in a worker thread; shutting NVML down under that read crashes the
#: whole process (a segfault in nvmlDeviceGetFanSpeed). Reads and the
#: shutdown therefore take turns.
_NVML_LOCK = threading.Lock()


@register_module
class GpuModule(Module):
    """Every graphics card in the machine, NVIDIA and AMD alike.

    A maker whose driver is missing is skipped with one log line; the module
    stays useful for the other. With no card at all, each poll says so with
    `{"available": false, "reason": …}` and the tile shows the reason.
    """

    name = "gpu"
    default_interval = 1.0
    # Feeds the GPU sparkline: every poll is one sample, see system.py.
    dedupe = False

    drm: Path = DRM

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.cards: list[AmdCard | NvidiaCard] = []
        self._nv: Any = None
        self._notes: list[str] = []

    async def setup(self) -> None:
        self.cards = [*self._find_nvidia(), *self._find_amd()]
        # Dedicated cards first: without a choice, the tile shows the first.
        self.cards.sort(key=lambda card: (card.integrated, card.id))
        if self.cards:
            logger.info("gpu module: " + ", ".join(f"{c.name} ({c.id})" for c in self.cards))
        else:
            logger.warning("gpu module: no graphics card found (" + "; ".join(self._notes) + ")")

    def _find_nvidia(self) -> list[NvidiaCard]:
        try:
            import pynvml
        except ImportError as exc:
            self._notes.append(f"pynvml not installed: {exc}")
            return []
        try:
            pynvml.nvmlInit()
        except Exception as exc:
            self._notes.append(f"NVML init failed: {exc}")
            return []
        self._nv = pynvml
        found = []
        try:
            for index in range(pynvml.nvmlDeviceGetCount()):
                found.append(NvidiaCard(pynvml, pynvml.nvmlDeviceGetHandleByIndex(index)))
        except Exception as exc:
            self._notes.append(f"NVML device query failed: {exc}")
        return found

    def _find_amd(self) -> list[AmdCard]:
        found = []
        for card in sorted(self.drm.glob("card[0-9]*")):
            device = card / "device"
            # `card0-DP-1` and friends are connectors, not devices.
            if "-" in card.name or _read(device / "vendor") != AMD_VENDOR:
                continue
            if not (device / "gpu_busy_percent").exists():
                continue
            found.append(AmdCard(device))
        if not found:
            self._notes.append("no amdgpu device")
        return found

    async def teardown(self) -> None:
        await asyncio.to_thread(self._shutdown)

    def _shutdown(self) -> None:
        with _NVML_LOCK:
            # A poll that starts after this finds nothing to read.
            self.cards = []
            if self._nv is not None:
                with contextlib.suppress(Exception):
                    self._nv.nvmlShutdown()
                self._nv = None

    def _read_all(self) -> list[dict[str, Any]]:
        with _NVML_LOCK:
            return self._read_cards()

    def _read_cards(self) -> list[dict[str, Any]]:
        out = []
        for card in self.cards:
            try:
                out.append(card.read())
            except Exception as exc:
                out.append({"id": card.id, "name": card.name, "integrated": card.integrated,
                            "available": False, "reason": f"read failed: {exc}"})
        return out

    async def poll(self) -> dict[str, Any]:
        if not self.cards:
            return {"available": False, "reason": "; ".join(self._notes) or "no graphics card found"}
        # sysfs reads are quick but they are file reads; NVML calls block.
        cards = await asyncio.to_thread(self._read_all)
        if not self.cards:                     # torn down while reading
            return {"available": False, "reason": "stopped"}
        return {
            "available": True,
            "cards": cards,
            "default": self.cards[0].id,
            # "iGPU" rather than a translated word: the label goes straight
            # into the settings window, which does not translate it again.
            "choices": [{"value": c.id, "label": f"{c.name} (iGPU)" if c.integrated else c.name}
                        for c in self.cards],
        }
