"""Module ABC and registry for backend data producers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from loguru import logger


class Module(ABC):
    """Base class for all backend data-producing modules.

    Subclasses must:
      - set the class attribute ``name`` (unique, matched to the config key)
      - implement ``async def poll()`` returning a JSON-serialisable dict

    Subclasses may:
      - set ``default_interval`` (seconds between polls when config omits it)
      - override ``setup()`` / ``teardown()`` for resource lifecycle
    """

    name: ClassVar[str] = ""
    default_interval: ClassVar[float] = 1.0

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
