"""Shared plumbing for HTTP/JSON API event sources.

Provides a base class that wraps httpx with tenacity retries (exponential
backoff on transient errors) and the :class:`ResponseCache`. Concrete sources
implement :meth:`build_params` / :meth:`parse` and get caching + resilience for
free.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from ..models import City, Event, EventType
from ..timewindow import DateRange
from .base import EventSource
from .cache import ResponseCache

logger = logging.getLogger(__name__)


def _is_transient(exc: BaseException) -> bool:
    """Retry transport errors and 5xx/429 — never other 4xx (bad key/params/endpoint)."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or 500 <= code < 600
    return False


class ApiEventSource(EventSource):
    """Base for JSON API sources with caching + retry + pagination hooks."""

    #: Requests time out after this many seconds.
    timeout: float = 15.0
    #: Max pages to walk per query (guards against runaway pagination).
    max_pages: int = 5

    def __init__(self, cache: ResponseCache | None = None) -> None:
        self._cache = cache

    # ── to implement in subclasses ──
    @property
    @abstractmethod
    def base_url(self) -> str:
        """Fully-qualified endpoint URL."""

    @abstractmethod
    def build_params(
        self,
        city: City,
        window: DateRange,
        event_types: list[EventType],
        page: int,
    ) -> dict[str, Any]:
        """Build query params for a given page (0-indexed)."""

    @abstractmethod
    def parse(self, payload: Any, city: City) -> list[Event]:
        """Turn one page's JSON payload into normalized events."""

    def has_more(self, payload: Any, page: int, parsed_count: int) -> bool:
        """Return True if another page should be fetched. Default: stop when empty."""
        return parsed_count > 0

    # ── shared fetch loop ──
    def fetch(
        self,
        city: City,
        window: DateRange,
        event_types: list[EventType],
    ) -> list[Event]:
        events: list[Event] = []
        with httpx.Client(timeout=self.timeout) as client:
            for page in range(self.max_pages):
                params = self.build_params(city, window, event_types, page)
                payload = self._get(client, params)
                if payload is None:
                    break
                parsed = self.parse(payload, city)
                events.extend(parsed)
                if not self.has_more(payload, page, len(parsed)):
                    break
        return events

    def _get(self, client: httpx.Client, params: dict[str, Any]) -> Any | None:
        if self._cache is not None:
            cached = self._cache.get(self.name, params)
            if cached is not None:
                logger.debug("cache hit for %s", self.name)
                return cached
        payload = self._request(client, params)
        if self._cache is not None and payload is not None:
            self._cache.set(self.name, params, payload)
        return payload

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=8),
        reraise=True,
    )
    def _request(self, client: httpx.Client, params: dict[str, Any]) -> Any:
        response = client.get(self.base_url, params=params)
        response.raise_for_status()
        return response.json()
