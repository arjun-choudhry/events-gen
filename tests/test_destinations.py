"""Tests for M13: per-city destinations (storage, publish routing)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from events_gen.models import Destination, Event, Platform, PostContent, PostDraft
from events_gen.publish import publish_draft
from events_gen.settings import Settings
from events_gen.storage import Storage


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, EG_DATA_DIR=str(tmp_path / "data"))  # type: ignore[call-arg]


def _rendered_draft(tmp_path: Path) -> PostDraft:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
    return PostDraft(
        city_slug="tokyo",
        window="week",  # type: ignore[arg-type]
        event_count=1,
        events=[
            Event(
                source="mock", title="X", start=datetime(2026, 7, 8, tzinfo=UTC), city_slug="tokyo"
            )
        ],
        content=PostContent(title="T", caption="c", hashtags=[]),
        video_path=str(video),
    )


# ── Storage CRUD ──


class TestDestinationStorage:
    def test_save_and_list(self, tmp_path: Path) -> None:
        storage = Storage(tmp_path / "db.sqlite")
        d = storage.save_destination(
            Destination(city_slug="nyc", label="NYC Main", platform=Platform.YOUTUBE)
        )
        assert d.created_at is not None
        dests = storage.list_destinations(city_slug="nyc")
        assert len(dests) == 1
        assert dests[0].label == "NYC Main"

    def test_list_by_city(self, tmp_path: Path) -> None:
        storage = Storage(tmp_path / "db.sqlite")
        storage.save_destination(Destination(city_slug="nyc", label="A", platform=Platform.YOUTUBE))
        storage.save_destination(
            Destination(city_slug="tokyo", label="B", platform=Platform.INSTAGRAM)
        )
        assert len(storage.list_destinations(city_slug="nyc")) == 1
        assert len(storage.list_destinations()) == 2

    def test_delete(self, tmp_path: Path) -> None:
        storage = Storage(tmp_path / "db.sqlite")
        d = storage.save_destination(
            Destination(city_slug="nyc", label="X", platform=Platform.YOUTUBE)
        )
        assert storage.delete_destination(d.id) is True
        assert storage.get_destination(d.id) is None


# ── Publish routing with destinations ──


class TestPublishWithDestinations:
    def test_dry_run_per_destination(self, settings: Settings, tmp_path: Path) -> None:
        storage = Storage(settings.db_path)
        draft = _rendered_draft(tmp_path)
        dest1 = Destination(city_slug="tokyo", label="YT1", platform=Platform.YOUTUBE)
        dest2 = Destination(city_slug="tokyo", label="IG1", platform=Platform.INSTAGRAM)
        results = publish_draft(
            draft, destinations=[dest1, dest2], dry_run=True, storage=storage, settings=settings
        )
        assert len(results) == 2
        assert results[0].destination_id == dest1.id
        assert results[1].destination_id == dest2.id
        assert all(r.success for r in results)

    def test_results_tracked_per_destination(self, settings: Settings, tmp_path: Path) -> None:
        storage = Storage(settings.db_path)
        draft = _rendered_draft(tmp_path)
        dest = Destination(city_slug="tokyo", label="YT", platform=Platform.YOUTUBE)
        publish_draft(draft, destinations=[dest], dry_run=True, storage=storage, settings=settings)
        reloaded = storage.get_draft(draft.id)
        assert reloaded is not None
        assert reloaded.results[0].destination_id == dest.id

    def test_fallback_to_global_without_destinations(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        storage = Storage(settings.db_path)
        draft = _rendered_draft(tmp_path)
        results = publish_draft(
            draft, targets=[Platform.YOUTUBE], dry_run=True, storage=storage, settings=settings
        )
        assert len(results) == 1
        assert results[0].destination_id is None  # global path, no destination

    def test_multi_youtube_destinations(self, settings: Settings, tmp_path: Path) -> None:
        storage = Storage(settings.db_path)
        draft = _rendered_draft(tmp_path)
        dest1 = Destination(city_slug="nyc", label="YT Channel 1", platform=Platform.YOUTUBE)
        dest2 = Destination(city_slug="nyc", label="YT Channel 2", platform=Platform.YOUTUBE)
        results = publish_draft(
            draft, destinations=[dest1, dest2], dry_run=True, storage=storage, settings=settings
        )
        assert len(results) == 2
        ids = {r.destination_id for r in results}
        assert ids == {dest1.id, dest2.id}
