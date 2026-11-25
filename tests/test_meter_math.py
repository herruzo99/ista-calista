"""Consumption across meter resets (idea from @macanakin's fork)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.ista_calista.sensor import _consumption_across_resets


def _readings(values: list[float | None]) -> list:
    start = datetime(2026, 9, 30, tzinfo=timezone.utc)
    return [
        SimpleNamespace(date=start + timedelta(days=i), reading=value)
        for i, value in enumerate(values)
    ]


def test_no_reset_is_last_minus_first():
    assert _consumption_across_resets(_readings([100.0, 110.0, 118.5])) == 18.5


def test_reset_starts_a_new_cycle():
    # 118.66 -> 0 is not -118.66: the meter was replaced and counts again.
    assert _consumption_across_resets(_readings([100.0, 118.66, 0.0, 3.0, 8.0])) == 26.66


def test_reset_without_consumption_is_zero():
    assert _consumption_across_resets(_readings([118.66, 118.66, 0.0, 0.0])) == 0.0


def test_missing_readings_are_ignored():
    assert _consumption_across_resets(_readings([10.0, 15.0, None, 20.0])) == 10.0


def test_fewer_than_two_readings_is_zero():
    assert _consumption_across_resets(_readings([42.0])) == 0.0
    assert _consumption_across_resets([]) == 0.0


def test_readings_are_sorted_by_date_before_counting():
    # Given out of order, the helper sorts by date: 100 -> 110 -> 105, where the
    # last step is a drop and therefore a new cycle.
    readings = _readings([100.0, 110.0, 105.0])
    readings.reverse()
    assert _consumption_across_resets(readings) == 115.0


def test_negative_and_nan_readings_are_ignored():
    values = [100.0, -5.0, float("nan"), 110.0]
    assert _consumption_across_resets(_readings(values)) == 10.0


def test_readings_without_a_date_are_ignored():
    readings = _readings([100.0, 110.0])
    readings.append(SimpleNamespace(date=None, reading=999.0))
    assert _consumption_across_resets(readings) == 10.0
