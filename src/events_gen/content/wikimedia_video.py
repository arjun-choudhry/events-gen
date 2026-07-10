"""Wikimedia Commons video fetcher (CC-licensed venue/performer footage).

Unlike stock libraries, Commons hosts real footage of famous venues and public
figures (e.g. Madison Square Garden), all Creative-Commons licensed. Coverage is
spotty — only well-known subjects have video — so this is tried first and the
caller falls back to generic stock when it returns nothing.

No API key needed; the API requires a descriptive User-Agent.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_USER_AGENT = "events-gen/0.1 (venue/performer video lookup)"


# Common words that appear in both venue names and unrelated videos — matching on
# these alone (e.g. "blue", "park", "hall") produces false positives.
_STOPWORDS = frozenset(
    {
        "the", "and", "live", "show", "night", "club", "bar", "hall", "center", "centre",
        "arena", "theatre", "theater", "stadium", "park", "blue", "red", "green", "city",
        "house", "room", "stage", "music", "festival", "concert", "event", "grand",
    }
)


def _is_relevant(title: str, query: str) -> bool:
    """True if the file title plausibly matches the query (guards against Commons'
    loose full-text search returning wildly unrelated videos).

    Relevance requires either a distinctive long word (≥6 chars, e.g. "Madison"),
    or at least two significant (non-stopword, ≥4-char) query words appearing in
    the title. This keeps genuine venue/performer hits while dropping noise like a
    "Big Blue crane collapse" video matching a query that merely contains "blue".
    """
    title_l = title.lower()
    words = [w for w in query.lower().replace(",", " ").split() if len(w) >= 4]
    significant = [w for w in words if w not in _STOPWORDS]
    distinctive_hit = any(len(w) >= 6 and w in title_l for w in significant)
    significant_hits = sum(1 for w in significant if w in title_l)
    return distinctive_hit or significant_hits >= 2


def wikimedia_clip_urls(client: httpx.Client, query: str) -> list[str]:
    """Return CC-licensed video URLs from Commons matching ``query`` (may be empty)."""
    try:
        resp = client.get(
            _COMMONS_API,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:video {query}",
                "gsrnamespace": "6",  # File namespace
                "gsrlimit": "10",
                "prop": "imageinfo",
                "iiprop": "url|mime",
            },
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        pages = (resp.json().get("query") or {}).get("pages", {})
        urls: list[str] = []
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            mime = info.get("mime", "")
            url = info.get("url")
            # Commons serves .ogv video as "application/ogg", not "video/ogg".
            is_video = mime.startswith("video/") or mime == "application/ogg"
            # Only keep results whose title actually relates to the query — Commons'
            # search will otherwise return unrelated videos for niche queries.
            if url and is_video and _is_relevant(str(page.get("title", "")), query):
                urls.append(str(url))
        return urls
    except Exception:  # noqa: BLE001 - best-effort
        logger.warning("Wikimedia search failed for %r", query, exc_info=True)
        return []


def fetch_wikimedia_clip(
    queries: Iterable[str],
    out_dir: Path,
    duration: float,
    event_id: str,
    *,
    exclude_urls: Iterable[str] = (),
    client: httpx.Client,
) -> tuple[Path, str] | None:
    """Fetch a CC-licensed venue/performer clip. Returns ``(path, url)`` or None.

    Tries each query (e.g. venue name, then event title); returns the first
    downloadable video not already in ``exclude_urls``.
    """
    from .video_clips import _download_and_trim

    excluded = set(exclude_urls)
    for query in queries:
        if not query:
            continue
        for url in wikimedia_clip_urls(client, query):
            if url in excluded:
                continue
            path = _download_and_trim(client, url, out_dir, event_id, duration)
            if path is not None:
                logger.info("wikimedia clip for event %s from query %r", event_id, query)
                return (path, url)
    return None
