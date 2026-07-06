"""A deterministic mock event source for development and demos.

Generates plausible synthetic events spread across the requested window and
event types, so the full pipeline (aggregate → content → render) can run with
no API keys. Always "configured". Deterministic given the same inputs (no
randomness) so tests and previews are stable.
"""

from __future__ import annotations

from datetime import timedelta

from ..models import City, Event, EventType
from ..timewindow import DateRange
from .base import EventSource

_SAMPLE_VENUES = [
    "The Grand Hall",
    "Riverside Arena",
    "Downtown Amphitheater",
    "Old Town Gallery",
    "Central Park Stage",
    "Harbor Convention Center",
]


class MockSource(EventSource):
    """Synthetic source used when no real API keys are configured."""

    name = "mock"

    def __init__(self, per_type: int = 4) -> None:
        self.per_type = per_type

    def is_configured(self) -> bool:
        return True

    def fetch(
        self,
        city: City,
        window: DateRange,
        event_types: list[EventType],
    ) -> list[Event]:
        types = event_types or [EventType(slug="general", name="General")]
        span = max((window.end - window.start).total_seconds(), 3600)
        events: list[Event] = []
        idx = 0
        total = len(types) * self.per_type
        for et in types:
            for n in range(self.per_type):
                # Spread events evenly across the window.
                offset = span * (idx + 1) / (total + 1)
                start = window.start + timedelta(seconds=offset)
                venue = _SAMPLE_VENUES[idx % len(_SAMPLE_VENUES)]
                events.append(
                    Event(
                        source=self.name,
                        source_event_id=f"mock-{city.slug}-{et.slug}-{n}",
                        title=f"{et.name} #{n + 1} in {city.name}",
                        description=f"A sample {et.name.lower()} event for {city.name}.",
                        event_type=et.slug,
                        start=start,
                        end=start + timedelta(hours=2),
                        venue=venue,
                        city_slug=city.slug,
                        rank_score=float(total - idx),  # earlier = higher
                    )
                )
                idx += 1
        return events
