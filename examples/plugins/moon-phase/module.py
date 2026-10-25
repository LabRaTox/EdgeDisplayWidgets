"""Moon phase, one number, once an hour."""

from __future__ import annotations

import time
from typing import Any

from backend.modules.base import Module, SettingField, register_module

#: Length of a synodic month in days, and a new moon to count from.
SYNODIC_DAYS = 29.53058867
NEW_MOON_EPOCH_DAYS = 6.0


@register_module
class MoonPhaseModule(Module):
    name = "moon-phase"
    default_interval = 3600.0
    settings_schema = [
        SettingField(
            key="southern",
            type="bool",
            label_key="settings.mod.moon-phase.southern",
            default=False,
        ),
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.southern = bool(config.get("southern", False))

    async def poll(self) -> dict[str, Any]:
        days = (time.time() / 86400.0 - NEW_MOON_EPOCH_DAYS) % SYNODIC_DAYS
        return {"fraction": days / SYNODIC_DAYS, "days": days, "southern": self.southern}
