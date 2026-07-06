"""Aggregate events from multiple sources into a ranked, deduped shortlist.

The aggregator is the single entry point the pipeline uses for discovery:

    fetch(city, window, event_types, count) -> list[Event]

It runs each configured source via :meth:`EventSource.safe_fetch` (so one
failing source never breaks the run), filters to the date window, dedupes across
sources, ranks, and returns the top ``count``.

Source selection: when real API keys are present those sources are used; the
:class:`MockSource` is included only when *no* real source is configured, so
development and demos always produce results without masking real data.
"""

from __future__ import annotations

import logging

from ..models import City, Event, EventType
from ..settings import Settings, get_settings
from ..timewindow import DateRange
from .base import EventSource
from .cache import ResponseCache
from .eventbrite import EventbriteSource
from .mock import MockSource
from .ticketmaster import TicketmasterSource

logger = logging.getLogger(__name__)


def default_sources(settings: Settings | None = None) -> list[EventSource]:
    """Build the source list based on which credentials are configured.

    Real sources that are configured are used. If none are configured, fall back
    to the :class:`MockSource` so the pipeline still yields events in dev.
    """
    settings = settings or get_settings()
    cache = ResponseCache(settings.cache_dir)
    real: list[EventSource] = [
        TicketmasterSource(settings=settings, cache=cache),
        EventbriteSource(settings=settings, cache=cache),
    ]
    configured = [s for s in real if s.is_configured()]
    if configured:
        return configured
    logger.info("no real event sources configured; using MockSource")
    return [MockSource()]


def _rank(event: Event, window: DateRange) -> float:
    """Score an event for ordering. Higher is better.

    Heuristics (sooner + richer metadata rank higher):
      - closer to the window start scores higher (favor imminent events)
      - having an image, venue, and description each add a small bonus
      - a source-provided rank_score (e.g. mock) is added directly
    """
    span = max((window.end - window.start).total_seconds(), 1.0)
    time_to_event = max((event.start - window.start).total_seconds(), 0.0)
    recency = 1.0 - min(time_to_event / span, 1.0)  # 1.0 = imminent, 0.0 = window end

    score = recency * 10.0
    if event.image_url:
        score += 2.0
    if event.venue:
        score += 1.0
    if event.description:
        score += 0.5
    score += event.rank_score
    return score


def dedupe(events: list[Event]) -> list[Event]:
    """Drop cross-source duplicates, keeping the richest record per key.

    "Richest" = the one with the most non-empty optional fields (image, venue,
    description, price, url), so we keep the most complete version of an event.
    """

    def richness(e: Event) -> int:
        return sum(
            1 for v in (e.image_url, e.venue, e.description, e.url, e.price_min) if v is not None
        )

    best: dict[str, Event] = {}
    for event in events:
        key = event.dedupe_key()
        current = best.get(key)
        if current is None or richness(event) > richness(current):
            best[key] = event
    return list(best.values())


def fetch(
    city: City,
    window: DateRange,
    event_types: list[EventType],
    count: int,
    *,
    sources: list[EventSource] | None = None,
) -> list[Event]:
    """Discover events: run sources, filter, dedupe, rank, and take top ``count``."""
    sources = sources if sources is not None else default_sources()

    collected: list[Event] = []
    for source in sources:
        collected.extend(source.safe_fetch(city, window, event_types))

    # Keep only events inside the window (sources may over-return).
    in_window = [e for e in collected if window.contains(e.start)]

    deduped = dedupe(in_window)
    deduped.sort(key=lambda e: _rank(e, window), reverse=True)

    top = deduped[: max(count, 0)]
    for event in top:
        event.rank_score = _rank(event, window)
    logger.info(
        "aggregated %d raw -> %d in-window -> %d deduped -> top %d",
        len(collected),
        len(in_window),
        len(deduped),
        len(top),
    )
    return top
