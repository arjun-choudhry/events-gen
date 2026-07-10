"""Keyless royalty-free music via the Openverse audio API.

Openverse (the same aggregator we already use for images) indexes Creative-Commons
audio from **multiple providers** (Jamendo, Freesound, …), so it widens the music
pool well beyond a single source — and needs **no API key**. We search by the
event's vibe (genre/tag terms), randomly pick among the fresh matches for variety,
and download the track. All failures degrade to ``None`` so music stays optional.

Note: some Openverse audio results are sound-effects/loops rather than full music;
we bias toward longer results (≥30s) to avoid picking a stinger by mistake.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Iterable
from pathlib import Path

import httpx

from ..settings import Settings, get_settings

logger = logging.getLogger(__name__)

_AUDIO_SEARCH = "https://api.openverse.org/v1/audio/"
_USER_AGENT = "events-gen/0.1 (music lookup)"
_PICK_POOL = 15
_MIN_DURATION_MS = 30_000  # skip short SFX/loops; we want actual music beds

# Vibe search terms per event type (Openverse matches these against title/tags).
_MOOD_QUERIES: dict[str, list[str]] = {
    "music": ["energetic electronic", "upbeat pop", "rock energetic"],
    "nightlife": ["electronic dance", "house music", "club energetic"],
    "sports": ["epic energetic", "powerful rock", "sport upbeat"],
    "festivals": ["upbeat festival", "happy electronic", "celebration"],
    "arts": ["ambient cinematic", "calm instrumental", "classical"],
    "food": ["jazz lounge", "acoustic chill", "happy acoustic"],
    "tech": ["electronic corporate", "futuristic ambient", "inspiring"],
    "family": ["happy upbeat", "fun acoustic", "positive"],
}
_DEFAULT_QUERIES = ["upbeat energetic", "happy instrumental", "electronic"]


def _queries(event_type: str | None) -> list[str]:
    return _MOOD_QUERIES.get((event_type or "").lower(), _DEFAULT_QUERIES)


class OpenverseTrack:
    """A resolved Openverse track: its id and the local cached mp3 path."""

    def __init__(self, track_id: str, path: Path, name: str) -> None:
        self.track_id = track_id
        self.path = path
        self.name = name


def _download_url(entry: dict[str, object]) -> str | None:
    """Best downloadable audio URL for a result (prefer a direct file over the page)."""
    # Openverse gives an alt file list; the top-level ``url`` is the source file.
    alt_files = entry.get("alt_files")
    if isinstance(alt_files, list):
        for alt in alt_files:
            if isinstance(alt, dict) and alt.get("url"):
                return str(alt["url"])
    url = entry.get("url")
    return str(url) if url else None


def fetch_track(
    out_dir: Path,
    *,
    event_type: str | None = None,
    exclude_ids: Iterable[str] = (),
    client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> OpenverseTrack | None:
    """Download a fresh, vibe-matched CC track from Openverse (keyless).

    Randomly picks among the fresh top matches for variety. Returns an
    :class:`OpenverseTrack` or ``None`` on any failure / no fresh result.
    """
    settings = settings or get_settings()
    excluded = set(exclude_ids)
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": _USER_AGENT})
    try:
        results: list[dict[str, object]] = []
        for query in _queries(event_type):
            resp = client.get(_AUDIO_SEARCH, params={"q": query, "page_size": "20"})
            resp.raise_for_status()
            results.extend(resp.json().get("results", []))
            if len(results) >= _PICK_POOL:
                break

        def _long_enough(entry: dict[str, object]) -> bool:
            dur = entry.get("duration")
            return isinstance(dur, int | float) and dur >= _MIN_DURATION_MS

        fresh = [
            r
            for r in results
            if r.get("id")
            and _download_url(r)
            and f"openverse:{r['id']}" not in excluded
            and _long_enough(r)
        ]
        if not fresh:
            logger.info("no fresh Openverse audio for vibe %s", event_type)
            return None

        entry = random.choice(fresh[:_PICK_POOL])
        track_id = str(entry["id"])
        url = _download_url(entry)
        if url is None:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"openverse_{track_id}.mp3"
        resp = client.get(url, follow_redirects=True)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        name = str(entry.get("title", track_id))
        logger.info("auto-selected Openverse track %s (%s) for vibe %s", track_id, name, event_type)
        return OpenverseTrack(track_id, out_path, name)
    except Exception:  # noqa: BLE001 - auto-music is best-effort
        logger.warning("Openverse auto-music failed", exc_info=True)
        return None
    finally:
        if owns_client:
            client.close()
