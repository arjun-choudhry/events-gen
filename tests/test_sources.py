"""Tests for individual event sources (parsing, config gating, HTTP mocking)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from events_gen.models import City, EventType
from events_gen.settings import Settings
from events_gen.sources.cache import ResponseCache
from events_gen.sources.eventbrite import EventbriteSource
from events_gen.sources.mock import MockSource
from events_gen.sources.scraper import ScraperSource
from events_gen.sources.ticketmaster import TicketmasterSource
from events_gen.timewindow import DateRange

CITY = City(
    slug="tokyo",
    name="Tokyo",
    country="Japan",
    country_code="JP",
    timezone="Asia/Tokyo",
    latitude=35.68,
    longitude=139.65,
)
WINDOW = DateRange(
    start=datetime(2026, 7, 6, tzinfo=UTC),
    end=datetime(2026, 7, 13, tzinfo=UTC),
)
MUSIC = EventType(slug="music", name="Music", source_categories={"ticketmaster": ["Music"]})


# ── config gating ──


def test_ticketmaster_not_configured_without_key() -> None:
    s = TicketmasterSource(settings=Settings(_env_file=None))  # type: ignore[call-arg]
    assert s.is_configured() is False
    # safe_fetch returns [] for unconfigured sources
    assert s.safe_fetch(CITY, WINDOW, [MUSIC]) == []


def test_ticketmaster_configured_with_key() -> None:
    s = TicketmasterSource(settings=Settings(_env_file=None, TICKETMASTER_API_KEY="k"))  # type: ignore[call-arg]
    assert s.is_configured() is True


# ── mock source ──


def test_mock_source_is_deterministic() -> None:
    s = MockSource(per_type=3)
    a = s.fetch(CITY, WINDOW, [MUSIC])
    b = s.fetch(CITY, WINDOW, [MUSIC])
    assert len(a) == 3
    assert [e.title for e in a] == [e.title for e in b]
    assert all(WINDOW.contains(e.start) for e in a)


# ── ticketmaster parsing (mocked HTTP) ──

_TM_PAYLOAD = {
    "_embedded": {
        "events": [
            {
                "id": "tm1",
                "name": "Big Concert",
                "url": "https://tm.example/e/tm1",
                "dates": {"start": {"dateTime": "2026-07-08T19:00:00Z"}},
                "priceRanges": [{"min": 50.0, "max": 120.0, "currency": "USD"}],
                "images": [{"url": "https://tm.example/img.jpg"}],
                "_embedded": {"venues": [{"name": "Dome"}]},
            },
            {
                "id": "tm2",
                "name": "All Day Fair",
                "dates": {"start": {"localDate": "2026-07-09"}},
            },
        ]
    },
    "page": {"totalPages": 1},
}


def _mock_source_with_transport(source_cls, handler, **kwargs):  # type: ignore[no-untyped-def]
    """Build a source whose _request uses a mocked httpx transport."""
    source = source_cls(**kwargs)
    transport = httpx.MockTransport(handler)

    def fetch_via_mock(city, window, event_types):  # type: ignore[no-untyped-def]
        events = []
        with httpx.Client(transport=transport) as client:
            for page in range(source.max_pages):
                params = source.build_params(city, window, event_types, page)
                payload = source._request(client, params)
                parsed = source.parse(payload, city)
                events.extend(parsed)
                if not source.has_more(payload, page, len(parsed)):
                    break
        return events

    source.fetch = fetch_via_mock  # type: ignore[method-assign]
    return source


def test_ticketmaster_parse() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_TM_PAYLOAD)

    s = _mock_source_with_transport(
        TicketmasterSource,
        handler,
        settings=Settings(_env_file=None, TICKETMASTER_API_KEY="k"),  # type: ignore[call-arg]
    )
    events = s.fetch(CITY, WINDOW, [MUSIC])
    assert len(events) == 2
    concert = events[0]
    assert concert.title == "Big Concert"
    assert concert.venue == "Dome"
    assert concert.price_min == 50.0
    assert concert.currency == "USD"
    assert str(concert.image_url) == "https://tm.example/img.jpg"
    # All-day event got a midnight timestamp.
    assert events[1].start.hour == 0


def test_ticketmaster_skips_malformed_record() -> None:
    payload = {"_embedded": {"events": [{"id": "x"}]}, "page": {"totalPages": 1}}  # no name/date

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    s = _mock_source_with_transport(
        TicketmasterSource,
        handler,
        settings=Settings(_env_file=None, TICKETMASTER_API_KEY="k"),  # type: ignore[call-arg]
    )
    assert s.fetch(CITY, WINDOW, [MUSIC]) == []


# ── eventbrite parsing ──


def test_eventbrite_parse() -> None:
    payload = {
        "events": [
            {
                "id": "eb1",
                "name": {"text": "Indie Show"},
                "summary": "Great night",
                "start": {"utc": "2026-07-10T20:00:00Z"},
                "url": "https://eb.example/eb1",
                "venue": {"name": "The Club"},
            }
        ],
        "pagination": {"has_more_items": False},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    s = _mock_source_with_transport(
        EventbriteSource,
        handler,
        settings=Settings(_env_file=None, EVENTBRITE_API_TOKEN="t"),  # type: ignore[call-arg]
    )
    events = s.fetch(CITY, WINDOW, [MUSIC])
    assert len(events) == 1
    assert events[0].title == "Indie Show"
    assert events[0].venue == "The Club"
    assert events[0].description == "Great night"


# ── cache ──


def test_cache_roundtrip_and_ttl(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path, default_ttl=3600)
    params = {"a": 1, "b": "x"}
    assert cache.get("src", params) is None
    cache.set("src", params, {"hello": "world"})
    assert cache.get("src", params) == {"hello": "world"}
    # Param order does not matter.
    assert cache.get("src", {"b": "x", "a": 1}) == {"hello": "world"}


def test_cache_expiry(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path, default_ttl=3600)
    cache.set("src", {"k": 1}, {"v": 1}, ttl=-1)  # already expired
    assert cache.get("src", {"k": 1}) is None


def test_cache_clear(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    cache.set("src", {"k": 1}, {"v": 1})
    cache.set("src", {"k": 2}, {"v": 2})
    assert cache.clear() == 2
    assert cache.get("src", {"k": 1}) is None


# ── scraper (JSON-LD parsing) ──

_JSONLD_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event","name":"Jazz Fest",
 "startDate":"2026-07-09T18:00:00Z","location":{"name":"Riverside"},
 "url":"https://city.example/jazz"}
</script>
</head><body>hi</body></html>
"""


def test_scraper_parses_jsonld_event() -> None:
    s = ScraperSource()
    events = s._parse_jsonld(_JSONLD_HTML, CITY)
    assert len(events) == 1
    assert events[0].title == "Jazz Fest"
    assert events[0].venue == "Riverside"


def test_scraper_handles_graph_and_lists() -> None:
    html = """
    <script type="application/ld+json">
    {"@graph":[
      {"@type":"WebSite","name":"ignore me"},
      {"@type":"Event","name":"Show A","startDate":"2026-07-08"},
      {"@type":["Thing","MusicEvent"],"name":"Show B","startDate":"2026-07-09"}
    ]}
    </script>
    """
    events = ScraperSource()._parse_jsonld(html, CITY)
    titles = {e.title for e in events}
    assert titles == {"Show A", "Show B"}


def test_scraper_no_url_returns_empty() -> None:
    # Default City has no scrape_url attribute -> inert.
    assert ScraperSource().fetch(CITY, WINDOW, []) == []
