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


class PublishResult(BaseModel):
    """Outcome of publishing a draft to one platform."""

    platform: Platform
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
