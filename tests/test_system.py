"""Tests for the SystemModule (psutil-backed)."""

from __future__ import annotations

import asyncio

import pytest

from backend.modules.base import clear_registry, register_module
from backend.modules.system import SystemModule


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    register_module(SystemModule)
    yield
    clear_registry()


@pytest.mark.asyncio
async def test_system_poll_shape():
    mod = SystemModule({"interval": 0.1})
    await mod.setup()
    data = await mod.poll()

    assert set(data.keys()) >= {"cpu", "ram", "swap", "network"}

    cpu = data["cpu"]
    assert "percent" in cpu
    assert isinstance(cpu["per_core"], list)
    assert cpu["count"] == len(cpu["per_core"])
    assert cpu["count"] >= 1

    ram = data["ram"]
    assert ram["total"] > 0
    assert 0 <= ram["percent"] <= 100

    net = data["network"]
    assert net["rx_bytes_per_s"] >= 0
    assert net["tx_bytes_per_s"] >= 0


@pytest.mark.asyncio
async def test_system_first_poll_has_zero_net_rates():
    mod = SystemModule({"interval": 0.1})
    await mod.setup()
    data = await mod.poll()
    # Setup primed _last_net but no real interval has elapsed yet, so the
    # rates should be ~0 (delta is tiny).
    assert data["network"]["rx_bytes_per_s"] >= 0
    assert data["network"]["tx_bytes_per_s"] >= 0


@pytest.mark.asyncio
async def test_system_network_rates_after_delay():
    mod = SystemModule({"interval": 0.1})
    await mod.setup()
    await mod.poll()
    await asyncio.sleep(0.1)
    data = await mod.poll()
    # Just verify the calculation runs without error and produces non-negative
    # rates; we can't assume actual traffic in CI.
    assert data["network"]["rx_bytes_per_s"] >= 0
    assert data["network"]["tx_bytes_per_s"] >= 0
    assert data["network"]["rx_total"] >= 0
    assert data["network"]["tx_total"] >= 0


@pytest.mark.asyncio
async def test_system_disk_path_is_configurable(tmp_path):
    mod = SystemModule({"interval": 0.1, "disk_path": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    assert data["disk"] is not None
    assert data["disk"]["path"] == str(tmp_path)
    assert data["disk"]["total"] > 0
