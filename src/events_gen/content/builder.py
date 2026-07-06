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
    smart_backgrounds: bool = False,
    smart_music: bool = True,
    auto_music: bool = False,
    music_exclude_ids: list[str] | None = None,
    size: tuple[int, int] = DEFAULT_SIZE,
    settings: Settings | None = None,
) -> PostContent:
    """Produce captions + background + music for ``events`` in ``city``.

    ``draft_id`` scopes the generated background file under the output dir so
    concurrent drafts don't collide. When ``smart_backgrounds`` is on, each event
    additionally gets a venue/place background (event promo image → Unsplash),
    stored per-event; the shared background remains as the fallback.

    When ``auto_music`` is on, a popularity-ranked royalty-free instrumental is
    auto-selected from Jamendo, skipping any track id in ``music_exclude_ids``
    (anti-repetition). It takes priority over the type/city default but not over
    an explicit ``music_upload``.
    """
    settings = settings or get_settings()
    settings.ensure_dirs()

    captions = generate_captions(city, events, window, settings=settings)

    bg_path = settings.output_dir / draft_id / "background.jpg"
    background = resolve_background(
        city, bg_path, size, upload_path=image_upload, settings=settings
    )

    event_backgrounds: dict[str, str] = {}
    if smart_backgrounds:
        event_backgrounds = _resolve_event_backgrounds(
            events, city, draft_id, size, settings=settings
        )

    music, music_track_id = _resolve_music_with_auto(
        city,
        events,
        event_types,
        draft_id,
        music_upload=music_upload,
        smart_music=smart_music,
        auto_music=auto_music,
        music_exclude_ids=music_exclude_ids or [],
        settings=settings,
    )

    return PostContent(
        title=captions.title,
        caption=captions.caption,
        hashtags=captions.hashtags,
        background_image_path=str(background),
        music_path=str(music) if music else None,
        music_track_id=music_track_id,
        event_backgrounds=event_backgrounds,
    )


def _resolve_music_with_auto(
    city: City,
    events: list[Event],
    event_types: list[EventType],
    draft_id: str,
    *,
    music_upload: Path | None,
    smart_music: bool,
    auto_music: bool,
    music_exclude_ids: list[str],
    settings: Settings,
) -> tuple[Path | None, str | None]:
    """Resolve the track path + its tracking id.

    Priority: upload → auto (Jamendo, non-repetitive) → type/city default → none.
    Returns ``(path, track_id)``; ``track_id`` is set only for auto-selected
    tracks so recent ones can be excluded next time.
    """
    # Explicit upload always wins (handled inside resolve_music too, but short-
    # circuit here so we never spend a Jamendo call on an upload).
    if music_upload is not None:
        return resolve_music(
            city, events, event_types, upload_path=music_upload, settings=settings
        ), None

    if auto_music:
        from .jamendo import fetch_track

        out_dir = settings.output_dir / draft_id
        track = fetch_track(out_dir, exclude_ids=music_exclude_ids, settings=settings)
        if track is not None:
            return track.path, f"jamendo:{track.track_id}"
        logger.info("auto-music unavailable; falling back to default music chain")

    music = resolve_music(city, events, event_types, use_defaults=smart_music, settings=settings)
    return music, None


def _resolve_event_backgrounds(
    events: list[Event],
    city: City,
    draft_id: str,
    size: tuple[int, int],
    *,
    settings: Settings,
) -> dict[str, str]:
    """Resolve a venue/place background per event (best-effort, never raises)."""
    from .images.venue import resolve_event_background

    result: dict[str, str] = {}
    base = settings.output_dir / draft_id
    for i, event in enumerate(events):
        out_path = base / f"event_bg_{i}.jpg"
        resolved = resolve_event_background(event, city.name, out_path, size, settings=settings)
        if resolved is not None:
            result[event.id] = str(resolved)
    if result:
        logger.info("resolved %d/%d smart backgrounds", len(result), len(events))
    return result
