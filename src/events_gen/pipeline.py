"""End-to-end generation pipeline: fetch → content → render → draft.

This is the single orchestration entry point the UI (and later the scheduler)
call. It ties together the pieces built in M1–M4:

    registry (city/types) → aggregator.fetch → build_content → render_video
    → PostDraft persisted via Storage

``run`` is deliberately synchronous and returns a saved :class:`PostDraft`. A
``progress`` callback lets the caller (Streamlit) surface step-by-step status
without the pipeline importing any UI code.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .content.builder import build_content
from .models import DraftStatus, Event, Platform, PostDraft, TimeWindow
from .registry import get_city, load_event_types
from .render import THEMES, get_format, render_video
from .settings import Settings, get_settings
from .sources import aggregator
from .storage import Storage
from .timewindow import compute_window

logger = logging.getLogger(__name__)

# A no-op default so callers don't have to pass one.
ProgressFn = Callable[[str], None]


def _noop(_: str) -> None:  # pragma: no cover - trivial
    pass


class PipelineError(Exception):
    """Raised when generation cannot produce a draft (e.g. no events found)."""


def run(
    *,
    city_slug: str,
    window: TimeWindow = TimeWindow.WEEK,
    event_types: list[str] | None = None,
    count: int = 5,
    render_format: str = "reel",
    theme: str | None = None,
    intensity: float | None = None,
    animation: str | None = None,
    text_position: str = "center",
    text_style: str = "panel",
    image_upload: Path | None = None,
    music_upload: Path | None = None,
    smart_backgrounds: bool = False,
    smart_music: bool = True,
    auto_music: bool = False,
    use_llm: bool = True,
    use_video_clips: bool = False,
    events: list[Event] | None = None,
    targets: list[Platform] | None = None,
    custom_start: datetime | None = None,
    custom_end: datetime | None = None,
    storage: Storage | None = None,
    settings: Settings | None = None,
    progress: ProgressFn = _noop,
) -> PostDraft:
    """Run the full generation pipeline and return a saved draft.

    Steps: resolve city/types → fetch events → build content → render video →
    persist a :class:`PostDraft` with ``status=READY``. Raises
    :class:`PipelineError` if no events are found.

    This is ``prepare_draft`` (fetch + content, no encode) followed by
    ``render_draft`` (the one expensive video encode). Callers that want instant
    per-event still previews before committing to the encode can call
    ``prepare_draft`` directly and encode later.
    """
    settings = settings or get_settings()
    storage = storage or Storage(settings.db_path)
    draft = prepare_draft(
        city_slug=city_slug,
        window=window,
        event_types=event_types,
        count=count,
        render_format=render_format,
        theme=theme,
        intensity=intensity,
        animation=animation,
        text_position=text_position,
        text_style=text_style,
        image_upload=image_upload,
        music_upload=music_upload,
        smart_backgrounds=smart_backgrounds,
        smart_music=smart_music,
        auto_music=auto_music,
        use_llm=use_llm,
        use_video_clips=use_video_clips,
        events=events,
        targets=targets,
        custom_start=custom_start,
        custom_end=custom_end,
        storage=storage,
        settings=settings,
        progress=progress,
    )
    return render_draft(
        draft, render_format=render_format, storage=storage, settings=settings, progress=progress
    )


def prepare_draft(
    *,
    city_slug: str,
    window: TimeWindow = TimeWindow.WEEK,
    event_types: list[str] | None = None,
    count: int = 5,
    render_format: str = "reel",
    theme: str | None = None,
    intensity: float | None = None,
    animation: str | None = None,
    text_position: str = "center",
    text_style: str = "panel",
    image_upload: Path | None = None,
    music_upload: Path | None = None,
    smart_backgrounds: bool = False,
    smart_music: bool = True,
    auto_music: bool = False,
    use_llm: bool = True,
    use_video_clips: bool = False,
    events: list[Event] | None = None,
    targets: list[Platform] | None = None,
    custom_start: datetime | None = None,
    custom_end: datetime | None = None,
    storage: Storage | None = None,
    settings: Settings | None = None,
    progress: ProgressFn = _noop,
) -> PostDraft:
    """Fetch events + build content and persist a draft — WITHOUT the video encode.

    Returns a saved :class:`PostDraft` with ``content`` populated (captions,
    backgrounds, per-event clips, music) and ``status=DRAFT`` but no
    ``video_path``. This is the fast part of ``run``; still previews can be
    rendered from ``draft.content`` instantly, and ``render_draft`` produces the
    final video only when the user commits. Raises :class:`PipelineError` if no
    events are found.
    """
    settings = settings or get_settings()
    settings.ensure_dirs()
    storage = storage or Storage(settings.db_path)

    city = get_city(city_slug, settings)
    all_types = load_event_types(settings)
    wanted = set(event_types or [])
    types = [t for t in all_types if t.slug in wanted] if wanted else []

    # 1. Fetch events (or use pre-selected list from the interactive picker)
    if events is not None:
        if not events:
            raise PipelineError("no events selected (empty list passed)")
        progress(f"Using {len(events)} pre-selected event(s).")
    else:
        progress(f"Discovering events in {city.name}…")
        date_range = compute_window(window, city.timezone, start=custom_start, end=custom_end)
        events = aggregator.fetch(city, date_range, types, count=count, settings=settings)
        if not events:
            raise PipelineError(f"no events found for {city.name} in the {window.value} window")
        progress(f"Found {len(events)} event(s).")

    # Create the draft up front so content/video paths are scoped to its id.
    draft = PostDraft(
        city_slug=city.slug,
        window=window,
        event_types=list(wanted),
        event_count=count,
        events=events,
        targets=targets or [],
        render_format=render_format,
        theme=theme,
        intensity=intensity,
        animation=animation,
        text_position=text_position,
        text_style=text_style,
        status=DraftStatus.DRAFT,
    )

    # 2. Build content (captions + background + music)
    progress("Writing captions and preparing assets…")
    content = build_content(
        city,
        events,
        types or all_types,
        window.value,
        draft_id=draft.id,
        image_upload=image_upload,
        music_upload=music_upload,
        smart_backgrounds=smart_backgrounds,
        smart_music=smart_music,
        auto_music=auto_music,
        use_llm=use_llm,
        use_video_clips=use_video_clips,
        music_exclude_ids=(
            storage.recent_music_track_ids(settings.music_history_size) if auto_music else []
        ),
        settings=settings,
    )
    draft.content = content

    saved = storage.save_draft(draft)
    progress(f"Prepared {len(events)} event(s).")
    logger.info("pipeline prepared draft %s (%d events, no video yet)", saved.id, len(events))
    return saved


def render_draft(
    draft: PostDraft,
    *,
    render_format: str | None = None,
    storage: Storage | None = None,
    settings: Settings | None = None,
    progress: ProgressFn = _noop,
) -> PostDraft:
    """Encode the final combined video for a prepared draft and mark it READY.

    Uses the draft's captured render settings (theme/intensity/animation/text).
    ``render_format`` defaults to the draft's stored format. This is the single
    expensive step, split out so it runs only when the user commits to combining
    the events into a video.
    """
    settings = settings or get_settings()
    storage = storage or Storage(settings.db_path)
    if draft.content is None:
        raise PipelineError("draft has no content to render; prepare it first")

    fmt = get_format(render_format or draft.render_format)
    progress(f"Rendering {fmt.name} video ({fmt.width}×{fmt.height})…")
    out_path = settings.output_dir / draft.id / f"{fmt.name}.mp4"
    render_video(
        draft.content,
        draft.events,
        out_path,
        fmt,
        theme=draft.theme,
        intensity=draft.intensity,
        animation=draft.animation,
        text_position=draft.text_position,
        text_style=draft.text_style,
        font_style=draft.font_style,
    )
    draft.video_path = str(out_path)
    draft.status = DraftStatus.READY

    # Generate the poster thumbnail (unless one was already customized).
    progress("Rendering thumbnail…")
    render_thumbnail_for_draft(draft, settings=settings)

    saved = storage.save_draft(draft)
    progress("Video ready.")
    logger.info("pipeline rendered draft %s (%s)", saved.id, saved.video_path)
    return saved


def render_thumbnail_for_draft(
    draft: PostDraft,
    *,
    settings: Settings | None = None,
) -> PostDraft:
    """Render (or re-render) the draft's poster thumbnail and set ``thumbnail_path``.

    Uses the draft's stored format/theme and ``thumbnail_title`` override. Does not
    persist — the caller saves the draft. Best-effort: failures leave the prior
    thumbnail untouched.
    """
    from .render import get_format, render_thumbnail

    settings = settings or get_settings()
    if draft.content is None:
        return draft
    fmt = get_format(draft.render_format)
    out_path = settings.output_dir / draft.id / "thumbnail.jpg"
    try:
        render_thumbnail(
            draft.content,
            draft.events,
            out_path,
            fmt=fmt,
            theme=draft.theme,
            title=draft.thumbnail_title,
            font_style=draft.font_style,
        )
        draft.thumbnail_path = str(out_path)
    except Exception:  # noqa: BLE001 - thumbnail is non-critical
        logger.warning("thumbnail render failed for draft %s", draft.id, exc_info=True)
    return draft


def render_thumbnail_options(
    draft: PostDraft,
    *,
    count: int = 10,
    storage: Storage | None = None,
    settings: Settings | None = None,
    progress: ProgressFn = _noop,
) -> PostDraft:
    """Render a gallery of ``count`` thumbnail options and persist their paths.

    Each option pairs a heading layout with a different (vibrant) event backdrop.
    Populates ``draft.thumbnail_options`` (key → path). Defaults ``thumbnail_path``
    to the first option when none is chosen yet.
    """
    from .render import get_format, render_thumbnail_variants

    settings = settings or get_settings()
    storage = storage or Storage(settings.db_path)
    if draft.content is None:
        raise PipelineError("draft has no content; render it first")

    progress(f"Rendering {count} thumbnail options…")
    out_dir = settings.output_dir / draft.id / "thumbnails"
    import contextlib

    from .registry import get_city

    city_name = ""
    with contextlib.suppress(Exception):
        city_name = get_city(draft.city_slug, settings).name
    variants = render_thumbnail_variants(
        draft.content,
        draft.events,
        out_dir,
        fmt=get_format(draft.render_format),
        theme=draft.theme,
        title=draft.thumbnail_title,
        font_style=draft.font_style,
        city_name=city_name,
        count=count,
        settings=settings,
    )
    draft.thumbnail_options = {k: str(v) for k, v in variants.items()}
    if variants and (draft.thumbnail_choice not in variants):
        first_key = next(iter(variants))
        draft.thumbnail_choice = first_key
        draft.thumbnail_path = str(variants[first_key])
    return storage.save_draft(draft)


def render_event_preview(
    draft: PostDraft,
    event_id: str,
    *,
    out_path: Path | None = None,
    settings: Settings | None = None,
    progress: ProgressFn = _noop,
) -> Path:
    """Render (and return the path of) one event's short standalone preview video.

    Plays that event's background clip + card + text using the draft's current
    render settings — the moving counterpart to the still thumbnail. Rendered
    lazily (only when the user clicks play) and cached under the draft's output
    dir. ``out_path`` lets the caller pick a cache-keyed filename so previews for
    different sources/text settings coexist and are reused. Raises
    :class:`PipelineError` if the event/content is missing.
    """
    from .render import render_event_segment

    settings = settings or get_settings()
    if draft.content is None:
        raise PipelineError("draft has no content; prepare it first")
    events_by_id = {e.id: e for e in draft.events}
    event = events_by_id.get(event_id)
    if event is None:
        raise PipelineError(f"event {event_id!r} not in draft")

    index = list(events_by_id).index(event_id) + 1
    fmt = get_format(draft.render_format)
    if out_path is None:
        out_path = settings.output_dir / draft.id / "segments" / f"{event_id}.mp4"
    progress(f"Rendering preview for {event.title}…")
    render_event_segment(
        draft.content,
        event,
        index,
        len(draft.events),
        out_path,
        fmt,
        theme=draft.theme,
        intensity=draft.intensity,
        text_position=draft.text_position,
        text_style=draft.text_style,
        font_style=draft.font_style,
    )
    return out_path


def render_theme_previews(
    draft: PostDraft,
    *,
    themes: list[str] | None = None,
    render_format: str = "reel",
    intensity: float | None = None,
    animation: str | None = None,
    text_position: str | None = None,
    storage: Storage | None = None,
    settings: Settings | None = None,
    progress: ProgressFn = _noop,
) -> PostDraft:
    """Render one preview video per theme for an already-finalized ``draft``.

    Content (captions, background, music) is reused as-is — only the render
    (fonts/colors/scrim) varies — so this is cheap and every preview shows the
    same finalized content. Populates ``draft.theme_previews`` (theme → path) and
    leaves the current selection (``draft.theme`` / ``draft.video_path``)
    untouched unless it was empty, in which case the first theme becomes current.

    Raises :class:`PipelineError` if the draft has no rendered content yet.
    """
    settings = settings or get_settings()
    settings.ensure_dirs()
    storage = storage or Storage(settings.db_path)

    if draft.content is None:
        raise PipelineError("draft has no content to preview; generate it first")

    # Default render settings from the draft (captured at generation time) so
    # previews match the original video's intensity/animation/placement.
    eff_intensity = intensity if intensity is not None else draft.intensity
    eff_animation = animation if animation is not None else draft.animation
    eff_text_position = text_position if text_position is not None else draft.text_position

    theme_names = themes if themes is not None else list(THEMES.keys())
    fmt = get_format(render_format)
    previews: dict[str, str] = dict(draft.theme_previews)

    for name in theme_names:
        progress(f"Rendering '{name}' preview…")
        out_path = settings.output_dir / draft.id / "previews" / f"{name}.mp4"
        render_video(
            draft.content,
            draft.events,
            out_path,
            fmt,
            theme=name,
            intensity=eff_intensity,
            animation=eff_animation,
            text_position=eff_text_position,
            text_style=draft.text_style,
        )
        previews[name] = str(out_path)
        # Persist after each theme so the UI can display previews incrementally as
        # they finish (rather than all at once when the whole batch completes).
        draft.theme_previews = dict(previews)
        if draft.theme is None:
            draft.theme = name
            draft.video_path = str(out_path)
        draft = storage.save_draft(draft)

    progress(f"Rendered {len(theme_names)} theme preview(s).")
    logger.info("rendered %d theme previews for draft %s", len(theme_names), draft.id)
    return draft


def resolve_event_sources(
    draft: PostDraft,
    choices: dict[str, str],
    uploads: dict[str, Path] | None = None,
    *,
    links: dict[str, str] | None = None,
    render_format: str = "reel",
    storage: Storage | None = None,
    settings: Settings | None = None,
    progress: ProgressFn = _noop,
) -> PostDraft:
    """Resolve each event's chosen background source into the draft's content.

    ``choices`` maps Event.id → a source: "wikimedia" | "pexels" | "pixabay" |
    "coverr" | "stock" (any stock provider) | "promo" | "upload" | "link".
    ``uploads`` maps Event.id → a saved upload path (for "upload" choices).
    ``links`` maps Event.id → a pasted clip URL (for "link" choices; a direct video
    URL or a Pexels/Pixabay/Coverr page URL).
    Uses the disk clip cache so re-selecting the same source doesn't re-download.
    Best-effort: a failed fetch leaves that event's current clip/source untouched.
    """
    from .content import clip_cache
    from .content.video_clips import (
        ClipLinkError,
        fetch_link_clip,
        fetch_stock_only,
        fetch_wikimedia_only,
    )

    settings = settings or get_settings()
    storage = storage or Storage(settings.db_path)
    uploads = uploads or {}
    links = links or {}
    if draft.content is None:
        raise PipelineError("draft has no content to update")

    content = draft.content
    city = get_city(draft.city_slug, settings)
    duration = get_format(render_format).seconds_per_card
    events_by_id = {e.id: e for e in draft.events}

    for event_id, source in choices.items():
        event = events_by_id.get(event_id)
        if event is None:
            continue

        if source == "promo":
            content.event_background_overrides[event_id] = "promo"
            content.event_video_clips.pop(event_id, None)
            content.event_clip_sources[event_id] = "promo"
            continue

        # Clip-producing sources: check cache, then fetch on miss.
        cached = clip_cache.get_cached(settings, draft.id, event_id, source)
        if cached is not None:
            progress(f"{event.title}: cached {source} clip")
            clip_path: Path | None = cached
        elif source == "upload":
            up = uploads.get(event_id)
            clip_path = (
                clip_cache.store_clip(settings, draft.id, event_id, "upload", up) if up else None
            )
        elif source == "link":
            link = links.get(event_id, "")
            fetch_dir = settings.output_dir / draft.id / "clip_cache" / event_id / "_fetch"
            try:
                progress(f"{event.title}: fetching pasted clip…")
                fetched = fetch_link_clip(
                    link, fetch_dir, event_id, duration, settings=settings
                )
            except ClipLinkError as exc:
                progress(f"{event.title}: {exc}")
                fetched = None
            clip_path = (
                clip_cache.store_clip(settings, draft.id, event_id, "link", fetched[0])
                if fetched is not None
                else None
            )
        else:
            progress(f"{event.title}: fetching {source} clip…")
            fetch_dir = settings.output_dir / draft.id / "clip_cache" / event_id / "_fetch"
            if source == "wikimedia":
                fetched = fetch_wikimedia_only(event, fetch_dir, duration)
            else:
                # "stock" = any provider; a specific provider name restricts to it.
                provs = None if source == "stock" else [source]
                fetched = fetch_stock_only(
                    event, city.name, fetch_dir, duration, providers=provs, settings=settings
                )
            clip_path = (
                clip_cache.store_clip(settings, draft.id, event_id, source, fetched[0])
                if fetched is not None
                else None
            )

        if clip_path is not None:
            content.event_video_clips[event_id] = str(clip_path)
            content.event_background_overrides.pop(event_id, None)
            content.event_clip_sources[event_id] = source
        else:
            progress(f"{event.title}: no {source} clip found; keeping current background")

    draft.content = content
    return storage.save_draft(draft)


def render_video_in_place(
    draft: PostDraft,
    *,
    render_format: str | None = None,
    storage: Storage | None = None,
    settings: Settings | None = None,
    progress: ProgressFn = _noop,
) -> PostDraft:
    """Re-render a draft's video reusing its existing content + render settings.

    Fast path for edit-pane changes (e.g. font-style / per-event backgrounds): no
    event re-fetch, no content rebuild — only the render step runs, writing back to
    the draft's current ``video_path``, then the thumbnail is refreshed too (font
    changes affect it). ``render_format`` defaults to the draft's stored format.
    """
    settings = settings or get_settings()
    settings.ensure_dirs()
    storage = storage or Storage(settings.db_path)

    if draft.content is None:
        raise PipelineError("draft has no content to re-render")

    fmt = get_format(render_format or draft.render_format)
    out_path = (
        Path(draft.video_path)
        if draft.video_path
        else (settings.output_dir / draft.id / f"{fmt.name}.mp4")
    )
    progress("Re-rendering video…")
    render_video(
        draft.content,
        draft.events,
        out_path,
        fmt,
        theme=draft.theme,
        intensity=draft.intensity,
        animation=draft.animation,
        text_position=draft.text_position,
        text_style=draft.text_style,
        font_style=draft.font_style,
    )
    draft.video_path = str(out_path)
    # Keep the thumbnail in sync with the new typography.
    render_thumbnail_for_draft(draft, settings=settings)
    saved = storage.save_draft(draft)
    progress("Re-render complete.")
    return saved


def select_theme(
    draft: PostDraft,
    theme: str,
    *,
    storage: Storage | None = None,
    settings: Settings | None = None,
) -> PostDraft:
    """Choose ``theme`` as the draft's final render (its preview becomes current).

    Raises :class:`PipelineError` if no preview exists for ``theme``.
    """
    settings = settings or get_settings()
    storage = storage or Storage(settings.db_path)
    path = draft.theme_previews.get(theme)
    if path is None:
        raise PipelineError(f"no preview rendered for theme {theme!r}")
    draft.theme = theme
    draft.video_path = path
    return storage.save_draft(draft)


def run_roundup(
    *,
    city_slugs: list[str],
    events_per_city: int = 1,
    render_format: str = "reel",
    theme: str | None = None,
    intensity: float | None = None,
    animation: str | None = None,
    storage: Storage | None = None,
    settings: Settings | None = None,
    progress: ProgressFn = _noop,
) -> PostDraft:
    """Generate a combined multi-city roundup video.

    Fetches the top ``events_per_city`` event(s) from each city, merges them into
    one event list, and renders a single video with a roundup-style caption.
    """
    from .content.builder import build_content

    settings = settings or get_settings()
    settings.ensure_dirs()
    storage = storage or Storage(settings.db_path)

    all_events: list[Event] = []
    city_names: list[str] = []
    for slug in city_slugs:
        city = get_city(slug, settings)
        city_names.append(city.name)
        all_types = load_event_types(settings)
        progress(f"Fetching top event(s) from {city.name}…")
        date_range = compute_window(TimeWindow.WEEK, city.timezone)
        events = aggregator.fetch(city, date_range, [], count=events_per_city, settings=settings)
        all_events.extend(events)

    if not all_events:
        raise PipelineError("no events found across any of the selected cities")

    progress(f"Building roundup for {len(city_slugs)} cities, {len(all_events)} events…")
    draft = PostDraft(
        city_slug=city_slugs[0],
        window=TimeWindow.WEEK,
        event_types=[],
        event_count=len(all_events),
        events=all_events,
        status=DraftStatus.RENDERING,
    )

    # Use the first city for background/music resolution.
    city = get_city(city_slugs[0], settings)
    all_types = load_event_types(settings)
    content = build_content(
        city,
        all_events,
        all_types,
        "week",
        draft_id=draft.id,
        settings=settings,
    )
    # Override the title with a roundup-style one.
    content.title = f"This Weekend: {', '.join(city_names[:4])}"
    if len(city_names) > 4:
        content.title += f" + {len(city_names) - 4} more"
    draft.content = content

    fmt = get_format(render_format)
    progress(f"Rendering roundup ({fmt.name})…")
    out_path = settings.output_dir / draft.id / f"roundup_{fmt.name}.mp4"
    render_video(
        content, all_events, out_path, fmt, theme=theme, intensity=intensity, animation=animation
    )
    draft.video_path = str(out_path)
    draft.status = DraftStatus.READY

    saved = storage.save_draft(draft)
    progress("Roundup ready.")
    return saved
