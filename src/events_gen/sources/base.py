"""The :class:`EventSource` interface all event providers implement.

A source turns a query (city + date range + event types) into a list of
normalized :class:`~events_gen.models.Event` objects. Sources that need
credentials report readiness via :meth:`is_configured`; unconfigured sources
are skipped by the aggregator rather than erroring.

:meth:`safe_fetch` wraps :meth:`fetch` so a single misbehaving source (network
error, bad payload) degrades to an empty result instead of breaking the whole
run — the aggregator relies on this for failure isolation.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..models import City, Event, EventType
from ..timewindow import DateRange

logger = logging.getLogger(__name__)


class EventSource(ABC):
    """Abstract base for an event provider (API or scraper)."""

    #: Stable identifier stored on each Event and used in logs/dedupe.
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if this source has what it needs to run (e.g. an API key)."""

    @abstractmethod
    def fetch(
        self,
        city: City,
        window: DateRange,
        event_types: list[EventType],
    ) -> list[Event]:
        """Query the provider and return normalized events.

        May raise; callers should prefer :meth:`safe_fetch`. ``event_types`` is
        the resolved list (empty means "all types").
        """

    def safe_fetch(
        self,
        city: City,
        window: DateRange,
        event_types: list[EventType],
    ) -> list[Event]:
        """Run :meth:`fetch`, isolating failures to an empty list.

        Skips unconfigured sources up front and logs (never re-raises) on error.
        """
        if not self.is_configured():
            logger.info("source %s skipped: not configured", self.name)
            return []
        try:
            events = self.fetch(city, window, event_types)
            logger.info("source %s returned %d events", self.name, len(events))
            return events
        except Exception:  # noqa: BLE001 - deliberate isolation boundary
            logger.exception("source %s failed; returning no events", self.name)
            return []
