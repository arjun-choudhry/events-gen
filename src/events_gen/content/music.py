"""Music track selection for a post.

Implements the R6 override rule: use a user-uploaded track if given, else the
default track for the dominant event type (from ``event_types.yaml``), else the
city's default track, else nothing (the renderer produces a silent video).

Only paths that actually exist on disk are returned — the default-music assets
are user-supplied (royalty-free), so a configured-but-missing default degrades
gracefully to no music rather than erroring.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from ..models import City, Event, EventType
from ..settings import Settings, get_settings

logger = logging.getLogger(__name__)


def _dominant_type(events: list[Event]) -> str | None:
    """Return the most common event_type slug among ``events`` (if any)."""
    counts = Counter(e.event_type for e in events if e.event_type)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def resolve_music(
    city: City,
    events: list[Event],
    event_types: list[EventType],
    *,
    upload_path: Path | None = None,
    use_defaults: bool = True,
    settings: Settings | None = None,
) -> Path | None:
    """Resolve the music track for a post following the R6 override rule.

    Priority: user upload → default track for the dominant event type →
    city default track → None (silent). Returns an existing path or None.

    ``use_defaults`` gates the "smart music" behavior: when False, only an
    explicit upload is honored (no automatic type/city default) — the video is
    silent unless the user provided a track.
    """
    settings = settings or get_settings()

    if upload_path is not None:
        if not upload_path.exists():
            raise FileNotFoundError(f"uploaded music not found: {upload_path}")
        logger.info("using uploaded music %s", upload_path)
        return upload_path

    if not use_defaults:
        logger.info("smart music off and no upload; video will be silent")
        return None

    dominant = _dominant_type(events)
    if dominant:
        et = next((t for t in event_types if t.slug == dominant), None)
        if et and et.default_music:
            track = settings.assets_dir / et.default_music
            if track.exists():
                logger.info("using default music for type %s: %s", dominant, track)
                return track
            logger.info("default music for type %s not found on disk: %s", dominant, track)

    if city.default_music:
        track = settings.assets_dir / city.default_music
        if track.exists():
            logger.info("using city default music %s", track)
            return track

    logger.info("no music resolved; video will be silent")
    return None
