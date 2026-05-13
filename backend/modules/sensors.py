"""Hardware sensors via /sys/class/hwmon (Linux).

Auto-discovers all hwmon chips at setup, then on every poll reads only the
already-known temp inputs (no re-globbing). The discovery filter keeps
labelled inputs from chips we recognise as 'interesting' and drops
chips that are already covered by other modules (NVIDIA via nvml).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from loguru import logger

from .base import Module, register_module

# Chips we never want — already covered by a dedicated module or known noise.
SKIP_CHIPS = {"nvidia", "amdgpu_top"}

# Prefix match: any chip starting with one of these is dropped entirely.
# Network-card temp sensors are rarely relevant on a kiosk dashboard.
SKIP_CHIP_PREFIXES = ("r8169", "mt7921", "iwlwifi")

# When a chip name matches this list, we keep it even if its temp inputs are
# unlabelled. Most discrete-temp chips fall into this set.
KNOWN_INTERESTING = {
    "coretemp",        # Intel CPU package
    "k10temp",         # AMD CPU
    "zenpower",        # AMD Ryzen Tdie/Tctl via zenpower kernel module
    "amdgpu",          # AMD GPU (until we add a real GPU module for it)
    "nvme",            # NVMe drives
    "acpitz",          # ACPI thermal zones
    "asus",            # ASUS WMI/EC sensors
    "asus-nb-wmi",
    "asusec",
    "spd5118",         # RAM DIMM temperature sensors (DDR5)
    "corsairpsu",      # Corsair PSU
}

# Labels that are good headline pickers within a chip.
PRIMARY_LABELS = {
    "package id 0",
    "tctl",
    "tdie",
    "cpu",
    "composite",       # NVMe overall
    "edge",            # AMDGPU
    "junction",
}

# Pretty display names for the "chip" column. Matched case-insensitively,
# falling back to the raw chip name when nothing matches.
CHIP_DISPLAY: dict[str, str] = {
    "k10temp": "CPU",
    "coretemp": "CPU",
    "zenpower": "CPU",
    "amdgpu": "GPU",
    "nvme": "NVMe",
    "spd5118": "RAM",
    "corsairpsu": "PSU",
    "acpitz": "Mainboard",
    "asus": "Mainboard",
    "asus-nb-wmi": "Mainboard",
    "asusec": "Mainboard",
}

# Pretty display names for individual temp inputs. Matched case-insensitively
# against the raw hwmon label.
LABEL_DISPLAY: dict[str, str] = {
    "tctl": "Package",
    "tdie": "Package",
    "tccd1": "CCD 1",
    "tccd2": "CCD 2",
    "tccd3": "CCD 3",
    "tccd4": "CCD 4",
    "package id 0": "Package",
    "cpu": "Package",
    "edge": "Edge",
    "junction": "Junction",
    "vrm temp": "VRM",
    "case temp": "Gehäuse",
}


def _pretty_chip(chip: str) -> str:
    low = chip.lower()
    if low in CHIP_DISPLAY:
        return CHIP_DISPLAY[low]
    for prefix, pretty in CHIP_DISPLAY.items():
        if low.startswith(prefix):
            return pretty
    return chip


def _pretty_label(label: str) -> str:
    return LABEL_DISPLAY.get(label.lower(), label)


# NVMe block-device model strings are typically vendor part numbers
# ("CT2000P5PSSD8") rather than something a human would recognise. Decode
# the common ones into "brand series capacity". Falls back to the raw
# string if no pattern matches.
_CRUCIAL_RE = re.compile(r"^CT(\d+)([A-Z]+\d+)(P)?SSD\d+$")
_CORSAIR_RE = re.compile(r"^Force\s+(MP\d+)$", re.IGNORECASE)
_SAMSUNG_RE = re.compile(
    r"^Samsung\s+SSD\s+(\d+)\s*(PRO|EVO|QVO)?\s*(\d+\s*[GT]B)?$",
    re.IGNORECASE,
)


def _format_capacity_gb(gb: int) -> str:
    if gb >= 1000 and gb % 1000 == 0:
        return f"{gb // 1000}TB"
    return f"{gb}GB"


def _prettify_nvme_model(model: str) -> str:
    m = model.strip()
    if not m:
        return m

    if (match := _CRUCIAL_RE.match(m)):
        size = _format_capacity_gb(int(match.group(1)))
        series = match.group(2)
        plus = " Plus" if match.group(3) else ""
        return f"Crucial {series}{plus} {size}"

    if (match := _CORSAIR_RE.match(m)):
        return f"Corsair {match.group(1).upper()}"

    if (match := _SAMSUNG_RE.match(m)):
        gen, variant, size = match.group(1), match.group(2), match.group(3)
        parts = [f"Samsung {gen}"]
        if variant:
            parts[0] += f" {variant.title()}"
        if size:
            parts.append(size.upper().replace(" ", ""))
        return " ".join(parts)

    return m


class _Reading:
    __slots__ = (
        "chip", "label", "path", "primary", "id",
        "display_chip", "display_label",
    )

    def __init__(
        self,
        chip: str,
        label: str,
        path: Path,
        primary: bool,
        ident: str,
        display_chip: str,
        display_label: str,
    ) -> None:
        self.chip = chip
        self.label = label
        self.path = path
        self.primary = primary
        self.id = ident
        self.display_chip = display_chip
        self.display_label = display_label


@register_module
class SensorsModule(Module):
    name = "sensors"
    default_interval = 2.0

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.hwmon_root = Path(config.get("hwmon_root", "/sys/class/hwmon"))
        self.include_unknown = bool(config.get("include_unknown_chips", False))
        self._readings: list[_Reading] = []
        self._available = False
        self._unavailable_reason: str | None = None

    async def setup(self) -> None:
        try:
            self._readings = await asyncio.to_thread(self._discover)
        except Exception as exc:
            self._unavailable_reason = f"discovery failed: {exc}"
            logger.warning(f"sensors disabled: {self._unavailable_reason}")
            return
        if not self._readings:
            self._unavailable_reason = "no usable hwmon temperature inputs found"
            logger.warning(f"sensors disabled: {self._unavailable_reason}")
            return
        self._available = True
        logger.info(
            f"sensors module active with {len(self._readings)} input(s) across "
            f"{len({r.chip for r in self._readings})} chip(s)"
        )

    def _discover(self) -> list[_Reading]:
        results: list[_Reading] = []
        if not self.hwmon_root.is_dir():
            return results

        # Counter for chips that need positional disambiguation (e.g. multiple
        # unlabelled RAM DIMM sensors with chip name `spd5118`).
        chip_counter: dict[str, int] = {}

        for entry in sorted(self.hwmon_root.iterdir()):
            try:
                name_path = entry / "name"
                if not name_path.is_file():
                    continue
                chip_name = name_path.read_text().strip()
                low = chip_name.lower()
                if not chip_name or low in SKIP_CHIPS:
                    continue
                if any(low.startswith(p) for p in SKIP_CHIP_PREFIXES):
                    continue
                interesting = (
                    chip_name in KNOWN_INTERESTING
                    or any(chip_name.startswith(prefix) for prefix in KNOWN_INTERESTING)
                    or self.include_unknown
                )

                # Per-chip instance index, used by spd5118 to label DIMMs.
                chip_counter[low] = chip_counter.get(low, 0) + 1
                instance_idx = chip_counter[low]

                # NVMe drives expose multiple temp inputs ("Composite",
                # "Sensor 1", "Sensor 2", …). Composite alone is useful;
                # disambiguate identical chip names across drives via the
                # block-device model string from /sys.
                nvme_model: str | None = None
                if low == "nvme":
                    model_path = entry / "device" / "model"
                    if model_path.is_file():
                        try:
                            raw_model = model_path.read_text().strip()
                            nvme_model = _prettify_nvme_model(raw_model) if raw_model else None
                        except OSError:
                            nvme_model = None

                for temp_input in sorted(entry.glob("temp*_input")):
                    idx = temp_input.stem.removeprefix("temp").removesuffix("_input")
                    label_path = entry / f"temp{idx}_label"
                    label = (
                        label_path.read_text().strip()
                        if label_path.is_file()
                        else ""
                    )
                    # NVMe: keep only the overall "Composite" reading.
                    if low == "nvme" and label.lower() != "composite":
                        continue
                    if not interesting and not label:
                        continue
                    if not label:
                        label = f"temp{idx}"

                    # Mark as primary if the label is a known headline reading
                    # OR if the chip publishes only one (unlabelled) temperature.
                    chip_temp_inputs = list(entry.glob("temp*_input"))
                    is_only_temp = len(chip_temp_inputs) == 1
                    primary = label.lower() in PRIMARY_LABELS or (
                        is_only_temp and chip_name in ("k10temp", "zenpower")
                    )

                    # Hwmon slot in the id keeps it globally unique when the
                    # same chip name appears on multiple devices (e.g. three
                    # NVMe drives all reporting as `nvme:1`).
                    ident = f"{entry.name}/{chip_name}:{idx}"

                    display_chip = _pretty_chip(chip_name)
                    if low == "spd5118":
                        display_label = f"DIMM {instance_idx}"
                    elif low == "nvme":
                        display_label = nvme_model or f"NVMe {instance_idx}"
                    else:
                        display_label = _pretty_label(label)

                    results.append(_Reading(
                        chip_name, label, temp_input, primary, ident,
                        display_chip, display_label,
                    ))
            except Exception as exc:
                logger.warning(f"sensors: failed to enumerate {entry}: {exc}")

        # Sort: primary first, then by display-chip+display-label so visually
        # related rows (all NVMe, all CPU, …) stay grouped in the widget.
        results.sort(key=lambda r: (
            not r.primary, r.display_chip.lower(), r.display_label.lower(),
        ))
        return results

    async def poll(self) -> dict[str, Any]:
        if not self._available:
            return {"available": False, "reason": self._unavailable_reason or "unknown"}

        readings: list[dict[str, Any]] = []
        for r in self._readings:
            try:
                raw = await asyncio.to_thread(r.path.read_text)
                # hwmon temperatures are millidegrees Celsius
                temp_c = int(raw.strip()) / 1000.0
            except Exception:
                continue
            readings.append({
                "id": r.id,
                "chip": r.chip,
                "label": r.label,
                "display_chip": r.display_chip,
                "display_label": r.display_label,
                "temp_c": round(temp_c, 1),
                "primary": r.primary,
            })

        return {"available": True, "readings": readings}
