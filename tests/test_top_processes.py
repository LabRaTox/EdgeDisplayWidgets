"""Tests for the TopProcessesModule (psutil-backed)."""

from __future__ import annotations

import asyncio
import os

import pytest

from backend.modules.base import clear_registry, register_module
from backend.modules.top_processes import TopProcessesModule


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    register_module(TopProcessesModule)
    yield
    clear_registry()


@pytest.mark.asyncio
async def test_top_processes_shape():
    mod = TopProcessesModule({"limit": 3})
    await mod.setup()
    # First poll right after prime: deltas are tiny but list shape is valid.
    data = await mod.poll()
    assert "processes" in data
    assert isinstance(data["processes"], list)
    assert len(data["processes"]) <= 3
    assert data["cpu_count"] >= 1


@pytest.mark.asyncio
async def test_top_processes_fields():
    mod = TopProcessesModule({"limit": 5})
    await mod.setup()
    # A short sleep lets some processes accumulate measurable CPU time.
    await asyncio.sleep(0.1)
    data = await mod.poll()
    for p in data["processes"]:
        assert isinstance(p["pid"], int)
        assert isinstance(p["name"], str)
        assert p["cpu_percent"] >= 0
        assert p["rss"] >= 0


@pytest.mark.asyncio
async def test_top_processes_sorted_desc():
    mod = TopProcessesModule({"limit": 10})
    await mod.setup()
    await asyncio.sleep(0.1)
    data = await mod.poll()
    cpus = [p["cpu_percent"] for p in data["processes"]]
    assert cpus == sorted(cpus, reverse=True)


@pytest.mark.asyncio
async def test_top_processes_limit_is_respected():
    mod = TopProcessesModule({"limit": 2})
    await mod.setup()
    data = await mod.poll()
    assert len(data["processes"]) <= 2


@pytest.mark.asyncio
async def test_top_processes_finds_test_process():
    """Our own pytest process should show up at least once."""
    mod = TopProcessesModule({"limit": 1000})
    await mod.setup()
    await asyncio.sleep(0.05)
    data = await mod.poll()
    pids = {p["pid"] for p in data["processes"]}
    assert os.getpid() in pids
