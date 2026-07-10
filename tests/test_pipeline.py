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

    def test_preselected_events_skips_fetch(self, settings: Settings) -> None:
        from datetime import UTC, datetime

        from events_gen.models import Event

        hand_picked = [
            Event(
                source="manual",
                title="My Event",
                start=datetime(2026, 7, 10, 20, tzinfo=UTC),
                city_slug="tokyo",
            ),
            Event(
                source="manual",
                title="Another",
                start=datetime(2026, 7, 11, 20, tzinfo=UTC),
                city_slug="tokyo",
            ),
        ]
        draft = pipeline.run(
            city_slug="tokyo",
            events=hand_picked,
            storage=Storage(settings.db_path),
            settings=settings,
        )
        assert len(draft.events) == 2
        assert draft.events[0].title == "My Event"
        assert draft.events[1].title == "Another"

    def test_empty_preselected_events_raises(self, settings: Settings) -> None:
        with pytest.raises(pipeline.PipelineError, match="no events selected"):
            pipeline.run(
                city_slug="tokyo",
                events=[],
                storage=Storage(settings.db_path),
                settings=settings,
            )


class TestPrepareAndRenderSplit:
    def test_prepare_draft_has_content_but_no_video(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        draft = pipeline.prepare_draft(
            city_slug="tokyo",
            count=2,
            render_format="reel",
            storage=storage,
            settings=settings,
        )
        assert draft.status is DraftStatus.DRAFT
        assert draft.content is not None
        assert draft.video_path is None
        assert draft.render_format == "reel"
        # It's persisted and reloadable.
        assert storage.get_draft(draft.id) is not None

    def test_render_draft_produces_video_and_ready(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        draft = pipeline.prepare_draft(
            city_slug="tokyo", count=2, storage=storage, settings=settings
        )
        rendered = pipeline.render_draft(draft, storage=storage, settings=settings)
        assert rendered.status is DraftStatus.READY
        assert rendered.video_path is not None
        assert Path(rendered.video_path).exists()

    def test_render_draft_uses_stored_format(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        draft = pipeline.prepare_draft(
            city_slug="tokyo", count=1, render_format="landscape", storage=storage, settings=settings
        )
        rendered = pipeline.render_draft(draft, storage=storage, settings=settings)
        # Landscape output path is named after the landscape format.
        assert "landscape" in Path(rendered.video_path or "").name

    def test_render_draft_without_content_raises(self, settings: Settings) -> None:
        from events_gen.models import PostDraft

        bare = PostDraft(city_slug="tokyo", window=TimeWindow.WEEK, event_count=0)
        with pytest.raises(pipeline.PipelineError, match="no content"):
            pipeline.render_draft(bare, storage=Storage(settings.db_path), settings=settings)

    def test_render_event_preview_produces_segment(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        draft = pipeline.prepare_draft(
            city_slug="tokyo", count=2, storage=storage, settings=settings
        )
        event_id = draft.events[0].id
        seg = pipeline.render_event_preview(draft, event_id, settings=settings)
        assert seg.exists()
        assert seg.stat().st_size > 0
        assert seg.name == f"{event_id}.mp4"

    def test_render_event_preview_unknown_event_raises(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        draft = pipeline.prepare_draft(
            city_slug="tokyo", count=1, storage=storage, settings=settings
        )
        with pytest.raises(pipeline.PipelineError, match="not in draft"):
            pipeline.render_event_preview(draft, "nonexistent", settings=settings)

    def test_render_event_preview_honors_out_path(self, settings: Settings, tmp_path: Path) -> None:
        # A caller-supplied out_path lets the UI file segments under a cache-keyed
        # name so switching source/text reuses prior renders instead of overwriting.
        storage = Storage(settings.db_path)
        draft = pipeline.prepare_draft(
            city_slug="tokyo", count=1, storage=storage, settings=settings
        )
        custom = tmp_path / "seg_signature123.mp4"
        result = pipeline.render_event_preview(
            draft, draft.events[0].id, out_path=custom, settings=settings
        )
        assert result == custom
        assert custom.exists()

    def test_render_thumbnail_options_populates_gallery(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        draft = pipeline.prepare_draft(
            city_slug="tokyo", count=3, storage=storage, settings=settings
        )
        draft = pipeline.render_thumbnail_options(draft, count=10, storage=storage, settings=settings)
        assert len(draft.thumbnail_options) == 10
        assert draft.thumbnail_choice in draft.thumbnail_options
        assert draft.thumbnail_path is not None
        from pathlib import Path as _P

        assert all(_P(p).exists() for p in draft.thumbnail_options.values())

    def test_font_style_survives_render(self, settings: Settings) -> None:
        from events_gen.models import FontStyle

        storage = Storage(settings.db_path)
        draft = pipeline.prepare_draft(
            city_slug="tokyo", count=1, storage=storage, settings=settings
        )
        draft.font_style = FontStyle(title_size=88, title_color="#00ff00", placement="top")
        storage.save_draft(draft)
        rendered = pipeline.render_video_in_place(draft, storage=storage, settings=settings)
        assert rendered.font_style is not None
        assert rendered.font_style.title_color == "#00ff00"
        assert rendered.video_path is not None and Path(rendered.video_path).exists()
