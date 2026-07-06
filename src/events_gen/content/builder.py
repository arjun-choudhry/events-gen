"""Assemble a complete :class:`PostContent` bundle for a post.

Ties together the three content sub-systems — captions (Claude/template),
background image (provider/upload/default), and music (default/upload) — into a
single ``PostContent`` the renderer (M4) consumes. Keeps the override rules in
one place so the pipeline and UI call a single function.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..models import City, Event, EventType, PostContent
from ..settings import Settings, get_settings
from .captions import generate_captions
from .images import resolve_background
from .music import resolve_music

logger = logging.getLogger(__name__)

# Default background size — portrait 9:16 (Reel/Short), the primary target.
DEFAULT_SIZE = (1080, 1920)


def build_content(
    city: City,
    events: list[Event],
    event_types: list[EventType],
    window: str,
    *,
    draft_id: str,
    image_upload: Path | None = None,
    music_upload: Path | None = None,
    size: tuple[int, int] = DEFAULT_SIZE,
    settings: Settings | None = None,
) -> PostContent:
    """Produce captions + background + music for ``events`` in ``city``.

    ``draft_id`` scopes the generated background file under the output dir so
    concurrent drafts don't collide.
    """
    settings = settings or get_settings()
    settings.ensure_dirs()

    captions = generate_captions(city, events, window, settings=settings)

    bg_path = settings.output_dir / draft_id / "background.jpg"
    background = resolve_background(
        city, bg_path, size, upload_path=image_upload, settings=settings
    )

    music = resolve_music(city, events, event_types, upload_path=music_upload, settings=settings)

    return PostContent(
        title=captions.title,
        caption=captions.caption,
        hashtags=captions.hashtags,
        background_image_path=str(background),
        music_path=str(music) if music else None,
    )
