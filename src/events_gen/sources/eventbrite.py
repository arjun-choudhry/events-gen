"""Eventbrite API event source.

Docs: https://www.eventbrite.com/platform/api
Uses the destination/search endpoint filtered by location (city lat/long) and
date range. Event-type slugs map to Eventbrite category IDs via
``event_types.yaml``. Auth is a bearer token.

Note: Eventbrite has changed its public search access over time; this source is
written defensively and simply returns nothing (via ``safe_fetch``) if the
endpoint is unavailable for the configured token.
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

_EB_DATE_FMT = "%Y-%m-%dT%H:%M:%SZ"


class EventbriteSource(ApiEventSource):
    name = "eventbrite"

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
        return "https://www.eventbriteapi.com/v3/destination/search/"

    def is_configured(self) -> bool:
        return bool(self._settings.eventbrite_api_token)

    def build_params(
        self,
        city: City,
        window: DateRange,
        event_types: list[EventType],
        page: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "token": self._settings.eventbrite_api_token,
            "location.latitude": city.latitude,
            "location.longitude": city.longitude,
            "location.within": "50km",
            "start_date.range_start": window.start.strftime(_EB_DATE_FMT),
            "start_date.range_end": window.end.strftime(_EB_DATE_FMT),
            "page": page + 1,  # Eventbrite pages are 1-indexed
            "expand": "venue",
        }
        categories = self._categories(event_types)
        if categories:
            params["categories"] = ",".join(categories)
        return params

    def _categories(self, event_types: list[EventType]) -> list[str]:
        ids: list[str] = []
        for et in event_types:
            ids.extend(et.source_categories.get(self.name, []))
        return sorted(set(ids))

    def has_more(self, payload: Any, page: int, parsed_count: int) -> bool:
        pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
        return bool(pagination.get("has_more_items", False))

    def parse(self, payload: Any, city: City) -> list[Event]:
        if not isinstance(payload, dict):
            return []
        raw_events = payload.get("events", [])
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
        start = item.get("start_date") or item.get("start", {}).get("utc")
        if not start:
            return None
        # Normalize a bare "YYYY-MM-DD" to a full timestamp.
        if len(start) == 10:
            start = f"{start}T00:00:00Z"

        end = item.get("end_date") or item.get("end", {}).get("utc")
        if end and len(end) == 10:
            end = f"{end}T00:00:00Z"

        name = item.get("name")
        if isinstance(name, dict):
            name = name.get("text")

        summary = item.get("summary")
        venue = None
        venue_obj = item.get("venue")
        if isinstance(venue_obj, dict):
            venue = venue_obj.get("name")

        return Event(
            source=self.name,
            source_event_id=item.get("id"),
            title=name or "Untitled event",
            description=summary,
            start=start,
            end=end,
            venue=venue,
            city_slug=city.slug,
            url=item.get("url"),
            image_url=(item.get("image") or {}).get("url")
            if isinstance(item.get("image"), dict)
            else None,
        )
