"""Per-event stock video clip fetcher (M16).

Searches Pexels then Pixabay for a short video clip matching the event's
venue/city. Downloads and trims to the card duration. Returns None on failure
so the render falls back to image backgrounds silently.
"""

from __future__ import annotations

import logging
import random
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

import httpx

from ..models import Event
from ..settings import Settings, get_settings

_COVERR_SEARCH = "https://api.coverr.co/videos"
_PEXELS_VIDEO = "https://api.pexels.com/videos/videos/{id}"
_PIXABAY_API = "https://pixabay.com/api/videos/"

# Stock providers we can target individually (order = default search preference).
_STOCK_PROVIDERS = ("pexels", "pixabay", "coverr")

# Recognized direct-video file extensions (a link ending in one is downloaded as-is).
_DIRECT_VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v", ".ogv")


def provider_from_url(url: str) -> str:
    """Best-effort map a downloaded clip URL back to its provider name.

    Falls back to the generic "stock" label when the host isn't recognized.
    """
    host = url.lower()
    if "pexels" in host:
        return "pexels"
    if "pixabay" in host:
        return "pixabay"
    if "coverr" in host:
        return "coverr"
    return "stock"


class ClipLinkError(Exception):
    """Raised when a pasted clip link can't be resolved to a downloadable video."""


def _best_pexels_file(video: dict[str, object]) -> str | None:
    files = video.get("video_files", [])
    if not isinstance(files, list):
        return None
    best = max(files, key=lambda f: f.get("width", 0) * f.get("height", 0), default=None)
    return str(best["link"]) if best and best.get("link") else None


def _best_pixabay_file(hit: dict[str, object]) -> str | None:
    videos = hit.get("videos", {})
    if not isinstance(videos, dict):
        return None
    best = max(
        (v for v in videos.values() if isinstance(v, dict) and v.get("url")),
        key=lambda v: v.get("width", 0) * v.get("height", 0),
        default=None,
    )
    return str(best["url"]) if best else None


def resolve_clip_url(link: str, client: httpx.Client, settings: Settings) -> str:
    """Turn a pasted clip link into a direct, downloadable video URL.

    Accepts either a direct video file URL (``.mp4``/``.webm``/…) — returned as-is —
    or a Pexels / Pixabay / Coverr *page* URL, which is resolved to the highest-
    resolution download link via that provider's API. Raises :class:`ClipLinkError`
    with a human-readable reason on anything unrecognized or unresolvable.

    Only royalty-free / CC stock sources and direct file URLs are supported — pages
    from YouTube / TikTok / Instagram are intentionally rejected (their content is
    copyrighted and would get published posts muted or struck).
    """
    link = link.strip()
    if not link:
        raise ClipLinkError("empty link")
    low = link.lower().split("?")[0]

    # 1. Direct video file — use as-is.
    if low.endswith(_DIRECT_VIDEO_EXTS):
        return link

    # 2. Copyrighted platforms — refuse (protects against Content ID strikes).
    if any(bad in low for bad in ("youtube.com", "youtu.be", "tiktok.com", "instagram.com")):
        raise ClipLinkError(
            "YouTube/TikTok/Instagram links are copyrighted and can't be republished. "
            "Use a royalty-free source (Pexels, Pixabay, Coverr) or a direct video file URL."
        )

    # 3. Stock provider page URLs → resolve to a download link via API.
    try:
        if "pexels.com" in low:
            m = re.search(r"/video/(?:[\w-]*-)?(\d+)", low)
            if not m:
                raise ClipLinkError("couldn't find a Pexels video id in that link")
            if not settings.pexels_api_key:
                raise ClipLinkError("PEXELS_API_KEY not set — can't resolve Pexels page links")
            resp = client.get(
                _PEXELS_VIDEO.format(id=m.group(1)),
                headers={"Authorization": settings.pexels_api_key},
            )
            resp.raise_for_status()
            url = _best_pexels_file(resp.json())
            if not url:
                raise ClipLinkError("no downloadable file on that Pexels video")
            return url

        if "pixabay.com" in low:
            m = re.search(r"-(\d+)/?$", low)
            if not m:
                raise ClipLinkError("couldn't find a Pixabay video id in that link")
            if not settings.pixabay_api_key:
                raise ClipLinkError("PIXABAY_API_KEY not set — can't resolve Pixabay page links")
            resp = client.get(
                _PIXABAY_API, params={"key": settings.pixabay_api_key, "id": m.group(1)}
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            url = _best_pixabay_file(hits[0]) if hits else None
            if not url:
                raise ClipLinkError("no downloadable file on that Pixabay video")
            return url

        if "coverr.co" in low:
            # Coverr page slugs lowercase the (case-sensitive) API id, so it can't
            # be recovered from the URL. Point the user at the page's Download button
            # instead — that direct .mp4 link is handled by the direct-file branch.
            raise ClipLinkError(
                "For Coverr, use the page's Download button and paste that direct "
                ".mp4 link (the page URL can't be resolved automatically)."
            )
    except httpx.HTTPError as exc:
        raise ClipLinkError(f"couldn't reach the provider API: {exc}") from exc

    raise ClipLinkError(
        "unrecognized link — paste a direct video file URL (.mp4/.webm/.mov) or a "
        "Pexels / Pixabay / Coverr page URL."
    )


def provider_available(provider: str, settings: Settings) -> bool:
    """True if the given clip provider is usable (keyless, or its key is set)."""
    if provider == "wikimedia":
        return True  # keyless
    if provider == "pexels":
        return bool(settings.pexels_api_key)
    if provider == "pixabay":
        return bool(settings.pixabay_api_key)
    if provider == "coverr":
        return bool(settings.coverr_api_key)
    return False

logger = logging.getLogger(__name__)

_PEXELS_SEARCH = "https://api.pexels.com/videos/search"
_PIXABAY_SEARCH = "https://pixabay.com/api/videos/"

# Stock libraries index by generic visual *concepts*, not specific venue names.
# Map each event-type slug to a WIDE set of lively search terms (motion/crowds/
# lights) so consecutive posts don't reuse the same clip and the footage feels
# "happening" rather than static scenery.
_TYPE_QUERIES: dict[str, list[str]] = {
    "music": [
        "live concert crowd", "concert stage lights", "music festival crowd",
        "crowd cheering hands up", "dj performing lights", "stage pyrotechnics",
        "festival dancing crowd", "band performing live", "confetti concert",
    ],
    "sports": [
        "stadium crowd cheering", "sports arena action", "athletics competition",
        "fans celebrating stadium", "runners racing", "basketball game action",
        "soccer stadium lights", "crowd wave stadium",
    ],
    "arts": [
        "art gallery people", "art exhibition crowd", "theatre stage performance",
        "ballet dancer motion", "painter creating art", "museum visitors",
        "spotlight stage curtain",
    ],
    "food": [
        "chef cooking flames", "food festival crowd", "restaurant busy night",
        "street food sizzling", "cocktail pouring", "market food stalls",
        "chef plating dish",
    ],
    "tech": [
        "technology conference crowd", "tech startup office", "data screens motion",
        "keynote stage presentation", "coding fast typing", "futuristic city lights",
        "robot demonstration",
    ],
    "nightlife": [
        "nightclub party lights", "night city neon lights", "dj club crowd dancing",
        "cocktail bar night", "people dancing club", "city night timelapse",
        "neon sign glowing",
    ],
    "family": [
        "family fun fair rides", "amusement park motion", "children playing park",
        "ferris wheel spinning", "carnival lights night", "parade crowd",
        "fireworks family watching",
    ],
    "festivals": [
        "festival crowd celebration", "outdoor festival stage", "fireworks display",
        "parade dancers costumes", "confetti celebration", "lantern festival night",
        "crowd hands up festival", "carnival street party",
    ],
}
# Used when an event has no classified type — still lively, motion-forward.
_GENERIC_QUERIES = [
    "city event crowd", "city nightlife neon", "urban lifestyle motion",
    "people celebrating crowd", "city timelapse lights", "downtown busy night",
]

# Terms that signal lively/high-motion footage — used to rank candidates so we
# prefer "happening" clips over static scenery when the API returns both.
_MOTION_HINTS = (
    "crowd", "dancing", "concert", "party", "lights", "celebration", "cheering",
    "action", "motion", "festival", "fireworks", "night", "performing", "timelapse",
)


def _search_queries(event: Event, city_name: str) -> list[str]:
    """Build a query list for the event, *shuffled* for cross-run variety.

    Stock footage of a *specific venue* essentially never exists, so we search by
    the event's type concept (what libraries actually index). The type-specific
    terms are shuffled each call so consecutive posts don't keep hitting the same
    top result; a city-flavored term and generic terms follow as fallbacks.
    """
    type_slug = (event.event_type or "").lower()
    type_terms = list(_TYPE_QUERIES.get(type_slug, []))
    random.shuffle(type_terms)  # vary which concept we try first each run

    queries: list[str] = list(type_terms)
    if type_slug in _TYPE_QUERIES:
        queries.append(f"{city_name} {_TYPE_QUERIES[type_slug][0]}")
    generic = list(_GENERIC_QUERIES)
    random.shuffle(generic)
    queries.extend(generic)

    # De-dupe while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def fetch_wikimedia_only(
    event: Event,
    out_dir: Path,
    duration: float,
    *,
    exclude_urls: Iterable[str] = (),
    client: httpx.Client | None = None,
) -> tuple[Path, str] | None:
    """Fetch only a Wikimedia Commons venue/performer clip (or None)."""
    from .wikimedia_video import fetch_wikimedia_clip

    owns_client = client is None
    client = client or httpx.Client(timeout=120.0)
    try:
        wiki_queries = [q for q in (event.venue, event.title) if q]
        return fetch_wikimedia_clip(
            wiki_queries, out_dir, duration, event.id, exclude_urls=exclude_urls, client=client
        )
    except Exception:  # noqa: BLE001
        logger.warning("wikimedia fetch failed for event %s", event.id, exc_info=True)
        return None
    finally:
        if owns_client:
            client.close()


def fetch_stock_only(
    event: Event,
    city_name: str,
    out_dir: Path,
    duration: float,
    *,
    providers: Iterable[str] | None = None,
    exclude_urls: Iterable[str] = (),
    client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> tuple[Path, str] | None:
    """Fetch a stock clip by event vibe from one or more providers (or None).

    ``providers`` restricts the search to specific sources ("pexels", "pixabay",
    "coverr"); ``None`` means all of them. Queries are shuffled and, within a
    query, a candidate is picked at *random* from the results, so consecutive
    posts get different footage instead of always the single top hit.
    """
    settings = settings or get_settings()
    wanted = set(providers) if providers is not None else set(_STOCK_PROVIDERS)
    excluded = set(exclude_urls)
    owns_client = client is None
    client = client or httpx.Client(timeout=120.0)
    try:
        for query in _search_queries(event, city_name):
            candidates: list[str] = []
            if "pexels" in wanted:
                candidates += _pexels_clip_urls(client, query, settings)
            if "pixabay" in wanted:
                candidates += _pixabay_clip_urls(client, query, settings)
            if "coverr" in wanted:
                candidates += _coverr_clip_urls(client, query, settings)
            fresh = [u for u in candidates if u not in excluded]
            if not fresh:
                continue
            # Randomly pick among this query's fresh candidates for variety.
            random.shuffle(fresh)
            for url in fresh:
                path = _download_and_trim(client, url, out_dir, event.id, duration)
                if path is not None:
                    logger.info("stock clip for event %s from query %r", event.id, query)
                    return (path, url)
        return None
    except Exception:  # noqa: BLE001
        logger.warning("stock fetch failed for event %s", event.id, exc_info=True)
        return None
    finally:
        if owns_client:
            client.close()


def fetch_link_clip(
    link: str,
    out_dir: Path,
    event_id: str,
    duration: float,
    *,
    client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> tuple[Path, str] | None:
    """Resolve a pasted clip ``link`` and download/trim it. Returns ``(path, url)``.

    ``link`` may be a direct video URL or a Pexels/Pixabay/Coverr page URL. Raises
    :class:`ClipLinkError` if the link can't be resolved (so the UI can show why);
    returns ``None`` only if the resolved URL fails to download/transcode.
    """
    settings = settings or get_settings()
    owns_client = client is None
    client = client or httpx.Client(timeout=120.0)
    try:
        url = resolve_clip_url(link, client, settings)  # may raise ClipLinkError
        path = _download_and_trim(client, url, out_dir, event_id, duration)
        return (path, url) if path is not None else None
    finally:
        if owns_client:
            client.close()


def fetch_event_clip(
    event: Event,
    city_name: str,
    out_dir: Path,
    duration: float,
    *,
    exclude_urls: Iterable[str] = (),
    client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> tuple[Path, str] | None:
    """Auto-chain: Wikimedia venue/performer footage → stock video by type.

    Returns ``(clip_path, source_url)`` (for cross-event de-dup), or None.
    """
    settings = settings or get_settings()
    owns_client = client is None
    client = client or httpx.Client(timeout=120.0)
    try:
        wiki = fetch_wikimedia_only(
            event, out_dir, duration, exclude_urls=exclude_urls, client=client
        )
        if wiki is not None:
            return wiki
        return fetch_stock_only(
            event,
            city_name,
            out_dir,
            duration,
            exclude_urls=exclude_urls,
            client=client,
            settings=settings,
        )
    finally:
        if owns_client:
            client.close()


def _pexels_clip_urls(client: httpx.Client, query: str, settings: Settings) -> list[str]:
    """Return candidate clip URLs from Pexels (one best file per result video)."""
    if not settings.pexels_api_key:
        return []
    try:
        resp = client.get(
            _PEXELS_SEARCH,
            params={
                "query": query,
                "per_page": 10,
                "orientation": "portrait",
                "size": "large",  # ask Pexels for 4K-capable results
            },
            headers={"Authorization": settings.pexels_api_key},
        )
        resp.raise_for_status()
        urls: list[str] = []
        for video in resp.json().get("videos", []):
            files = video.get("video_files", [])
            # Pick the highest-resolution file for this video (prefer 4K → 1080p → …),
            # so the downloaded clip is as sharp as the source allows.
            best = max(
                files,
                key=lambda f: (f.get("width", 0) * f.get("height", 0)),
                default=None,
            )
            if best and best.get("link"):
                urls.append(str(best["link"]))
        return urls
    except Exception:  # noqa: BLE001
        logger.warning("Pexels search failed for %r", query, exc_info=True)
        return []


def _pixabay_clip_urls(client: httpx.Client, query: str, settings: Settings) -> list[str]:
    """Return candidate clip URLs from Pixabay (best quality per hit)."""
    if not settings.pixabay_api_key:
        return []
    try:
        resp = client.get(
            _PIXABAY_SEARCH,
            params={"key": settings.pixabay_api_key, "q": query, "per_page": 10},
        )
        resp.raise_for_status()
        urls: list[str] = []
        for hit in resp.json().get("hits", []):
            videos = hit.get("videos", {})
            # Pick the highest-resolution rendition available (Pixabay returns several
            # tiers per hit — "large" is up to 3840px, "medium" ~1920px). Choose by
            # actual pixel area rather than a fixed tier name so we never downgrade.
            best = max(
                (v for v in videos.values() if isinstance(v, dict) and v.get("url")),
                key=lambda v: (v.get("width", 0) * v.get("height", 0)),
                default=None,
            )
            if best:
                urls.append(str(best["url"]))
        return urls
    except Exception:  # noqa: BLE001
        logger.warning("Pixabay search failed for %r", query, exc_info=True)
        return []


def _coverr_clip_urls(client: httpx.Client, query: str, settings: Settings) -> list[str]:
    """Return candidate clip URLs from Coverr (optional; needs COVERR_API_KEY)."""
    if not settings.coverr_api_key:
        return []
    try:
        resp = client.get(
            _COVERR_SEARCH,
            params={
                "query": query,
                "page_size": 10,
                # Coverr only populates each hit's ``urls`` (the mp4 links) when
                # this flag is set; without it every hit's ``urls`` is null.
                "urls": "true",
                "api_key": settings.coverr_api_key,
            },
        )
        resp.raise_for_status()
        urls: list[str] = []
        for hit in resp.json().get("hits", []):
            # Coverr exposes downloadable renditions under ``urls`` (mp4 variants).
            u = hit.get("urls") or {}
            link = u.get("mp4_download") or u.get("mp4") or u.get("mp4_preview")
            if link:
                urls.append(str(link))
        return urls
    except Exception:  # noqa: BLE001
        logger.warning("Coverr search failed for %r", query, exc_info=True)
        return []


def _download_and_trim(
    client: httpx.Client, url: str, out_dir: Path, event_id: str, duration: float
) -> Path | None:
    """Download clip and trim to duration, re-encoding near-losslessly.

    The re-encode only exists to guarantee a valid, seekable mp4 with duration
    metadata; we keep it visually lossless (low CRF + slow preset) so the clip's
    original sharpness/resolution is preserved for the final render.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"clip_raw_{event_id}.mp4"
    trimmed_path = out_dir / f"clip_{event_id}.mp4"
    try:
        # A descriptive User-Agent is required by Wikimedia's upload servers
        # (they 403 requests without one); harmless for Pexels/Pixabay CDNs.
        resp = client.get(
            url,
            follow_redirects=True,
            headers={"User-Agent": "events-gen/0.1 (video clip fetch)"},
        )
        resp.raise_for_status()
        raw_path.write_bytes(resp.content)
        # Trim to duration and re-encode to ensure valid mp4 with duration metadata.
        # CRF 16 + preset slow keeps the source detail (no visible quality loss).
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(raw_path),
                "-ss",
                "0",
                "-t",
                str(duration),
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "16",
                "-an",
                "-pix_fmt",
                "yuv420p",
                str(trimmed_path),
            ],
            capture_output=True,
            check=True,
        )
        raw_path.unlink(missing_ok=True)
        if trimmed_path.exists() and trimmed_path.stat().st_size > 0:
            logger.info("fetched video clip for event %s", event_id)
            return trimmed_path
        return None
    except Exception:  # noqa: BLE001
        logger.warning("clip download/trim failed for %s", url, exc_info=True)
        return None
