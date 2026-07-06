"""Tests for the core domain models."""

from __future__ import annotations

from datetime import UTC, datetime

from events_gen.models import (
    DraftStatus,
    Event,
    Platform,
    PostContent,
    PostDraft,
    TimeWindow,
)


def _event(**overrides: object) -> Event:
    base = {
        "source": "ticketmaster",
        "title": "Jazz Night",
        "start": datetime(2026, 7, 10, 20, 0, tzinfo=UTC),
        "venue": "Blue Note",
        "city_slug": "new-york",
    }
    base.update(overrides)
    return Event(**base)  # type: ignore[arg-type]


def test_event_dedupe_key_is_case_and_space_insensitive() -> None:
    a = _event(title="Jazz Night", venue="Blue Note")
    b = _event(title="  jazz night ", venue="  blue note ")
    assert a.dedupe_key() == b.dedupe_key()


def test_event_dedupe_key_differs_by_day() -> None:
    a = _event(start=datetime(2026, 7, 10, 20, 0, tzinfo=UTC))
    b = _event(start=datetime(2026, 7, 11, 20, 0, tzinfo=UTC))
    assert a.dedupe_key() != b.dedupe_key()


def test_ids_are_unique() -> None:
    assert _event().id != _event().id


def test_post_draft_defaults() -> None:
    draft = PostDraft(
        city_slug="london",
        window=TimeWindow.WEEK,
        event_types=["music"],
        event_count=5,
    )
    assert draft.status is DraftStatus.DRAFT
    assert draft.events == []
    assert draft.results == []
    assert draft.created_at is None  # set by storage on save


def test_post_draft_roundtrips_json_with_nested_content() -> None:
    draft = PostDraft(
        city_slug="tokyo",
        window=TimeWindow.MONTH,
        event_types=["music", "arts"],
        event_count=3,
        events=[_event(city_slug="tokyo")],
        content=PostContent(
            title="This Month in Tokyo", caption="Don't miss out!", hashtags=["#tokyo"]
        ),
        targets=[Platform.YOUTUBE, Platform.INSTAGRAM],
    )
    restored = PostDraft.model_validate_json(draft.model_dump_json())
    assert restored.city_slug == "tokyo"
    assert restored.content is not None
    assert restored.content.hashtags == ["#tokyo"]
    assert restored.targets == [Platform.YOUTUBE, Platform.INSTAGRAM]
    assert len(restored.events) == 1
