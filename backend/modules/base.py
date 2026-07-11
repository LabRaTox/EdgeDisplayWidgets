"""Module ABC and registry for backend data producers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Literal

from loguru import logger
from pydantic import BaseModel


class SettingField(BaseModel):
    """Declarative descriptor for one editable module setting.

    A module lists these in ``settings_schema`` and the Settings UI renders a
    matching input for each — so a new module option becomes editable by
    declaring it here, with no bespoke UI code. This mirrors the registry
    pattern: adding config surface requires zero core changes.

    ``key`` is the config key relative to the module block; use dotted notation
    for nested blocks (e.g. ``"govee.api_key"``). ``label_key`` / ``help_key`` /
    ``group_key`` are i18n keys resolved by the frontend (they fall back to the
    key string itself when a locale is missing the entry).
    """

    key: str
    type: Literal["bool", "int", "float", "text", "select", "list"]
    label_key: str
    default: Any = None
    secret: bool = False
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[str] | None = None
    placeholder_key: str | None = None
    help_key: str | None = None
    group_key: str | None = None


class Module(ABC):
    """Base class for all backend data-producing modules.

    Subclasses must:
      - set the class attribute ``name`` (unique, matched to the config key)
      - implement ``async def poll()`` returning a JSON-serialisable dict

    Subclasses may:
      - set ``default_interval`` (seconds between polls when config omits it)
      - set ``settings_schema`` (editable config fields exposed in the UI)
      - override ``setup()`` / ``teardown()`` for resource lifecycle
    """

    name: ClassVar[str] = ""
    default_interval: ClassVar[float] = 1.0
    # Module-specific config fields (beyond the common enabled/interval) that
    # the Settings UI should render an input for. Empty ⇒ nothing extra.
    settings_schema: ClassVar[list[SettingField]] = []

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        interval = config.get("interval")
        self.interval: float = (
            float(interval) if interval is not None else float(self.default_interval)
        )

    async def setup(self) -> None:
        """One-time init; override to open files, dbus connections, etc."""
        return None

    async def teardown(self) -> None:
        """Release resources acquired in ``setup``."""
        return None

    @abstractmethod
    async def poll(self) -> dict[str, Any]:
        """Return current data as a JSON-serialisable dict."""
        ...


_REGISTRY: dict[str, type[Module]] = {}


def register_module(cls: type[Module]) -> type[Module]:
    """Class decorator that adds a Module subclass to the global registry."""
    if not isinstance(cls, type) or not issubclass(cls, Module):
        raise TypeError(f"@register_module: {cls!r} must be a Module subclass")
    name = getattr(cls, "name", "")
    if not name:
        raise ValueError(f"@register_module: {cls.__name__} is missing a non-empty `name`")
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"@register_module: name '{name}' already registered to {existing.__name__}"
        )
    _REGISTRY[name] = cls
    logger.debug(f"registered module: {name} -> {cls.__name__}")
    return cls


def get_registry() -> dict[str, type[Module]]:
    """Return a shallow copy of the registry."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Test-only helper; do not call in production code."""
    _REGISTRY.clear()
