"""Shared HTTP resilience for publisher clients (M8.1).

Wraps an httpx request callable with tenacity retries: exponential backoff on
transient transport errors, 5xx responses, and 429 rate-limits — but *not* on
other 4xx (a bad token or malformed request won't get better by retrying).

Publishers pass their bound ``client.get``/``client.post`` call as a thunk so the
injected-client test seam (MockTransport) keeps working.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _is_retryable(exc: BaseException) -> bool:
    """Retry transport errors and 5xx/429 status errors; reraise other 4xx."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or 500 <= code < 600
    return False


def request_with_retry(call: Callable[[], httpx.Response]) -> httpx.Response:
    """Invoke ``call`` (an httpx request), retrying transient failures.

    ``call`` should perform the request and return the response; this helper
    calls ``raise_for_status`` so status-based retries trigger. Returns the
    successful response, or reraises the last exception after 3 attempts.
    """

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=8),
        reraise=True,
    )
    def _do() -> httpx.Response:
        response = call()
        response.raise_for_status()
        return response

    return _do()
