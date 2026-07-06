"""Per-event "smart" background resolution.

For each event, resolve a background image of *where the event is happening*:

1. the event's own promo image (``event.image_url``, provided by Ticketmaster /
   Eventbrite) if present;
2. else an Unsplash search for the venue/city (free API key, but apps stay in
   demo/limited mode until approved, so this may return nothing);
3. else an **Openverse** search — Creative-Commons images, **no API key
   required** — so per-event backgrounds work out of the box;
4. else ``None`` — the caller falls back to the shared city background.

Downloaded/searched images are fetched over HTTP (with the shared retry policy),
cover-fit to the target size, and cached under the draft's output dir. Any
failure degrades to the next tier (and ultimately ``None``) so the render never
breaks.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from ...models import Event
from ...settings import Settings, get_settings

logger = logging.getLogger(__name__)

_UNSPLASH_SEARCH = "https://api.unsplash.com/search/photos"
_OPENVERSE_SEARCH = "https://api.openverse.org/v1/images/"
_USER_AGENT = "events-gen/0.1 (https://github.com/; venue background lookup)"


def _resize_to_target(data: bytes, out_path: Path, size: tuple[int, int]) -> Path:
    """Resize raw image bytes to ``size`` using LANCZOS + blur-fill fallback."""
    from .resize import resize_bytes

    return resize_bytes(data, out_path, size)


def _download(client: httpx.Client, url: str) -> bytes | None:
    from ...publish._http import request_with_retry

    try:
        resp = request_with_retry(lambda: client.get(url, follow_redirects=True))
        return resp.content
    except Exception:  # noqa: BLE001 - any fetch failure degrades to None
        logger.warning("failed to download image %s", url, exc_info=True)
        return None


def _unsplash_url(client: httpx.Client, query: str, access_key: str) -> str | None:
    """Return the first Unsplash photo URL for ``query`` (or None)."""
    from ...publish._http import request_with_retry

    try:
        resp = request_with_retry(
            lambda: client.get(
                _UNSPLASH_SEARCH,
                params={"query": query, "per_page": 1, "orientation": "portrait"},
                headers={"Authorization": f"Client-ID {access_key}"},
            )
        )
        results = resp.json().get("results") or []
        if not results:
            logger.info("no Unsplash results for %r", query)
            return None
        urls = results[0].get("urls", {})
        # Prefer raw with explicit dimensions (sharp, large) over the limited 'regular'.
        raw = urls.get("raw")
        if raw:
            url: str = f"{raw}&w=2160&h=3840&fit=crop&q=80"
        else:
            url = urls.get("full") or urls.get("regular", "")
        return url or None
    except Exception:  # noqa: BLE001
        logger.warning("Unsplash search failed for %r", query, exc_info=True)
        return None


def _openverse_url(client: httpx.Client, query: str) -> str | None:
    """Return the first Openverse image URL for ``query`` (no API key needed)."""
    from ...publish._http import request_with_retry

    try:
        resp = request_with_retry(
            lambda: client.get(
                _OPENVERSE_SEARCH,
                params={"q": query, "page_size": 1},
                headers={"User-Agent": _USER_AGENT},
            )
        )
        results = resp.json().get("results") or []
        if not results:
            logger.info("no Openverse results for %r", query)
            return None
        # Prefer the full image url; fall back to the thumbnail.
        url = results[0].get("url") or results[0].get("thumbnail")
        return str(url) if url else None
    except Exception:  # noqa: BLE001
        logger.warning("Openverse search failed for %r", query, exc_info=True)
        return None


def resolve_event_background(
    event: Event,
    city_name: str,
    out_path: Path,
    size: tuple[int, int],
    *,
    client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> Path | None:
    """Resolve a venue/place background for a single event.

    Priority: event promo image → Unsplash → Openverse (keyless) → None. Returns
    a saved, cover-fit image path, or ``None`` if nothing could be resolved (the
    caller then uses the shared city background).
    """
    settings = settings or get_settings()
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0)
    query = f"{event.venue}, {city_name}" if event.venue else city_name
    try:
        # 1. Event's own promo image.
        if event.image_url:
            data = _download(client, str(event.image_url))
            if data:
                logger.info("using event promo image for %s", event.title)
                return _resize_to_target(data, out_path, size)

        # 2. Unsplash search (if a key is configured and its app is approved).
        if settings.unsplash_access_key:
            photo_url = _unsplash_url(client, query, settings.unsplash_access_key)
            if photo_url:
                data = _download(client, photo_url)
                if data:
                    logger.info("using Unsplash background for %r", query)
                    return _resize_to_target(data, out_path, size)

        # 3. Openverse fallback — keyless, so this works out of the box.
        photo_url = _openverse_url(client, query)
        if photo_url:
            data = _download(client, photo_url)
            if data:
                logger.info("using Openverse background for %r", query)
                return _resize_to_target(data, out_path, size)

        return None
    finally:
        if owns_client:
            client.close()
