"""Tests for M10: event picker helpers (sort, select, duration, stale detection)."""

from __future__ import annotations

from datetime import UTC, datetime

from events_gen.models import Event
from events_gen.render.formats import REEL
from events_gen.ui.picker import (
    estimate_duration,
    is_fetch_stale,
    select_top_n,
    sort_candidates,
)


def _ev(
    title: str = "Ev",
    rank: float = 0.0,
    day: int = 10,
    price: float | None = None,
) -> Event:
    return Event(
        source="mock",
        title=title,
        start=datetime(2026, 7, day, 20, tzinfo=UTC),
        venue="Hall",
        city_slug="x",
        rank_score=rank,
        price_min=price,
    )


class TestSort:
    def test_rank_descending(self) -> None:
        events = [_ev("A", rank=1), _ev("B", rank=5), _ev("C", rank=3)]
        result = sort_candidates(events, "rank")
        assert [e.title for e in result] == ["B", "C", "A"]

    def test_date_ascending(self) -> None:
        events = [_ev("Late", day=15), _ev("Soon", day=7), _ev("Mid", day=11)]
        result = sort_candidates(events, "date")
        assert [e.title for e in result] == ["Soon", "Mid", "Late"]

    def test_price_ascending(self) -> None:
        events = [_ev("Pricey", price=100), _ev("Free", price=None), _ev("Cheap", price=25)]
        result = sort_candidates(events, "price")
        # None treated as 0 → comes first.
        assert [e.title for e in result] == ["Free", "Cheap", "Pricey"]

    def test_name_case_insensitive(self) -> None:
        events = [_ev("Zebra"), _ev("apple"), _ev("Banana")]
        result = sort_candidates(events, "name")
        assert [e.title for e in result] == ["apple", "Banana", "Zebra"]

    def test_unknown_key_returns_original_order(self) -> None:
        events = [_ev("A"), _ev("B")]
        assert sort_candidates(events, "bogus") == events


class TestSelectTopN:
    def test_returns_first_n_ids(self) -> None:
        events = [_ev(f"E{i}") for i in range(10)]
        ids = select_top_n(events, 3)
        assert ids == {events[0].id, events[1].id, events[2].id}

    def test_n_larger_than_list(self) -> None:
        events = [_ev("A"), _ev("B")]
        ids = select_top_n(events, 5)
        assert len(ids) == 2

    def test_n_zero(self) -> None:
        assert select_top_n([_ev("A")], 0) == set()


class TestEstimateDuration:
    def test_matches_format_math(self) -> None:
        # No intro/outro cards anymore — duration is just one card per event.
        d = estimate_duration(5, REEL)
        assert d == 5 * REEL.seconds_per_card

    def test_zero_events(self) -> None:
        d = estimate_duration(0, REEL)
        assert d == 0.0


class TestFetchStale:
    def test_same_params_not_stale(self) -> None:
        p = {"city": "nyc", "window": "week", "types": ["music"]}
        assert is_fetch_stale(p, p) is False

    def test_changed_city_is_stale(self) -> None:
        old = {"city": "nyc", "window": "week", "types": []}
        new = {"city": "tokyo", "window": "week", "types": []}
        assert is_fetch_stale(old, new) is True

    def test_none_fetch_params_not_stale(self) -> None:
        assert is_fetch_stale(None, {"city": "nyc"}) is False
