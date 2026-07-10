"""Auto-select popularity-ranked, royalty-free instrumental music (Jamendo).

This is the *legal* analog to "use a popular chart song": Jamendo serves
Creative-Commons / royalty-free tracks with a popularity ranking, so we can pick
music that trends without the copyright takedowns that commercial (Billboard)
audio would trigger on YouTube/Instagram.

``fetch_track`` returns a locally-cached mp3 path for the top-ranked instrumental
track that is *not* in ``exclude_ids`` (the anti-repetition set), or ``None`` if
Jamendo isn't configured or nothing new is available. Each track's Jamendo id is
returned alongside the path so the caller can record it in the draft's history.

All failures degrade to ``None`` — music is optional, never fatal to a render.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Iterable
from pathlib import Path

import httpx

from ..settings import Settings, get_settings

logger = logging.getLogger(__name__)

_TRACKS_URL = "https://api.jamendo.com/v3.0/tracks"

# Map each event-type slug to Jamendo "fuzzytags" that capture the vibe, so the
# music actually matches the event's energy instead of always defaulting to the
# same globally-popular track. Ordered loosely most→least on-vibe.
_MOOD_TAGS: dict[str, list[str]] = {
    "music": ["energetic", "electronic", "dance", "pop", "rock"],
    "nightlife": ["electronic", "dance", "house", "energetic", "club"],
    "sports": ["energetic", "rock", "epic", "powerful", "sport"],
    "festivals": ["upbeat", "happy", "electronic", "festival", "energetic"],
    "arts": ["ambient", "cinematic", "classical", "calm", "beautiful"],
    "food": ["jazz", "lounge", "acoustic", "happy", "chill"],
    "tech": ["electronic", "corporate", "futuristic", "ambient", "inspiring"],
    "family": ["happy", "upbeat", "acoustic", "fun", "positive"],
}
# Fallback vibe when the event type is unknown/unmapped — still lively, not dull.
_DEFAULT_MOOD = ["upbeat", "happy", "energetic", "pop"]

# How many top candidates to randomly choose among (variety without going obscure).
_PICK_POOL = 15


class JamendoTrack:
    """A resolved track: its Jamendo id and the local cached mp3 path."""

    def __init__(self, track_id: str, path: Path, name: str) -> None:
        self.track_id = track_id
        self.path = path
        self.name = name


def _search(
    client: httpx.Client, client_id: str, limit: int, tags: list[str] | None = None
) -> list[dict[str, str]]:
    """Return up to ``limit`` popular instrumental tracks (id, name, audio url).

    When ``tags`` is given, results are filtered to that vibe via Jamendo's
    ``fuzzytags`` so the music matches the event's energy.
    """
    from ..publish._http import request_with_retry

    params = {
        "client_id": client_id,
        "format": "json",
        "limit": str(limit),
        "order": "popularity_total",  # most popular first
        "vocalinstrumental": "instrumental",
        "audioformat": "mp32",
        "include": "musicinfo",
    }
    if tags:
        params["fuzzytags"] = "+".join(tags)
    resp = request_with_retry(lambda: client.get(_TRACKS_URL, params=params))
    results: list[dict[str, str]] = resp.json().get("results", [])
    return results


def _download(client: httpx.Client, url: str) -> bytes:
    """Download raw bytes from ``url`` with the shared retry policy."""
    from ..publish._http import request_with_retry

    resp = request_with_retry(lambda: client.get(url, follow_redirects=True))
    return resp.content


def _mood_tags(event_type: str | None) -> list[str]:
    """Jamendo fuzzytags for an event type's vibe (default lively set if unmapped)."""
    return _MOOD_TAGS.get((event_type or "").lower(), _DEFAULT_MOOD)


def fetch_track(
    out_dir: Path,
    *,
    event_type: str | None = None,
    exclude_ids: Iterable[str] = (),
    client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> JamendoTrack | None:
    """Download a fresh, vibe-matched instrumental track not in ``exclude_ids``.

    Matches the music to ``event_type`` via Jamendo fuzzytags (e.g. concert →
    energetic/electronic, arts → ambient/cinematic) and **randomly picks** from
    the fresh top candidates so consecutive posts don't reuse the same track.
    Falls back to an untagged popular search if the mood search is too narrow.
    Returns a :class:`JamendoTrack` or ``None`` when Jamendo is unconfigured, the
    API fails, or every candidate was recently used.
    """
    settings = settings or get_settings()
    if not settings.jamendo_client_id:
        logger.info("no JAMENDO_CLIENT_ID; skipping auto-music")
        return None

    excluded = set(exclude_ids)
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        limit = max(30, settings.music_history_size + _PICK_POOL)
        cid = settings.jamendo_client_id
        # Track ids are stored/excluded in the prefixed "jamendo:<id>" form.
        excluded_raw = {e.split(":", 1)[1] for e in excluded if e.startswith("jamendo:")}
        # 1. Vibe-matched candidates first, 2. untagged popular as a widening fallback.
        candidates = _search(client, cid, limit, tags=_mood_tags(event_type))
        if len({str(t.get("id", "")) for t in candidates} - excluded_raw) < 3:
            candidates += _search(client, cid, limit)

        fresh = [
            t
            for t in candidates
            if str(t.get("id", "")) and t.get("audio") and str(t.get("id")) not in excluded_raw
        ]
        if not fresh:
            logger.info("no fresh Jamendo track found (%d candidates all excluded)", len(candidates))
            return None

        # Randomly pick among the freshest top-N for variety (not always #1).
        track = random.choice(fresh[:_PICK_POOL])
        track_id = str(track["id"])
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"jamendo_{track_id}.mp3"
        out_path.write_bytes(_download(client, str(track["audio"])))
        name = str(track.get("name", track_id))
        logger.info("auto-selected Jamendo track %s (%s) for vibe %s", track_id, name, event_type)
        return JamendoTrack(track_id, out_path, name)
    except Exception:  # noqa: BLE001 - auto-music is best-effort
        logger.warning("Jamendo auto-music failed", exc_info=True)
        return None
    finally:
        if owns_client:
            client.close()
