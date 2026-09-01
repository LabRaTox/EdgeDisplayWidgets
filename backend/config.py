"""YAML configuration loader and Pydantic v2 schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

LogLevel = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)


class LoggingConfig(BaseModel):
    """Logging settings.

    The YAML key ``json`` is preserved as an alias for the Python attribute
    ``as_json`` to avoid shadowing ``BaseModel.json``.
    """

    model_config = ConfigDict(populate_by_name=True)

    level: LogLevel = "INFO"
    as_json: bool = Field(default=False, alias="json")


class ModuleConfig(BaseModel):
    """Per-module config block.

    Modules may declare arbitrary additional keys (forwarded as-is via
    ``extra = "allow"``). The Hub passes the dumped dict to the Module
    constructor so each module can pick out what it needs.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    interval: float | None = Field(default=None, gt=0)


class WidgetPlacement(BaseModel):
    """One widget instance on a page.

    Two equivalent placement formats are supported:
      • ``area``: a name referencing ``grid.areas`` (legacy CSS-Grid template).
      • ``col`` + ``row`` (+ ``colspan`` + ``rowspan``): direct grid coords,
        1-indexed.

    When ``area`` is set, the page's validator derives col/row/spans from the
    grid template, so consumers can always rely on the numeric fields.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    area: str | None = None
    col: int = Field(default=1, ge=1)
    row: int = Field(default=1, ge=1)
    colspan: int = Field(default=1, ge=1)
    rowspan: int = Field(default=1, ge=1)
    variant: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class GridDef(BaseModel):
    columns: str = "1fr"
    rows: str = "1fr"
    areas: list[str] = Field(default_factory=list)


def _compute_area_rects(areas: list[str]) -> dict[str, dict[str, int]]:
    """Return the bounding rectangle (1-indexed) for every named area.

    The format comes from CSS-Grid, where a named area has to form a rectangle.
    That is not enforced again here: a layout that breaks the rule places its
    widgets by the bounding box, which is odd but not fatal, and the layout
    editor writes coordinates rather than areas anyway.
    """
    positions: dict[str, dict[str, int]] = {}
    for r, row_str in enumerate(areas):
        for c, name in enumerate(row_str.split()):
            if not name or name == ".":
                continue
            if name not in positions:
                positions[name] = {"min_r": r, "max_r": r, "min_c": c, "max_c": c}
            else:
                p = positions[name]
                p["min_r"] = min(p["min_r"], r)
                p["max_r"] = max(p["max_r"], r)
                p["min_c"] = min(p["min_c"], c)
                p["max_c"] = max(p["max_c"], c)
    return {
        name: {
            "col": p["min_c"] + 1,
            "row": p["min_r"] + 1,
            "colspan": p["max_c"] - p["min_c"] + 1,
            "rowspan": p["max_r"] - p["min_r"] + 1,
        }
        for name, p in positions.items()
    }


class PageConfig(BaseModel):
    id: str
    title: str = ""
    grid: GridDef
    widgets: list[WidgetPlacement] = Field(default_factory=list)

    @model_validator(mode="after")
    def _resolve_widget_placements(self) -> PageConfig:
        # If a grid.areas template is provided, derive col/row from named
        # areas for any widget that uses the legacy ``area`` field. Once
        # this runs every widget has well-defined numeric placements.
        if self.grid.areas:
            rects = _compute_area_rects(self.grid.areas)
            for w in self.widgets:
                if w.area:
                    if w.area not in rects:
                        raise ValueError(
                            f"page '{self.id}': widget '{w.id}' references "
                            f"undefined area '{w.area}' (known: {sorted(rects)})"
                        )
                    rect = rects[w.area]
                    w.col = rect["col"]
                    w.row = rect["row"]
                    w.colspan = rect["colspan"]
                    w.rowspan = rect["rowspan"]
        return self


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    default_theme: str = "cyberpunk"
    # Interface language of the kiosk. "auto" takes it from `LANG`. It lives in
    # the config rather than in the kiosk's own storage because the settings
    # window is a separate application: it cannot write anything the kiosk
    # keeps to itself, so what the window may change has to be server-side.
    default_language: str = "auto"
    modules: dict[str, ModuleConfig] = Field(default_factory=dict)
    pages: list[PageConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_page_ids(self) -> AppConfig:
        ids = [p.id for p in self.pages]
        if len(ids) != len(set(ids)):
            raise ValueError("page ids must be unique")
        return self


def load_config(path: str | Path) -> AppConfig:
    """Load and validate the YAML config file."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping, got {type(raw).__name__}")
    return AppConfig.model_validate(raw)
