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
    image_upload: Path | None = None,
    music_upload: Path | None = None,
    smart_backgrounds: bool = False,
    smart_music: bool = True,
    auto_music: bool = False,
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
        status=DraftStatus.RENDERING,
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
        music_exclude_ids=(
            storage.recent_music_track_ids(settings.music_history_size) if auto_music else []
        ),
        settings=settings,
    )
    draft.content = content

    # 3. Render video
    fmt = get_format(render_format)
    progress(f"Rendering {fmt.name} video ({fmt.width}×{fmt.height})…")
    out_path = settings.output_dir / draft.id / f"{fmt.name}.mp4"
    render_video(
        content, events, out_path, fmt, theme=theme, intensity=intensity, animation=animation
    )
    draft.video_path = str(out_path)
    draft.theme = theme
    draft.status = DraftStatus.READY

    # 4. Persist
    saved = storage.save_draft(draft)
    progress("Draft ready.")
    logger.info("pipeline produced draft %s (%s)", saved.id, saved.video_path)
    return saved


def render_theme_previews(
    draft: PostDraft,
    *,
    themes: list[str] | None = None,
    render_format: str = "reel",
    intensity: float | None = None,
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

    theme_names = themes if themes is not None else list(THEMES.keys())
    fmt = get_format(render_format)
    previews: dict[str, str] = dict(draft.theme_previews)

    for name in theme_names:
        progress(f"Rendering '{name}' preview…")
        out_path = settings.output_dir / draft.id / "previews" / f"{name}.mp4"
        render_video(draft.content, draft.events, out_path, fmt, theme=name, intensity=intensity)
        previews[name] = str(out_path)

    draft.theme_previews = previews
    # If nothing is selected yet, default to the first rendered theme.
    if draft.theme is None and theme_names:
        draft.theme = theme_names[0]
        draft.video_path = previews[theme_names[0]]

    saved = storage.save_draft(draft)
    progress(f"Rendered {len(theme_names)} theme preview(s).")
    logger.info("rendered %d theme previews for draft %s", len(theme_names), saved.id)
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
