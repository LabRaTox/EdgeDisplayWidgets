"""Tests for picking the kiosk's output."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shell" / "qml_kiosk"))

from screens import pick_screen  # noqa: E402


@dataclass
class Size:
    w: int
    h: int

    def width(self) -> int:
        return self.w

    def height(self) -> int:
        return self.h


@dataclass
class FakeScreen:
    out: str
    w: int
    h: int
    ratio: float = 1.0
    maker: str = ""
    label: str = ""

    def name(self) -> str:
        return self.out

    def model(self) -> str:
        return self.label

    def manufacturer(self) -> str:
        return self.maker

    def geometry(self) -> Size:
        return Size(self.w, self.h)

    def devicePixelRatio(self) -> float:
        return self.ratio


MAIN = FakeScreen("DP-3", 1920, 1080)


def test_by_resolution():
    edge = FakeScreen("DP-4", 2560, 720)
    assert pick_screen([MAIN, edge], "", 2560, 720) is edge


def test_scaled_output_is_found_in_device_pixels():
    edge = FakeScreen("DP-4", 2048, 576, ratio=1.25)
    assert pick_screen([MAIN, edge], "", 2560, 720) is edge


def test_panel_on_its_side_is_found():
    edge = FakeScreen("DP-4", 720, 2560)
    assert pick_screen([MAIN, edge], "", 2560, 720) is edge


def test_by_model_name_when_the_size_says_nothing():
    edge = FakeScreen("DP-4", 1700, 478, ratio=1.33, maker="Corsair", label="XENEON EDGE")
    assert pick_screen([MAIN, edge], "", 2560, 720) is edge


def test_name_given_is_used_verbatim():
    edge = FakeScreen("DP-4", 2560, 720)
    assert pick_screen([MAIN, edge], "DP-3", 2560, 720) is MAIN
    assert pick_screen([MAIN, edge], "HDMI-1", 2560, 720) is None


def test_nothing_matches():
    assert pick_screen([MAIN], "", 2560, 720) is None
