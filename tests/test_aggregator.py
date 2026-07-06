"""Tests for the aggregator: dedupe, ranking, window filter, failure isolation."""

from __future__ import annotations

from datetime import UTC, datetime

from events_gen.models import City, Event, EventType
from events_gen.sources import aggregator
from events_gen.sources.base import EventSource
from events_gen.timewindow import DateRange

CITY = City(
    slug="testville",
    name="Testville",
    country="Nowhere",
    country_code="NA",
    timezone="UTC",
    latitude=0.0,
    longitude=0.0,
)

WINDOW = DateRange(
    start=datetime(2026, 7, 6, 0, 0, tzinfo=UTC),
    end=datetime(2026, 7, 13, 0, 0, tzinfo=UTC),
)


def _event(title: str, day: int, **kw: object) -> Event:
    base = {
        "source": "s",
        "title": title,
        "start": datetime(2026, 7, day, 20, 0, tzinfo=UTC),
        "venue": "Hall",
        "city_slug": "testville",
    }
    base.update(kw)
    return Event(**base)  # type: ignore[arg-type]


class _StaticSource(EventSource):
    def __init__(self, name: str, events: list[Event], configured: bool = True) -> None:
        self.name = name
        self._events = events
        self._configured = configured

    def is_configured(self) -> bool:
        return self._configured

    def fetch(self, city: City, window: DateRange, event_types: list[EventType]) -> list[Event]:
        return list(self._events)


class _BoomSource(EventSource):
    name = "boom"

    def is_configured(self) -> bool:
        return True

    def fetch(self, city: City, window: DateRange, event_types: list[EventType]) -> list[Event]:
        raise RuntimeError("source exploded")


# ── dedupe ──


def test_dedupe_collapses_same_title_day_venue() -> None:
    a = _event("Show", 8, source="a")
    b = _event("show", 8, source="b", venue="hall")  # same key, different source
    result = aggregator.dedupe([a, b])
    assert len(result) == 1


def test_dedupe_keeps_richest_record() -> None:
    plain = _event("Show", 8, source="a")
    rich = _event(
        "Show",
        8,
        source="b",
        image_url="https://example.com/i.jpg",
        description="great show",
    )
    result = aggregator.dedupe([plain, rich])
    assert len(result) == 1
    assert result[0].source == "b"  # the richer one survived


# ── window filter ──


def test_fetch_filters_out_of_window_events() -> None:
    src = _StaticSource("s", [_event("In", 8), _event("Out", 20)])
    result = aggregator.fetch(CITY, WINDOW, [], count=10, sources=[src])
    titles = {e.title for e in result}
    assert titles == {"In"}


# ── ranking ──


def test_fetch_ranks_sooner_and_richer_first() -> None:
    late_plain = _event("Late", 12, source="a")
    soon_rich = _event(
        "Soon",
        6,
        source="b",
        image_url="https://example.com/i.jpg",
        description="d",
    )
    src = _StaticSource("s", [late_plain, soon_rich])
    result = aggregator.fetch(CITY, WINDOW, [], count=10, sources=[src])
    assert result[0].title == "Soon"


def test_fetch_respects_count() -> None:
    events = [_event(f"E{i}", 7 + (i % 5)) for i in range(20)]
    src = _StaticSource("s", events)
    result = aggregator.fetch(CITY, WINDOW, [], count=3, sources=[src])
    assert len(result) == 3


# ── failure isolation ──


def test_fetch_isolates_failing_source() -> None:
    good = _StaticSource("good", [_event("Good", 8)])
    result = aggregator.fetch(CITY, WINDOW, [], count=10, sources=[_BoomSource(), good])
    assert [e.title for e in result] == ["Good"]


def test_fetch_skips_unconfigured_source() -> None:
    off = _StaticSource("off", [_event("Hidden", 8)], configured=False)
    on = _StaticSource("on", [_event("Shown", 8)])
    result = aggregator.fetch(CITY, WINDOW, [], count=10, sources=[off, on])
    assert [e.title for e in result] == ["Shown"]


def test_fetch_empty_when_all_sources_empty() -> None:
    src = _StaticSource("s", [])
    assert aggregator.fetch(CITY, WINDOW, [], count=5, sources=[src]) == []
