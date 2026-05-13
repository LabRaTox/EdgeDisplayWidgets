"""Tests for the DiskUsageModule (psutil-backed)."""

from __future__ import annotations

import pytest

from backend.modules.base import clear_registry, register_module
from backend.modules.disk_usage import DiskUsageModule


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    register_module(DiskUsageModule)
    yield
    clear_registry()


@pytest.mark.asyncio
async def test_disk_usage_shape():
    mod = DiskUsageModule({})
    await mod.setup()
    data = await mod.poll()
    assert "disks" in data
    assert isinstance(data["disks"], list)
    # Whatever host runs the test must have at least a root filesystem.
    assert any(d["mountpoint"] == "/" for d in data["disks"])


@pytest.mark.asyncio
async def test_disk_usage_fields():
    mod = DiskUsageModule({})
    await mod.setup()
    data = await mod.poll()
    for d in data["disks"]:
        assert d["total"] > 0
        assert 0 <= d["percent"] <= 100
        assert d["used"] + d["free"] <= d["total"] + 1  # tolerate rounding
        assert "fstype" in d
        assert "device" in d


@pytest.mark.asyncio
async def test_disk_usage_sorted_by_percent_desc():
    mod = DiskUsageModule({})
    await mod.setup()
    data = await mod.poll()
    percents = [d["percent"] for d in data["disks"]]
    assert percents == sorted(percents, reverse=True)


@pytest.mark.asyncio
async def test_disk_usage_min_size_filter():
    # Set the size floor absurdly high so nothing qualifies.
    mod = DiskUsageModule({"min_size_gb": 1_000_000.0})
    await mod.setup()
    data = await mod.poll()
    assert data["disks"] == []


@pytest.mark.asyncio
async def test_disk_usage_mount_allowlist(tmp_path):
    # Pin the module to a known path so we don't depend on host-specific mounts.
    mod = DiskUsageModule({"mounts": ["/"], "min_size_gb": 0.0})
    await mod.setup()
    data = await mod.poll()
    assert [d["mountpoint"] for d in data["disks"]] == ["/"]
