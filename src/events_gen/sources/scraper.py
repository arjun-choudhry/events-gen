"""Generic public-page scraper source (optional, robots.txt-aware).

This source is a *fallback* for public city event pages where APIs fall short.
It is disabled unless a city provides a ``scrape_url`` (not part of the default
config) and the target's ``robots.txt`` permits fetching. It never touches
login-gated content (Facebook, Instagram, etc.) — that would violate ToS and is
explicitly out of scope.

Extraction prefers structured data: JSON-LD ``schema.org/Event`` blocks embedded
in the page, which many venue/city sites publish. This avoids brittle,
site-specific HTML selectors. Sites without JSON-LD simply yield nothing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..models import City, Event, EventType
from ..timewindow import DateRange
from .base import EventSource

logger = logging.getLogger(__name__)

_USER_AGENT = "events-gen/0.1 (+https://example.invalid/events-gen)"


class ScraperSource(EventSource):
    """Scrapes a city's configured public events page for JSON-LD events."""

    name = "scraper"

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def is_configured(self) -> bool:
        # Enabled per-city via a ``scrape_url`` attribute on the City (optional,
        # not in the default schema). Without it, the source is inert.
        return True

    def _scrape_url(self, city: City) -> str | None:
        return getattr(city, "scrape_url", None)

    def _robots_allows(self, client: httpx.Client, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
        parser = RobotFileParser()
        try:
            resp = client.get(robots_url)
            if resp.status_code >= 400:
                # No robots.txt → conventionally allowed.
                return True
            parser.parse(resp.text.splitlines())
        except httpx.HTTPError:
            logger.info("scraper: could not fetch robots.txt for %s; skipping", robots_url)
            return False
        return parser.can_fetch(_USER_AGENT, url)

    def fetch(
        self,
        city: City,
        window: DateRange,
        event_types: list[EventType],
    ) -> list[Event]:
        url = self._scrape_url(city)
        if not url:
            logger.info("scraper: no scrape_url for %s; nothing to do", city.slug)
            return []

        headers = {"User-Agent": _USER_AGENT}
        with httpx.Client(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            if not self._robots_allows(client, url):
                logger.info("scraper: robots.txt disallows %s; skipping", url)
                return []
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text

        events = [e for e in self._parse_jsonld(html, city) if window.contains(e.start)]
        return events

    def _parse_jsonld(self, html: str, city: City) -> list[Event]:
        """Extract schema.org/Event objects from JSON-LD <script> blocks."""
        events: list[Event] = []
        for block in _iter_jsonld_blocks(html):
            for node in _iter_event_nodes(block):
                event = self._node_to_event(node, city)
                if event is not None:
                    events.append(event)
        return events

    def _node_to_event(self, node: dict[str, Any], city: City) -> Event | None:
        raw_start = node.get("startDate")
        name = node.get("name")
        if not raw_start or not name:
            return None
        start = _parse_iso(raw_start)
        if start is None:
            return None
        end = _parse_iso(node.get("endDate"))

        venue = None
        location = node.get("location")
        if isinstance(location, dict):
            venue = location.get("name")
        elif isinstance(location, str):
            venue = location

        try:
            return Event(
                source=self.name,
                title=name,
                description=node.get("description"),
                start=start,
                end=end,
                venue=venue,
                city_slug=city.slug,
                url=node.get("url"),
            )
        except Exception:  # noqa: BLE001 - skip malformed node
            logger.warning("scraper: skipping unparseable JSON-LD event", exc_info=True)
            return None


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 date/datetime string to a datetime, or return None.

    Accepts bare dates ("YYYY-MM-DD", treated as midnight) and trailing 'Z'.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) == 10:
        text = f"{text}T00:00:00+00:00"
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _iter_jsonld_blocks(html: str) -> list[Any]:
    """Return parsed JSON objects from all ld+json script blocks in ``html``."""
    import re

    blocks: list[Any] = []
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        raw = match.group(1).strip()
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return blocks


def _iter_event_nodes(block: Any) -> list[dict[str, Any]]:
    """Yield schema.org Event nodes from a JSON-LD block (handles lists/@graph)."""
    nodes: list[dict[str, Any]] = []

    def _visit(obj: Any) -> None:
        if isinstance(obj, list):
            for item in obj:
                _visit(item)
        elif isinstance(obj, dict):
            if "@graph" in obj:
                _visit(obj["@graph"])
            node_type = obj.get("@type", "")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any("Event" in str(t) for t in types):
                nodes.append(obj)

    _visit(block)
    return nodes
