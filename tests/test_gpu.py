"""Tests for the GpuModule: NVIDIA through NVML, AMD through amdgpu's sysfs.

AMD cards are built as a fake sysfs tree, laid out like the real one under
`/sys/class/drm` (measured on a Radeon 610M, with the files a dedicated card
adds). NVML is replaced by a small stand-in, so nothing here needs a GPU.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from backend.config import AppConfig
from backend.modules import gpu
from backend.modules.gpu import GpuModule, pci_name

PCI_IDS = """\
# comment
1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t164e  Raphael [Radeon 610M]
\t73bf  Navi 21 [Radeon RX 6800/6800 XT / 6900 XT]
\t\t1002 0e3a  Radeon RX 6900 XT
10de  NVIDIA Corporation
\t164e  Not an AMD card
"""


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{value}\n")


def amd_card(drm: Path, card: str, slot: str, device_id: str, *, dedicated: bool) -> None:
    """One amdgpu device the way sysfs shows it, with a connector next to it."""
    device = drm / "devices" / slot
    write(device / "vendor", "0x1002")
    write(device / "uevent", f"DRIVER=amdgpu\nPCI_ID=1002:{device_id.upper()}\nPCI_SLOT_NAME={slot}")
    write(device / "gpu_busy_percent", 37 if dedicated else 4)
    write(device / "mem_info_vram_used", 4 * 1024**3 if dedicated else 52326400)
    write(device / "mem_info_vram_total", 16 * 1024**3 if dedicated else 536870912)
    hwmon = device / "hwmon" / "hwmon3"
    write(hwmon / "name", "amdgpu")
    write(hwmon / "temp1_label", "edge")
    write(hwmon / "temp1_input", 61000 if dedicated else 40000)
    write(hwmon / "freq1_label", "sclk")
    write(hwmon / "freq1_input", 2400000000 if dedicated else 600000000)
    if dedicated:
        write(hwmon / "temp2_label", "junction")
        write(hwmon / "temp2_input", 75000)
        write(hwmon / "freq2_label", "mclk")
        write(hwmon / "freq2_input", 1000000000)
        write(hwmon / "power1_average", 180000000)
        write(hwmon / "power1_cap", 255000000)
        write(hwmon / "fan1_input", 1500)
        write(hwmon / "fan1_max", 3000)
    else:
        write(hwmon / "power1_input", 28351000)
    (drm / card).mkdir(parents=True)
    (drm / card / "device").symlink_to(device)
    (drm / f"{card}-DP-1").mkdir()


@pytest.fixture
def drm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "drm"
    ids = tmp_path / "pci.ids"
    ids.write_text(PCI_IDS)
    monkeypatch.setattr(gpu, "PCI_IDS", ids)
    monkeypatch.setattr(GpuModule, "drm", root)
    # No NVIDIA by default; a test that wants one installs the stand-in.
    monkeypatch.setitem(sys.modules, "pynvml", None)
    return root


def fake_nvml(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> None:
    def init():
        if fail:
            raise RuntimeError("simulated NVML init failure")

    nv = types.SimpleNamespace(
        NVML_TEMPERATURE_GPU=0, NVML_CLOCK_GRAPHICS=0, NVML_CLOCK_MEM=1,
        nvmlInit=init,
        nvmlShutdown=lambda: None,
        nvmlDeviceGetCount=lambda: 1,
        nvmlDeviceGetHandleByIndex=lambda i: "h0",
        nvmlDeviceGetName=lambda h: b"NVIDIA GeForce RTX 4070 Ti SUPER",
        nvmlDeviceGetPciInfo=lambda h: types.SimpleNamespace(busId=b"00000000:01:00.0"),
        nvmlDeviceGetUtilizationRates=lambda h: types.SimpleNamespace(gpu=12),
        nvmlDeviceGetMemoryInfo=lambda h: types.SimpleNamespace(used=2 * 1024**3, total=16 * 1024**3),
        nvmlDeviceGetTemperature=lambda h, kind: 55,
        nvmlDeviceGetPowerUsage=lambda h: 12317,
        nvmlDeviceGetFanSpeed=lambda h: 30,
        nvmlDeviceGetClockInfo=lambda h, kind: 2100 if kind == 0 else 10500,
    )
    monkeypatch.setitem(sys.modules, "pynvml", nv)


async def poll(config: dict | None = None) -> dict:
    module = GpuModule(config or {})
    await module.setup()
    return await module.poll()


def test_pci_name_prefers_the_marketing_name(tmp_path):
    ids = tmp_path / "pci.ids"
    ids.write_text(PCI_IDS)
    assert pci_name("1002", "164E", ids) == "Radeon 610M"
    assert pci_name("0x1002", "0x73bf", ids) == "Radeon RX 6800/6800 XT / 6900 XT"
    assert pci_name("1002", "ffff", ids) is None
    assert pci_name("1002", "164e", tmp_path / "missing") is None


async def test_amd_dedicated_card_and_apu(drm):
    amd_card(drm, "card0", "0000:13:00.0", "164e", dedicated=False)
    amd_card(drm, "card1", "0000:03:00.0", "73bf", dedicated=True)
    out = await poll()

    assert out["available"] is True
    # Dedicated first: that is the one a tile without a choice shows.
    assert [c["id"] for c in out["cards"]] == ["0000:03:00.0", "0000:13:00.0"]
    assert out["default"] == "0000:03:00.0"
    assert [c["label"] for c in out["choices"]] == [
        "AMD Radeon RX 6800/6800 XT / 6900 XT", "AMD Radeon 610M (iGPU)"]

    rx, apu = out["cards"]
    assert rx["integrated"] is False and apu["integrated"] is True
    assert rx["gpu_percent"] == 37
    assert rx["vram"]["percent"] == pytest.approx(25.0)
    assert rx["temp_c"] == 61          # edge, as NVIDIA reports its core
    assert rx["power_w"] == pytest.approx(180.0)
    assert rx["fan_percent"] == 50
    assert rx["clocks"] == {"graphics_mhz": 2400, "memory_mhz": 1000}
    assert apu["power_w"] == pytest.approx(28.351)
    assert apu["fan_percent"] is None
    assert apu["clocks"]["memory_mhz"] is None


async def test_nvidia_and_amd_together(drm, monkeypatch):
    amd_card(drm, "card0", "0000:13:00.0", "164e", dedicated=False)
    fake_nvml(monkeypatch)
    out = await poll()
    nvidia = out["cards"][0]
    assert out["default"] == "0000:01:00.0"   # NVML's long domain, shortened
    assert nvidia["vendor"] == "nvidia"
    assert nvidia["name"] == "NVIDIA GeForce RTX 4070 Ti SUPER"
    assert nvidia["power_w"] == pytest.approx(12.317)
    assert nvidia["clocks"] == {"graphics_mhz": 2100, "memory_mhz": 10500}
    assert out["cards"][1]["vendor"] == "amd"


async def test_broken_nvml_leaves_amd_working(drm, monkeypatch):
    amd_card(drm, "card0", "0000:03:00.0", "73bf", dedicated=True)
    fake_nvml(monkeypatch, fail=True)
    out = await poll()
    assert [c["vendor"] for c in out["cards"]] == ["amd"]


async def test_no_card_at_all(drm):
    out = await poll()
    assert out["available"] is False
    assert "pynvml" in out["reason"] and "amdgpu" in out["reason"]


async def test_a_card_that_fails_to_read_is_reported_not_raised(drm, monkeypatch):
    fake_nvml(monkeypatch)
    module = GpuModule({})
    await module.setup()
    monkeypatch.setattr(module.cards[0], "read", lambda: (_ for _ in ()).throw(RuntimeError("gone")))
    out = await module.poll()
    assert out["cards"][0]["available"] is False
    assert "gone" in out["cards"][0]["reason"]


def test_old_nvidia_block_becomes_gpu():
    cfg = AppConfig.model_validate({"modules": {"nvidia": {"enabled": False, "interval": 2.0,
                                                          "device_index": 1}}})
    assert "nvidia" not in cfg.modules
    assert cfg.modules["gpu"].enabled is False
    assert cfg.modules["gpu"].interval == 2.0
    assert "device_index" not in cfg.modules["gpu"].model_dump()

    both = AppConfig.model_validate({"modules": {"nvidia": {"enabled": True},
                                                 "gpu": {"enabled": False}}})
    assert both.modules["gpu"].enabled is False
    assert "nvidia" not in both.modules
