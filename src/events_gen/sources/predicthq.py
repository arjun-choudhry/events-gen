"""PredictHQ Events API event source.

Docs: https://docs.predicthq.com/api/events
Queries by geo-point (city lat/long within an offset radius) + date range.
Auth is via Bearer token in the Authorization header.

``rank_score`` is derived from PredictHQ's ``rank`` field (0-100 int),
divided by 10 to fit our 0-10 internal scale.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from ..models import City, Event, EventType
from ..settings import Settings, get_settings
from ..timewindow import DateRange
from .cache import ResponseCache
from .http_api import ApiEventSource, _is_transient

logger = logging.getLogger(__name__)

_PHQ_DATE_FMT = "%Y-%m-%dT%H:%M:%S"

# Map PredictHQ categories to our event-type slugs.
_CATEGORY_MAP: dict[str, str] = {
    "concerts": "music",
    "performing-arts": "arts",
    "sports": "sports",
    "community": "family",
    "festivals": "music",
    "food-beverage": "family",
    "academic": "family",
}

# Default PredictHQ categories to query (concert + arts + sports + community events).
_DEFAULT_CATEGORIES = "concerts,performing-arts,sports,community,festivals,food-beverage"


class PredictHQSource(ApiEventSource):
    name = "predicthq"

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
        return "https://api.predicthq.com/v1/events/"

    def is_configured(self) -> bool:
        return bool(self._settings.predicthq_api_token)

    def build_params(
        self,
        city: City,
        window: DateRange,
        event_types: list[EventType],
        page: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "location_around.origin": f"{city.latitude},{city.longitude}",
            "location_around.offset": "50km",
            "start.gte": window.start.strftime(_PHQ_DATE_FMT),
            "start.lte": window.end.strftime(_PHQ_DATE_FMT),
            "limit": self.page_size,
            "offset": page * self.page_size,
            "sort": "rank",
            "state": "active",
        }
        categories = self._categories(event_types)
        if categories:
            params["category"] = categories
        else:
            params["category"] = _DEFAULT_CATEGORIES
        return params

    def _categories(self, event_types: list[EventType]) -> str:
        """Collect PredictHQ category names from our event types."""
        cats: list[str] = []
        for et in event_types:
            cats.extend(et.source_categories.get(self.name, []))
        return ",".join(sorted(set(cats))) if cats else ""

    def has_more(self, payload: Any, page: int, parsed_count: int) -> bool:
        if not isinstance(payload, dict):
            return False
        # PredictHQ returns a "next" URL when more results are available.
        return bool(payload.get("next"))

    def parse(self, payload: Any, city: City) -> list[Event]:
        if not isinstance(payload, dict):
            return []
        raw_events = payload.get("results", [])
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
        start = item.get("start")
        if not start:
            return None

        end = item.get("end")

        # PredictHQ rank is 0-100 (predicted attendance rank). Also boost with
        # phq_attendance (actual estimated headcount) when available.
        rank = int(item.get("rank", 0) or 0)
        phq_attendance = int(item.get("phq_attendance", 0) or 0)
        # Base: rank / 12 (up to ~8.3). Attendance bonus: up to +2 (10k+ = max).
        rank_score = min(rank / 12.0 + min(phq_attendance / 5000.0, 2.0), 10.0)

        category = item.get("category", "")
        event_type = _CATEGORY_MAP.get(category)

        # Venue from entities.
        venue = None
        entities = item.get("entities", [])
        if entities and isinstance(entities, list):
            for entity in entities:
                if isinstance(entity, dict) and entity.get("type") == "venue":
                    venue = entity.get("name")
                    break

        title = item.get("title") or "Untitled event"
        description = item.get("description")

        return Event(
            source=self.name,
            source_event_id=item.get("id"),
            title=title,
            description=description,
            event_type=event_type,
            start=start,
            end=end,
            venue=venue,
            city_slug=city.slug,
            url=None,  # PredictHQ doesn't provide event URLs directly
            image_url=None,
            rank_score=rank_score,
        )

    # ── Override the HTTP request to add the Authorization header ──

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=8),
        reraise=True,
    )
    def _request(self, client: httpx.Client, params: dict[str, Any]) -> Any:
        """Override to inject the Bearer token as a header (not a query param)."""
        headers = {"Authorization": f"Bearer {self._settings.predicthq_api_token}"}
        response = client.get(self.base_url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
