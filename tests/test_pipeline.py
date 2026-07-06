"""Tests for the end-to-end generation pipeline (M5)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from events_gen import pipeline
from events_gen.models import DraftStatus, Platform, TimeWindow
from events_gen.settings import Settings
from events_gen.storage import Storage

CITIES_YAML = {
    "cities": [
        {
            "slug": "tokyo",
            "name": "Tokyo",
            "country": "Japan",
            "country_code": "JP",
            "timezone": "Asia/Tokyo",
            "latitude": 35.68,
            "longitude": 139.65,
        }
    ]
}

EVENT_TYPES_YAML = {
    "event_types": [
        {"slug": "music", "name": "Music"},
        {"slug": "arts", "name": "Arts"},
    ]
}


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cities.yaml").write_text(yaml.safe_dump(CITIES_YAML))
    (config_dir / "event_types.yaml").write_text(yaml.safe_dump(EVENT_TYPES_YAML))
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        EG_DATA_DIR=str(tmp_path / "data"),
        EG_CONFIG_DIR=str(config_dir),
        EG_ASSETS_DIR=str(tmp_path / "assets"),
    )


class TestPipelineRun:
    def test_produces_ready_draft(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        draft = pipeline.run(
            city_slug="tokyo",
            window=TimeWindow.WEEK,
            count=3,
            storage=storage,
            settings=settings,
        )
        assert draft.status is DraftStatus.READY
        assert draft.city_slug == "tokyo"
        assert draft.content is not None
        assert draft.video_path is not None
        assert Path(draft.video_path).exists()
        assert 0 < len(draft.events) <= 3

    def test_draft_is_persisted(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        draft = pipeline.run(city_slug="tokyo", count=2, storage=storage, settings=settings)
        reloaded = storage.get_draft(draft.id)
        assert reloaded is not None
        assert reloaded.id == draft.id
        assert reloaded.video_path == draft.video_path

    def test_progress_callback_invoked(self, settings: Settings) -> None:
        messages: list[str] = []
        pipeline.run(
            city_slug="tokyo",
            count=2,
            storage=Storage(settings.db_path),
            settings=settings,
            progress=messages.append,
        )
        assert messages
        assert any("event" in m.lower() for m in messages)

    def test_targets_stored_on_draft(self, settings: Settings) -> None:
        draft = pipeline.run(
            city_slug="tokyo",
            count=2,
            targets=[Platform.YOUTUBE, Platform.INSTAGRAM],
            storage=Storage(settings.db_path),
            settings=settings,
        )
        assert draft.targets == [Platform.YOUTUBE, Platform.INSTAGRAM]

    def test_landscape_format(self, settings: Settings) -> None:
        draft = pipeline.run(
            city_slug="tokyo",
            count=2,
            render_format="landscape",
            storage=Storage(settings.db_path),
            settings=settings,
        )
        assert draft.video_path is not None
        assert "landscape" in draft.video_path

    def test_unknown_city_raises(self, settings: Settings) -> None:
        from events_gen.registry import RegistryError

        with pytest.raises(RegistryError):
            pipeline.run(city_slug="atlantis", storage=Storage(settings.db_path), settings=settings)
