"""Tests for the NvidiaModule.

Always-runnable: a monkeypatched no-GPU path verifies the disabled state.
The available-GPU shape test self-skips when no NVIDIA card is present.
"""

from __future__ import annotations

import pytest

from backend.modules.base import clear_registry, register_module
from backend.modules.nvidia import NvidiaModule


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    register_module(NvidiaModule)
    yield
    clear_registry()


@pytest.mark.asyncio
async def test_nvidia_disabled_when_init_fails(monkeypatch):
    import pynvml

    def _boom():
        raise RuntimeError("simulated NVML init failure")

    monkeypatch.setattr(pynvml, "nvmlInit", _boom)

    mod = NvidiaModule({})
    await mod.setup()
    assert mod._available is False

    data = await mod.poll()
    assert data["available"] is False
    assert "reason" in data
    assert "simulated" in data["reason"]


@pytest.mark.asyncio
async def test_nvidia_disabled_when_pynvml_missing(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "pynvml", None)
    # Setting to None makes `import pynvml` raise ImportError.

    mod = NvidiaModule({})
    await mod.setup()
    data = await mod.poll()
    assert data["available"] is False
    assert "pynvml" in data["reason"]


@pytest.mark.asyncio
async def test_nvidia_poll_shape_when_available():
    """Self-skips when no GPU is present; otherwise asserts the payload shape."""
    mod = NvidiaModule({})
    await mod.setup()
    if not mod._available:
        pytest.skip(f"no NVIDIA GPU available: {mod._unavailable_reason}")

    try:
        data = await mod.poll()
        assert data["available"] is True
        assert isinstance(data["gpu_percent"], int)
        assert 0 <= data["gpu_percent"] <= 100
        assert data["vram"]["total"] > 0
        assert data["vram"]["used"] >= 0
        assert data["temp_c"] >= 0
        assert "clocks" in data
    finally:
        await mod.teardown()
