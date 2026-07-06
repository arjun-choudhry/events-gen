"""Tests for the SQLite storage layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from events_gen.models import (
    DraftStatus,
    Job,
    JobStatus,
    Platform,
    PostDraft,
    Schedule,
    ScheduleCadence,
    TimeWindow,
)
from events_gen.storage import Storage


@pytest.fixture()
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "test.db")


def _draft(**overrides: object) -> PostDraft:
    base = {
        "city_slug": "new-york",
        "window": TimeWindow.WEEK,
        "event_types": ["music"],
        "event_count": 5,
    }
    base.update(overrides)
    return PostDraft(**base)  # type: ignore[arg-type]


def test_save_sets_timestamps(storage: Storage) -> None:
    draft = storage.save_draft(_draft())
    assert draft.created_at is not None
    assert draft.updated_at is not None


def test_create_read_update_draft(storage: Storage) -> None:
    draft = storage.save_draft(_draft())
    fetched = storage.get_draft(draft.id)
    assert fetched is not None
    assert fetched.city_slug == "new-york"

    created_at = fetched.created_at
    fetched.status = DraftStatus.READY
    updated = storage.save_draft(fetched)

    reread = storage.get_draft(draft.id)
    assert reread is not None
    assert reread.status is DraftStatus.READY
    assert reread.created_at == created_at  # preserved across update
    assert updated.updated_at is not None


def test_list_drafts_filters(storage: Storage) -> None:
    storage.save_draft(_draft(city_slug="london"))
    storage.save_draft(_draft(city_slug="tokyo"))
    storage.save_draft(_draft(city_slug="tokyo", status=DraftStatus.PUBLISHED))

    assert len(storage.list_drafts()) == 3
    assert len(storage.list_drafts(city_slug="tokyo")) == 2
    assert len(storage.list_drafts(status=DraftStatus.PUBLISHED.value)) == 1


def test_delete_draft(storage: Storage) -> None:
    draft = storage.save_draft(_draft())
    assert storage.delete_draft(draft.id) is True
    assert storage.get_draft(draft.id) is None
    assert storage.delete_draft(draft.id) is False


def test_job_roundtrip(storage: Storage) -> None:
    job = storage.save_job(Job(kind="generate", draft_id="abc", status=JobStatus.RUNNING))
    fetched = storage.get_job(job.id)
    assert fetched is not None
    assert fetched.kind == "generate"
    assert fetched.status is JobStatus.RUNNING
    assert len(storage.list_jobs(draft_id="abc")) == 1


def test_schedule_roundtrip_and_enabled_filter(storage: Storage) -> None:
    storage.save_schedule(
        Schedule(
            city_slug="berlin",
            cadence=ScheduleCadence.WEEKLY,
            window=TimeWindow.WEEK,
            targets=[Platform.INSTAGRAM],
            enabled=True,
        )
    )
    storage.save_schedule(
        Schedule(
            city_slug="mumbai",
            cadence=ScheduleCadence.MONTHLY,
            window=TimeWindow.MONTH,
            enabled=False,
        )
    )
    assert len(storage.list_schedules()) == 2
    assert len(storage.list_schedules(enabled_only=True)) == 1


def test_persistence_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "persist.db"
    first = Storage(db)
    draft = first.save_draft(_draft())
    # New Storage instance, same file
    second = Storage(db)
    assert second.get_draft(draft.id) is not None
