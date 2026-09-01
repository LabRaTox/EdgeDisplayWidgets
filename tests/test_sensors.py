"""Tests for the SensorsModule (hwmon parsing)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.modules.base import clear_registry, register_module
from backend.modules.sensors import SensorsModule, _prettify_nvme_model


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    register_module(SensorsModule)
    yield
    clear_registry()


def _make_chip(root: Path, slot: int, chip_name: str, temps: dict[int, tuple[str, int]]) -> None:
    """Build a fake `/sys/class/hwmon/hwmonN` directory.

    `temps` is {idx: (label_or_empty, milli_celsius)}.
    """
    d = root / f"hwmon{slot}"
    d.mkdir(parents=True)
    (d / "name").write_text(chip_name)
    for idx, (label, value) in temps.items():
        (d / f"temp{idx}_input").write_text(str(value))
        if label:
            (d / f"temp{idx}_label").write_text(label)


@pytest.mark.asyncio
async def test_discovers_known_chips_with_unlabeled_inputs(tmp_path: Path):
    _make_chip(tmp_path, 0, "k10temp", {1: ("Tctl", 45000), 2: ("Tdie", 44000)})
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()

    assert data["available"] is True
    chips = {r["chip"] for r in data["readings"]}
    assert "k10temp" in chips
    labels = [r["label"] for r in data["readings"] if r["chip"] == "k10temp"]
    assert "Tctl" in labels
    assert "Tdie" in labels
    # Tctl is in PRIMARY_LABELS so should be marked primary
    tctl = next(r for r in data["readings"] if r["label"] == "Tctl")
    assert tctl["primary"] is True


@pytest.mark.asyncio
async def test_includes_labelled_inputs_from_unknown_chips(tmp_path: Path):
    _make_chip(tmp_path, 0, "weird_chip", {1: ("Vault Temp", 38000)})
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    assert any(r["label"] == "Vault Temp" for r in data["readings"])


@pytest.mark.asyncio
async def test_skips_unlabelled_inputs_from_unknown_chips(tmp_path: Path):
    _make_chip(tmp_path, 0, "weird_chip", {1: ("", 38000)})
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    # No usable inputs => module disabled
    assert mod._available is False


@pytest.mark.asyncio
async def test_skips_blacklisted_chips(tmp_path: Path):
    _make_chip(tmp_path, 0, "nvidia", {1: ("GPU", 65000)})
    _make_chip(tmp_path, 1, "k10temp", {1: ("Tctl", 45000)})
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    chips = {r["chip"] for r in data["readings"]}
    assert "nvidia" not in chips
    assert "k10temp" in chips


@pytest.mark.asyncio
async def test_returns_unavailable_when_no_hwmon(tmp_path: Path):
    # Empty directory -> nothing to discover
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    assert data["available"] is False
    assert "no usable" in data["reason"] or "discovery" in data["reason"]


@pytest.mark.asyncio
async def test_returns_unavailable_when_root_missing():
    mod = SensorsModule({"hwmon_root": "/nonexistent/path"})
    await mod.setup()
    data = await mod.poll()
    assert data["available"] is False


@pytest.mark.asyncio
async def test_temp_value_converted_from_millicelsius(tmp_path: Path):
    _make_chip(tmp_path, 0, "coretemp", {1: ("Package id 0", 67500)})
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    assert data["readings"][0]["temp_c"] == 67.5


@pytest.mark.asyncio
async def test_display_names_for_known_chip_and_label(tmp_path: Path):
    _make_chip(tmp_path, 0, "k10temp", {1: ("Tctl", 39000), 3: ("Tccd1", 36000)})
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    tctl = next(r for r in data["readings"] if r["label"] == "Tctl")
    tccd1 = next(r for r in data["readings"] if r["label"] == "Tccd1")
    assert tctl["display_chip"] == "CPU"
    assert tctl["display_label"] == "Package"
    assert tccd1["display_chip"] == "CPU"
    assert tccd1["display_label"] == "CCD 1"


@pytest.mark.asyncio
async def test_nvme_drives_disambiguated_by_model(tmp_path: Path):
    for slot, model in enumerate(["Force MP510", "CT500P1SSD8", "CT2000P5PSSD8"]):
        _make_chip(tmp_path, slot, "nvme", {1: ("Composite", 50000)})
        device = tmp_path / f"hwmon{slot}" / "device"
        device.mkdir()
        (device / "model").write_text(model)
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    nvme_labels = {r["display_label"] for r in data["readings"] if r["display_chip"] == "NVMe"}
    assert nvme_labels == {"Corsair MP510", "Crucial P1 500GB", "Crucial P5 Plus 2TB"}
    # IDs must be unique even though raw chip:idx collides.
    ids = [r["id"] for r in data["readings"]]
    assert len(ids) == len(set(ids))


def test_prettify_nvme_model_known_patterns():
    assert _prettify_nvme_model("CT500P1SSD8") == "Crucial P1 500GB"
    assert _prettify_nvme_model("CT2000P5PSSD8") == "Crucial P5 Plus 2TB"
    assert _prettify_nvme_model("CT1000T700SSD3") == "Crucial T700 1TB"
    assert _prettify_nvme_model("Force MP510") == "Corsair MP510"
    assert _prettify_nvme_model("Samsung SSD 990 PRO 2TB") == "Samsung 990 Pro 2TB"
    # Unknown patterns fall through untouched.
    assert _prettify_nvme_model("WeirdVendor X1") == "WeirdVendor X1"
    assert _prettify_nvme_model("") == ""


@pytest.mark.asyncio
async def test_nvme_drops_sub_sensors(tmp_path: Path):
    _make_chip(
        tmp_path, 0, "nvme",
        {1: ("Composite", 50000), 2: ("Sensor 1", 48000), 3: ("Sensor 2", 47000)},
    )
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    labels = [r["label"] for r in data["readings"]]
    assert labels == ["Composite"]


@pytest.mark.asyncio
async def test_spd5118_dimms_numbered(tmp_path: Path):
    _make_chip(tmp_path, 0, "spd5118", {1: ("", 37000)})
    _make_chip(tmp_path, 1, "spd5118", {1: ("", 37500)})
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    dimm_labels = sorted(r["display_label"] for r in data["readings"])
    assert dimm_labels == ["DIMM 1", "DIMM 2"]
    assert all(r["display_chip"] == "RAM" for r in data["readings"])


@pytest.mark.asyncio
async def test_network_chips_are_skipped(tmp_path: Path):
    _make_chip(tmp_path, 0, "r8169_0_e00:00", {1: ("", 53000)})
    _make_chip(tmp_path, 1, "mt7921_phy0", {1: ("", 44000)})
    _make_chip(tmp_path, 2, "k10temp", {1: ("Tctl", 39000)})
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    chips = {r["chip"] for r in data["readings"]}
    assert chips == {"k10temp"}


@pytest.mark.asyncio
async def test_primary_readings_sort_first(tmp_path: Path):
    _make_chip(tmp_path, 0, "coretemp", {1: ("Core 0", 50000), 2: ("Package id 0", 60000)})
    mod = SensorsModule({"hwmon_root": str(tmp_path)})
    await mod.setup()
    data = await mod.poll()
    # 'Package id 0' is in PRIMARY_LABELS, should appear before 'Core 0'
    labels = [r["label"] for r in data["readings"]]
    assert labels.index("Package id 0") < labels.index("Core 0")


# --- Stable ids ------------------------------------------------------------
#
# A layout stores the id of the sensor a tile shows. hwmon slots are handed out
# in driver probe order, so an id built from `hwmonN` can point at a different
# chip after a reboot. These pin down that it is built from the hardware
# address instead, and that two chips never end up sharing one id.


def _link_device(root: Path, slot: int, target: Path) -> None:
    """Give a fake chip the `device` symlink a real one has."""
    target.mkdir(parents=True, exist_ok=True)
    (root / f"hwmon{slot}" / "device").symlink_to(target)


@pytest.mark.asyncio
async def test_id_is_built_from_the_hardware_address(tmp_path: Path):
    hwmon = tmp_path / "hwmon"
    _make_chip(hwmon, 3, "k10temp", {1: ("Tctl", 45000)})
    _link_device(hwmon, 3, tmp_path / "devices" / "pci0000:00" / "0000:00:18.3")

    mod = SensorsModule({"hwmon_root": str(hwmon)})
    await mod.setup()
    data = await mod.poll()

    ids = [r["id"] for r in data["readings"]]
    assert ids == ["k10temp@0000:00:18.3:1"]
    # The slot must not appear: that is the part that moves.
    assert "hwmon3" not in ids[0]


@pytest.mark.asyncio
async def test_the_id_survives_a_different_hwmon_slot(tmp_path: Path):
    """The same chip on the same address, enumerated differently, keeps its id.
    This is the whole point: a tile still shows the sensor it was given."""
    ids = []
    for slot in (3, 7):
        hwmon = tmp_path / f"boot{slot}"
        _make_chip(hwmon, slot, "k10temp", {1: ("Tctl", 45000)})
        _link_device(hwmon, slot, tmp_path / "dev" / "0000:00:18.3")
        mod = SensorsModule({"hwmon_root": str(hwmon)})
        await mod.setup()
        ids.append((await mod.poll())["readings"][0]["id"])
    assert ids[0] == ids[1]


@pytest.mark.asyncio
async def test_drives_of_the_same_kind_get_different_ids(tmp_path: Path):
    """Three NVMe drives all report as `nvme`. They sit in different slots, so
    picking one must not be able to give you another."""
    hwmon = tmp_path / "hwmon"
    for slot, pci in enumerate(("0000:02:00.0", "0000:03:00.0", "0000:04:00.0")):
        _make_chip(hwmon, slot, "nvme", {1: ("Composite", 40000 + slot)})
        # A drive links to its controller instance, which is a counter itself;
        # the address one level up is the stable part.
        _link_device(hwmon, slot, tmp_path / "devices" / pci / "nvme" / f"nvme{slot}")

    mod = SensorsModule({"hwmon_root": str(hwmon)})
    await mod.setup()
    ids = [r["id"] for r in (await mod.poll())["readings"]]
    assert len(set(ids)) == 3, ids
    assert all("nvme@0000:0" in i for i in ids), ids


@pytest.mark.asyncio
async def test_readings_without_an_address_stay_unique(tmp_path: Path):
    """Hardware that reports no address at all falls back to the hwmon slot.
    That is not stable across reboots, but it is still unique, so a tile can
    never show a sensor other than the one it names."""
    hwmon = tmp_path / "hwmon"
    _make_chip(hwmon, 0, "acpitz", {1: ("", 40000)})
    _make_chip(hwmon, 1, "acpitz", {1: ("", 41000)})

    mod = SensorsModule({"hwmon_root": str(hwmon), "include_unknown": True})
    await mod.setup()
    ids = [r["id"] for r in (await mod.poll())["readings"]]
    assert len(set(ids)) == len(ids), ids


@pytest.mark.asyncio
async def test_ids_are_unique_on_this_machine():
    """Against the real /sys, when it is there."""
    if not Path("/sys/class/hwmon").is_dir():
        pytest.skip("no hwmon on this machine")
    mod = SensorsModule({})
    await mod.setup()
    data = await mod.poll()
    if data.get("available") is not True:
        pytest.skip(data.get("reason", "no readings"))
    ids = [r["id"] for r in data["readings"]]
    assert len(set(ids)) == len(ids), f"duplicate ids: {ids}"


@pytest.mark.asyncio
async def test_two_chips_on_one_device_are_told_apart(tmp_path: Path, caplog):
    """One device can expose several hwmon nodes. Same chip name, same address,
    same input index would be one id for two readings, and a tile pointing at
    it would show whichever came first. The slot is appended instead, and the
    fallback is logged rather than silent."""
    hwmon = tmp_path / "hwmon"
    device = tmp_path / "devices" / "0000:00:18.3"
    for slot in (0, 1):
        _make_chip(hwmon, slot, "k10temp", {1: ("Tctl", 45000 + slot)})
        _link_device(hwmon, slot, device)

    mod = SensorsModule({"hwmon_root": str(hwmon)})
    await mod.setup()
    ids = [r["id"] for r in (await mod.poll())["readings"]]

    assert len(set(ids)) == 2, ids
    assert all(i.endswith(("#hwmon0", "#hwmon1")) for i in ids), ids
