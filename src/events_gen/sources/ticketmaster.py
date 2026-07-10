"""Ticketmaster Discovery API event source.

Docs: https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
Queries by geo-point (city lat/long) + date range, mapping our event-type slugs
to Ticketmaster ``classificationName`` values via ``event_types.yaml``.
"""

from __future__ import annotations

import logging
from typing import Any

from ..models import City, Event, EventType
from ..settings import Settings, get_settings
from ..timewindow import DateRange
from .cache import ResponseCache
from .http_api import ApiEventSource

logger = logging.getLogger(__name__)

_TM_DATE_FMT = "%Y-%m-%dT%H:%M:%SZ"

# Map Ticketmaster classification "segment" names to our event-type slugs.
_SEGMENT_TO_SLUG: dict[str, str] = {
    "music": "music",
    "sports": "sports",
    "arts & theatre": "arts",
    "arts & theater": "arts",
    "film": "arts",
    "miscellaneous": "family",
}


def _classify(item: dict[str, Any]) -> str | None:
    """Extract an event-type slug from a Ticketmaster classification segment."""
    classifications = item.get("classifications")
    if not classifications:
        return None
    segment = classifications[0].get("segment", {})
    name = (segment.get("name") or "").strip().lower()
    return _SEGMENT_TO_SLUG.get(name)


class TicketmasterSource(ApiEventSource):
    name = "ticketmaster"

    def __init__(
        self,
        settings: Settings | None = None,
        cache: ResponseCache | None = None,
        page_size: int = 50,
    ) -> None:
        super().__init__(cache=cache)
        self._settings = settings or get_settings()
        self.page_size = page_size

    @property
    def base_url(self) -> str:
        return "https://app.ticketmaster.com/discovery/v2/events.json"

    def is_configured(self) -> bool:
        return bool(self._settings.ticketmaster_api_key)

    def build_params(
        self,
        city: City,
        window: DateRange,
        event_types: list[EventType],
        page: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "apikey": self._settings.ticketmaster_api_key,
            "latlong": f"{city.latitude},{city.longitude}",
            "radius": 50,
            "unit": "km",
            "startDateTime": window.start.strftime(_TM_DATE_FMT),
            "endDateTime": window.end.strftime(_TM_DATE_FMT),
            "size": self.page_size,
            "page": page,
            "sort": "date,asc",
        }
        classifications = self._classifications(event_types)
        if classifications:
            params["classificationName"] = ",".join(classifications)
        return params

    def _classifications(self, event_types: list[EventType]) -> list[str]:
        names: list[str] = []
        for et in event_types:
            names.extend(et.source_categories.get(self.name, []))
        return sorted(set(names))

    def has_more(self, payload: Any, page: int, parsed_count: int) -> bool:
        page_info = payload.get("page", {}) if isinstance(payload, dict) else {}
        total_pages = int(page_info.get("totalPages", 0))
        return page + 1 < total_pages

    def parse(self, payload: Any, city: City) -> list[Event]:
        if not isinstance(payload, dict):
            return []
        raw_events = payload.get("_embedded", {}).get("events", [])
        events: list[Event] = []
        for item in raw_events:
            try:
                event = self._parse_one(item, city)
            except Exception:  # noqa: BLE001 - skip a single malformed record
                logger.warning("%s: skipping unparseable event", self.name, exc_info=True)
                continue
            if event is not None:
                events.append(event)
        return events

    def _parse_one(self, item: dict[str, Any], city: City) -> Event | None:
        dates = item.get("dates", {}).get("start", {})
        start = dates.get("dateTime")
        if not start:
            # All-day events may only have a localDate; fall back to midnight.
            local_date = dates.get("localDate")
            if not local_date:
                return None
            start = f"{local_date}T00:00:00Z"

        venue = None
        embedded = item.get("_embedded", {})
        venues = embedded.get("venues") if isinstance(embedded, dict) else None
        if venues:
            venue = venues[0].get("name")

        price_min = price_max = currency = None
        ranges = item.get("priceRanges")
        if ranges:
            price_min = ranges[0].get("min")
            price_max = ranges[0].get("max")
            currency = ranges[0].get("currency")

        image_url = None
        images = item.get("images")
        if images:
            image_url = images[0].get("url")

        # Extract popularity signal: attractions[0].upcomingEvents._total
        rank_score = 0.0
        attractions = embedded.get("attractions") if isinstance(embedded, dict) else None
        if attractions and isinstance(attractions, list):
            upcoming = attractions[0].get("upcomingEvents", {})
            if isinstance(upcoming, dict):
                total = int(upcoming.get("_total", 0) or 0)
                rank_score = min(total / 100.0, 10.0)

        return Event(
            source=self.name,
            source_event_id=item.get("id"),
            title=item.get("name", "Untitled event"),
            event_type=_classify(item),
            start=start,  # pydantic parses ISO-8601 into datetime
            end=None,
            venue=venue,
            city_slug=city.slug,
            url=item.get("url"),
            image_url=image_url,
            price_min=price_min,
            price_max=price_max,
            currency=currency,
            rank_score=rank_score,
        )
