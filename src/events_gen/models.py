"""Core domain models shared across the pipeline.

These are pydantic models so they validate at the boundaries (API responses,
UI inputs, DB round-trips) and serialize cleanly to/from JSON for SQLite
storage.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl


def _new_id() -> str:
    return uuid4().hex


class TimeWindow(StrEnum):
    """Discovery window for events."""

    WEEK = "week"
    MONTH = "month"
    CUSTOM = "custom"


class Platform(StrEnum):
    """Publishing destinations."""

    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"


class DraftStatus(StrEnum):
    """Lifecycle of a post draft."""

    DRAFT = "draft"
    RENDERING = "rendering"
    READY = "ready"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class JobStatus(StrEnum):
    """Lifecycle of a background/pipeline job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ScheduleCadence(StrEnum):
    """How often a scheduled run fires."""

    WEEKLY = "weekly"
    MONTHLY = "monthly"


class City(BaseModel):
    """A city the app can generate posts for (from ``config/cities.yaml``)."""

    slug: str
    name: str
    country: str
    country_code: str
    timezone: str
    latitude: float
    longitude: float
    default_image: str | None = None
    default_music: str | None = None


class EventType(BaseModel):
    """An event category (from ``config/event_types.yaml``)."""

    slug: str
    name: str
    default_music: str | None = None
    # per-source category hints, e.g. {"ticketmaster": ["Music"], "eventbrite": ["103"]}
    source_categories: dict[str, list[str]] = Field(default_factory=dict)


class Event(BaseModel):
    """A single normalized event, deduped and ranked by the aggregator."""

    id: str = Field(default_factory=_new_id)
    source: str  # e.g. "ticketmaster", "eventbrite", "scraper"
    source_event_id: str | None = None
    title: str
    description: str | None = None
    event_type: str | None = None  # event-type slug, if classified
    start: datetime
    end: datetime | None = None
    venue: str | None = None
    city_slug: str
    url: HttpUrl | None = None
    image_url: HttpUrl | None = None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    rank_score: float = 0.0  # populated by the aggregator's ranking step

    def dedupe_key(self) -> str:
        """Stable key for cross-source dedupe: title + date + venue."""
        day = self.start.date().isoformat()
        venue = (self.venue or "").strip().lower()
        title = self.title.strip().lower()
        return f"{title}|{day}|{venue}"


class FontStyle(BaseModel):
    """One set of typography knobs applied to ALL text in the video + thumbnail.

    Set once, at the end, after the video is rendered — a single re-render applies
    it everywhere. ``font_path`` is an absolute path to a system font file (chosen
    from the font picker); ``None`` uses the built-in default family. Sizes are in
    pixels at the format's native width. Colors are hex strings (e.g. "#ffffff").
    """

    font_path: str | None = None
    font_name: str | None = None  # display label for the chosen font (UI only)
    title_size: int = 68
    body_size: int = 44
    title_color: str = "#ffffff"
    body_color: str = "#ebebeb"
    accent_color: str = "#b4dcb4"
    # Vertical placement of the text block: "top" | "center" | "bottom".
    placement: str = "center"
    # Horizontal text alignment within the card: "left" | "center" | "right".
    text_align: str = "left"
    # Legibility treatment: "panel" (opaque box), "outline", or "shadow".
    text_style: str = "shadow"
    # Panel opacity 0–1 (only used when text_style == "panel").
    panel_opacity: float = 0.6
    uppercase_titles: bool = False


class PostContent(BaseModel):
    """Generated + selected content for a post (captions, background, music)."""

    title: str
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    background_image_path: str | None = None
    music_path: str | None = None
    # Identifier of the auto-selected music track (e.g. "jamendo:12345"), used to
    # avoid repeating tracks across recent posts. None for uploads/local defaults.
    music_track_id: str | None = None
    # Optional per-event venue/place backgrounds ("smart backgrounds"), keyed by
    # Event.id. The renderer uses these for each event's card, falling back to
    # ``background_image_path`` when an event has no entry.
    event_backgrounds: dict[str, str] = Field(default_factory=dict)
    # Optional per-event video clips (M16), keyed by Event.id → clip path.
    # When present, the renderer uses a VideoFileClip instead of a still image.
    event_video_clips: dict[str, str] = Field(default_factory=dict)
    # Per-event *requested* background source, keyed by Event.id. One of
    # "wikimedia" | "stock" | "promo" | "upload". "promo" forces the event's
    # Ticketmaster image (Ken-Burns animated); the others resolve to a clip path
    # stored in ``event_video_clips``.
    event_background_overrides: dict[str, str] = Field(default_factory=dict)
    # Per-event *realized* source of the current clip/background (authoritative for
    # the edit-pane radio default): "wikimedia" | "stock" | "promo" | "upload".
    event_clip_sources: dict[str, str] = Field(default_factory=dict)


class Destination(BaseModel):
    """A publishing account scoped to a city (M13).

    One Destination = one platform account. A city can have N destinations
    (e.g. 2 YouTube channels + 1 Instagram). Credentials are stored under
    ``secrets/<id>/`` so they stay out of the database payload.
    """

    id: str = Field(default_factory=_new_id)
    city_slug: str
    label: str
    platform: Platform
    # YouTube credential paths (relative to repo root / secrets/).
    youtube_client_secrets_path: str | None = None
    youtube_token_path: str | None = None
    # Instagram credentials (stored directly — they're just strings).
    instagram_access_token: str | None = None
    instagram_business_account_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PublishResult(BaseModel):
    """Outcome of publishing a draft to one platform/destination."""

    platform: Platform
    destination_id: str | None = None
    success: bool
    external_id: str | None = None  # video id / media id
    url: str | None = None
    error: str | None = None
    published_at: datetime | None = None


class PostDraft(BaseModel):
    """A generated post awaiting review, render, and/or publish."""

    id: str = Field(default_factory=_new_id)
    city_slug: str
    window: TimeWindow
    event_types: list[str] = Field(default_factory=list)
    event_count: int
    events: list[Event] = Field(default_factory=list)
    content: PostContent | None = None
    video_path: str | None = None
    # Poster thumbnail shown before the video plays. ``thumbnail_title`` overrides
    # the headline text (defaults to the post title when None).
    thumbnail_path: str | None = None
    thumbnail_title: str | None = None
    # Thumbnail option gallery: variant-key → rendered image path, and the chosen
    # variant key (its image == ``thumbnail_path``). Populated on demand.
    thumbnail_options: dict[str, str] = Field(default_factory=dict)
    thumbnail_choice: str | None = None
    # Single typography style applied to ALL video/thumbnail text, set post-render.
    font_style: FontStyle | None = None
    # Target render format ("reel" / "short" / "landscape" / 4K variants). Captured
    # when the draft is prepared so the eventual video encode uses the right size.
    render_format: str = "reel"
    # Theme name → rendered video path, when previews are generated per theme.
    # ``theme`` is the currently-selected one (its path == ``video_path``).
    theme_previews: dict[str, str] = Field(default_factory=dict)
    theme: str | None = None
    # Render settings captured at generation time so theme previews stay consistent.
    intensity: float | None = None
    animation: str | None = None
    text_position: str = "center"
    # How card text is made legible: "panel" (opaque scrim), "outline", or "shadow".
    text_style: str = "panel"
    targets: list[Platform] = Field(default_factory=list)
    status: DraftStatus = DraftStatus.DRAFT
    results: list[PublishResult] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CityPreset(BaseModel):
    """A saved set of Create-screen defaults for a city (R10).

    Captures the controls an operator would otherwise re-pick each run: event
    types, count, window, render format, chosen background/music, and targets.
    """

    id: str = Field(default_factory=_new_id)
    name: str
    city_slug: str
    window: TimeWindow = TimeWindow.WEEK
    event_types: list[str] = Field(default_factory=list)
    event_count: int = 5
    render_format: str = "reel"
    theme: str | None = None
    intensity: float | None = None
    background_path: str | None = None
    music_path: str | None = None
    targets: list[Platform] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Job(BaseModel):
    """A unit of pipeline work (generation and/or publish), for tracking + history."""

    id: str = Field(default_factory=_new_id)
    kind: str  # e.g. "generate", "publish", "scheduled_run"
    draft_id: str | None = None
    status: JobStatus = JobStatus.PENDING
    detail: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Schedule(BaseModel):
    """A recurring, toggleable auto-run configuration for a city (M7)."""

    id: str = Field(default_factory=_new_id)
    city_slug: str
    cadence: ScheduleCadence
    window: TimeWindow
    event_types: list[str] = Field(default_factory=list)
    event_count: int = 5
    targets: list[Platform] = Field(default_factory=list)
    auto_publish: bool = False  # False = generate draft only (review required)
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
