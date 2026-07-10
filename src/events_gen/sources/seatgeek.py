"""SeatGeek Events API event source.

Docs: https://platform.seatgeek.com/
Queries by geo-point (city lat/long) + date range.  Auth is via ``client_id``
and ``client_secret`` as query parameters.

``rank_score`` is derived from SeatGeek's ``score`` field (0-1 float),
multiplied by 10 to match our 0-10 internal scale.
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

_SG_DATE_FMT = "%Y-%m-%dT%H:%M:%S"


class SeatGeekSource(ApiEventSource):
    name = "seatgeek"

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
        return "https://api.seatgeek.com/2/events"

    def is_configured(self) -> bool:
        return bool(self._settings.seatgeek_client_id and self._settings.seatgeek_client_secret)

    def build_params(
        self,
        city: City,
        window: DateRange,
        event_types: list[EventType],
        page: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "client_id": self._settings.seatgeek_client_id,
            "client_secret": self._settings.seatgeek_client_secret,
            "lat": city.latitude,
            "lon": city.longitude,
            "range": "50mi",
            "per_page": self.page_size,
            "page": page + 1,  # SeatGeek pages are 1-indexed
            "datetime_local.gte": window.start.strftime(_SG_DATE_FMT),
            "datetime_local.lte": window.end.strftime(_SG_DATE_FMT),
            "sort": "score.desc",
        }
        return params

    def has_more(self, payload: Any, page: int, parsed_count: int) -> bool:
        if not isinstance(payload, dict):
            return False
        meta = payload.get("meta", {})
        total = int(meta.get("total", 0))
        per_page = int(meta.get("per_page", self.page_size))
        # page is 0-indexed here; API uses 1-indexed, so (page+1)*per_page
        return (page + 1) * per_page < total

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
        start = item.get("datetime_local") or item.get("datetime_utc")
        if not start:
            return None

        venue = None
        venue_obj = item.get("venue")
        if isinstance(venue_obj, dict):
            venue = venue_obj.get("name")

        image_url = None
        performers = item.get("performers")
        if performers and isinstance(performers, list):
            image_url = performers[0].get("image")

        # SeatGeek score is 0.0-1.0 (demand/quality for THIS event). Also boost
        # with listing_count — more secondary-market listings = higher demand.
        stats = item.get("stats", {}) if isinstance(item.get("stats"), dict) else {}
        score = float(item.get("score", 0) or 0)
        listing_count = int(stats.get("listing_count", 0) or 0)
        # Base: score * 8 (up to 8). Listing bonus: up to +2 (capped at 200 listings).
        rank_score = min(score * 8.0 + min(listing_count / 100.0, 2.0), 10.0)

        # Price range from stats.
        price_min = stats.get("lowest_price")
        price_max = stats.get("highest_price")

        title = item.get("title") or item.get("short_title") or "Untitled event"

        return Event(
            source=self.name,
            source_event_id=str(item.get("id", "")),
            title=title,
            event_type=self._classify(item),
            start=start,
            end=None,
            venue=venue,
            city_slug=city.slug,
            url=item.get("url"),
            image_url=image_url,
            price_min=price_min,
            price_max=price_max,
            currency="USD",
            rank_score=rank_score,
        )

    def _classify(self, item: dict[str, Any]) -> str | None:
        """Map SeatGeek taxonomy type to our event-type slug."""
        taxonomy = item.get("taxonomies")
        if not taxonomy or not isinstance(taxonomy, list):
            sg_type = item.get("type", "")
            return _TYPE_MAP.get(sg_type.lower())
        name = taxonomy[0].get("name", "").lower()
        return _TYPE_MAP.get(name)


_TYPE_MAP: dict[str, str] = {
    "concert": "music",
    "concerts": "music",
    "music_festival": "music",
    "sports": "sports",
    "nfl": "sports",
    "nba": "sports",
    "mlb": "sports",
    "nhl": "sports",
    "mls": "sports",
    "theater": "arts",
    "broadway_tickets_national": "arts",
    "comedy": "arts",
    "dance_performance_tour": "arts",
    "family": "family",
    "cirque_du_soleil": "family",
}
