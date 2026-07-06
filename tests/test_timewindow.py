"""Tests for time-window computation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from events_gen.models import TimeWindow
from events_gen.timewindow import compute_window


def test_week_window_ends_sunday_night() -> None:
    # 2026-07-08 is a Wednesday.
    now = datetime(2026, 7, 8, 10, 0, tzinfo=UTC)
    r = compute_window(TimeWindow.WEEK, "UTC", now=now)
    assert r.start == now
    # End of Sunday 2026-07-12.
    assert r.end.year == 2026 and r.end.month == 7 and r.end.day == 12
    assert (r.end.hour, r.end.minute, r.end.second) == (23, 59, 59)


def test_week_window_on_sunday_ends_same_day() -> None:
    now = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)  # Sunday
    r = compute_window(TimeWindow.WEEK, "UTC", now=now)
    assert r.end.day == 12


def test_month_window_ends_last_day() -> None:
    now = datetime(2026, 2, 10, 9, 0, tzinfo=UTC)  # non-leap Feb
    r = compute_window(TimeWindow.MONTH, "UTC", now=now)
    assert r.end.month == 2 and r.end.day == 28


def test_month_window_december_rolls_over() -> None:
    now = datetime(2026, 12, 5, 9, 0, tzinfo=UTC)
    r = compute_window(TimeWindow.MONTH, "UTC", now=now)
    assert r.end.month == 12 and r.end.day == 31


def test_timezone_affects_utc_bounds() -> None:
    now = datetime(2026, 7, 8, 2, 0, tzinfo=UTC)
    tokyo = compute_window(TimeWindow.WEEK, "Asia/Tokyo", now=now)
    utc = compute_window(TimeWindow.WEEK, "UTC", now=now)
    # End-of-Sunday in Tokyo is earlier in UTC than end-of-Sunday in UTC.
    assert tokyo.end < utc.end


def test_custom_requires_both_bounds() -> None:
    with pytest.raises(ValueError, match="requires both"):
        compute_window(TimeWindow.CUSTOM, "UTC", start=datetime(2026, 7, 1))


def test_custom_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="after start"):
        compute_window(
            TimeWindow.CUSTOM,
            "UTC",
            start=datetime(2026, 7, 10, tzinfo=UTC),
            end=datetime(2026, 7, 1, tzinfo=UTC),
        )


def test_contains() -> None:
    now = datetime(2026, 7, 8, 10, 0, tzinfo=UTC)
    r = compute_window(TimeWindow.WEEK, "UTC", now=now)
    assert r.contains(datetime(2026, 7, 9, 12, 0, tzinfo=UTC))
    assert not r.contains(datetime(2026, 7, 1, 12, 0, tzinfo=UTC))
    # Naive datetime treated as UTC.
    assert r.contains(datetime(2026, 7, 9, 12, 0))
