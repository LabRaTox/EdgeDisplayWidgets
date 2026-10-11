"""Tests for the kiosk's page grid: CSS track list to pixel offsets."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shell" / "qml_kiosk"))

from grid import spans, tracks  # noqa: E402


def test_template_becomes_fixed_and_stretch():
    assert tracks("32px 1fr 2fr minmax(0, 3fr)") == [
        {"fixed": 32.0, "stretch": 0.0},
        {"fixed": 0.0, "stretch": 1.0},
        {"fixed": 0.0, "stretch": 2.0},
        {"fixed": 0.0, "stretch": 3.0},
    ]


def test_minmax_with_a_space_is_one_track():
    # The shipped config writes it this way.
    template = "minmax(0, 1.66fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.66fr)"
    assert [t["stretch"] for t in tracks(template)] == [1.66, 1.0, 1.0, 1.66]


def test_unknown_token_is_an_equal_share():
    assert tracks("auto") == [{"fixed": 0.0, "stretch": 1.0}]


def test_empty_template_is_one_track():
    assert tracks("") == [{"fixed": 0.0, "stretch": 1.0}]


def test_fr_tracks_share_by_ratio():
    # 310 wide, one 10 pixel gap: 300 left for 1fr + 2fr.
    assert spans(tracks("1fr 2fr"), 310, 10) == [[0.0, 100.0], [110.0, 200.0]]


def test_fixed_track_keeps_its_size():
    # The row layout of the default page: `32px 1fr 1fr`.
    assert spans(tracks("32px 1fr 1fr"), 720, 8) == [
        [0.0, 32.0], [40.0, 336.0], [384.0, 336.0],
    ]


def test_fixed_column_keeps_its_size():
    assert spans(tracks("200px 1fr"), 1000, 0) == [[0.0, 200.0], [200.0, 800.0]]


def test_tracks_fill_the_total_exactly():
    result = spans(tracks("1fr 1fr 1fr"), 1000, 12)
    start, size = result[-1]
    assert start + size == pytest.approx(1000)


def test_overfull_fixed_tracks_leave_nothing_negative():
    result = spans(tracks("600px 1fr 600px"), 1000, 0)
    assert result[1] == [600.0, 0.0]
    assert all(size >= 0 for _, size in result)
