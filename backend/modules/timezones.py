"""The current offset of every time zone, for the clock and the world clock.

The kiosk's JavaScript knows local time and UTC, nothing else: Qt's engine has
no time zone database. This module reads the IANA database every Linux has
under /usr/share/zoneinfo, the one the system clock reads too, and hands out
each zone's offset from UTC in minutes. A tile then shows a zone's time as
UTC plus that offset.

Offsets change only at a daylight saving switch, so with deduplication the
answer goes out once and then again when some zone switches. The poll runs
every minute, which is how late a clock in another zone can be with its own
switch. The same answer carries `choices`, the list the clock's options show
for picking a zone.
"""

from __future__ import annotations

import zoneinfo
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, ClassVar

from .base import Module, register_module


@lru_cache(maxsize=1)
def all_zones() -> list[str]:
    """Every zone of the database, without the legacy names.

    `Etc/GMT+5` means UTC-5 (the sign is inverted on purpose) and `US/Eastern`
    and friends are aliases. Both only confuse in a picker.
    """
    zones = []
    for name in zoneinfo.available_timezones():
        if "/" not in name or name.startswith(("Etc/", "SystemV/", "US/", "posix/", "right/")):
            continue
        zones.append(name)
    return sorted(zones)


def offset_minutes(name: str, moment: datetime) -> int | None:
    try:
        offset = moment.astimezone(zoneinfo.ZoneInfo(name)).utcoffset()
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return None
    return round(offset.total_seconds() / 60) if offset is not None else None


def utc_label(minutes: int) -> str:
    """`+2`, `-5:30`, `+5:45`, as written after "UTC"."""
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"{sign}{hours}" + (f":{rest:02d}" if rest else "")


@register_module
class TimezonesModule(Module):
    name: ClassVar[str] = "timezones"
    default_interval: ClassVar[float] = 60.0

    async def poll(self) -> dict[str, Any]:
        moment = datetime.now(UTC)
        offsets: dict[str, int] = {}
        for zone in all_zones():
            minutes = offset_minutes(zone, moment)
            if minutes is not None:
                offsets[zone] = minutes
        return {
            "offsets": offsets,
            "choices": [{"value": zone, "label": f"{zone.replace('_', ' ')} · UTC{utc_label(minutes)}"}
                        for zone, minutes in offsets.items()],
        }
