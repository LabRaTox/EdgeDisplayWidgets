"""The time zone module: offsets from the system's IANA database."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from backend.modules import timezones


def test_legacy_names_are_left_out():
    zones = timezones.all_zones()
    assert "Europe/Berlin" in zones and "America/Argentina/Buenos_Aires" in zones
    assert not any(z.startswith(("Etc/", "US/", "posix/")) for z in zones)
    assert zones == sorted(zones)


def test_offsets_follow_daylight_saving():
    winter = datetime(2026, 1, 15, 12, tzinfo=UTC)
    summer = datetime(2026, 7, 15, 12, tzinfo=UTC)
    assert timezones.offset_minutes("Europe/Berlin", winter) == 60
    assert timezones.offset_minutes("Europe/Berlin", summer) == 120
    assert timezones.offset_minutes("Asia/Kathmandu", winter) == 345
    assert timezones.offset_minutes("America/St_Johns", winter) == -210
    assert timezones.offset_minutes("Nowhere/Land", winter) is None


def test_labels():
    assert timezones.utc_label(120) == "+2"
    assert timezones.utc_label(-330) == "-5:30"
    assert timezones.utc_label(345) == "+5:45"
    assert timezones.utc_label(0) == "+0"


def test_poll_answer():
    data = asyncio.run(timezones.TimezonesModule({}).poll())
    assert data["offsets"]["Asia/Tokyo"] == 540
    tokyo = next(c for c in data["choices"] if c["value"] == "Asia/Tokyo")
    assert tokyo["label"] == "Asia/Tokyo · UTC+9"
    buenos = next(c for c in data["choices"] if c["value"] == "America/Argentina/Buenos_Aires")
    assert "Buenos Aires" in buenos["label"]
