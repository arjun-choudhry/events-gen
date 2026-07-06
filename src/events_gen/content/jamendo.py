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
from collections.abc import Iterable
from pathlib import Path

import httpx

from ..settings import Settings, get_settings

logger = logging.getLogger(__name__)

_TRACKS_URL = "https://api.jamendo.com/v3.0/tracks"


class JamendoTrack:
    """A resolved track: its Jamendo id and the local cached mp3 path."""

    def __init__(self, track_id: str, path: Path, name: str) -> None:
        self.track_id = track_id
        self.path = path
        self.name = name


def _search(client: httpx.Client, client_id: str, limit: int) -> list[dict[str, str]]:
    """Return up to ``limit`` popular instrumental tracks (id, name, audio url)."""
    from ..publish._http import request_with_retry

    resp = request_with_retry(
        lambda: client.get(
            _TRACKS_URL,
            params={
                "client_id": client_id,
                "format": "json",
                "limit": str(limit),
                "order": "popularity_total",  # most popular first
                "vocalinstrumental": "instrumental",
                "audioformat": "mp32",
                "include": "musicinfo",
            },
        )
    )
    results: list[dict[str, str]] = resp.json().get("results", [])
    return results


def _download(client: httpx.Client, url: str) -> bytes:
    """Download raw bytes from ``url`` with the shared retry policy."""
    from ..publish._http import request_with_retry

    resp = request_with_retry(lambda: client.get(url, follow_redirects=True))
    return resp.content


def fetch_track(
    out_dir: Path,
    *,
    exclude_ids: Iterable[str] = (),
    client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> JamendoTrack | None:
    """Download the top popular instrumental track not in ``exclude_ids``.

    Returns a :class:`JamendoTrack` (id + cached path) or ``None`` when Jamendo
    is unconfigured, the API fails, or every candidate was recently used.
    """
    settings = settings or get_settings()
    if not settings.jamendo_client_id:
        logger.info("no JAMENDO_CLIENT_ID; skipping auto-music")
        return None

    excluded = set(exclude_ids)
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        # Fetch a page larger than the exclusion window so a fresh pick remains.
        limit = max(20, settings.music_history_size + 10)
        candidates = _search(client, settings.jamendo_client_id, limit)
        for track in candidates:
            track_id = str(track.get("id", ""))
            audio_url = track.get("audio")
            if not track_id or not audio_url or track_id in excluded:
                continue

            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"jamendo_{track_id}.mp3"
            out_path.write_bytes(_download(client, audio_url))
            name = str(track.get("name", track_id))
            logger.info("auto-selected Jamendo track %s (%s)", track_id, name)
            return JamendoTrack(track_id, out_path, name)

        logger.info("no fresh Jamendo track found (all %d candidates excluded)", len(candidates))
        return None
    except Exception:  # noqa: BLE001 - auto-music is best-effort
        logger.warning("Jamendo auto-music failed", exc_info=True)
        return None
    finally:
        if owns_client:
            client.close()
