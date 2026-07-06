"""Tests for per-theme preview rendering + selection (pipeline)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from events_gen import pipeline
from events_gen.models import Event, PostContent, PostDraft, TimeWindow
from events_gen.settings import Settings
from events_gen.storage import Storage


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, EG_DATA_DIR=str(tmp_path / "data"))  # type: ignore[call-arg]


def _finalized_draft() -> PostDraft:
    return PostDraft(
        city_slug="tokyo",
        window=TimeWindow.WEEK,
        event_count=1,
        events=[
            Event(
                source="mock",
                title="Show",
                start=datetime(2026, 7, 8, 20, tzinfo=UTC),
                venue="Hall",
                city_slug="tokyo",
            )
        ],
        content=PostContent(title="Tokyo This Week", caption="c", hashtags=["#tokyo"]),
    )


class TestRenderThemePreviews:
    def test_renders_a_preview_per_theme(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        storage = Storage(s.db_path)
        draft = storage.save_draft(_finalized_draft())
        result = pipeline.render_theme_previews(
            draft, themes=["classic", "neon", "minimal"], storage=storage, settings=s
        )
        assert set(result.theme_previews) == {"classic", "neon", "minimal"}
        for path in result.theme_previews.values():
            assert Path(path).exists()

    def test_defaults_selection_to_first_theme(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        storage = Storage(s.db_path)
        draft = storage.save_draft(_finalized_draft())
        result = pipeline.render_theme_previews(
            draft, themes=["editorial", "bold"], storage=storage, settings=s
        )
        assert result.theme == "editorial"
        assert result.video_path == result.theme_previews["editorial"]

    def test_previews_persisted(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        storage = Storage(s.db_path)
        draft = storage.save_draft(_finalized_draft())
        pipeline.render_theme_previews(draft, themes=["classic"], storage=storage, settings=s)
        reloaded = storage.get_draft(draft.id)
        assert reloaded is not None
        assert "classic" in reloaded.theme_previews

    def test_no_content_raises(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        storage = Storage(s.db_path)
        draft = PostDraft(city_slug="tokyo", window=TimeWindow.WEEK, event_count=1)
        with pytest.raises(pipeline.PipelineError, match="no content"):
            pipeline.render_theme_previews(draft, themes=["classic"], storage=storage, settings=s)

    def test_does_not_override_existing_selection(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        storage = Storage(s.db_path)
        draft = _finalized_draft()
        draft.theme = "sunset"
        draft.video_path = "/somewhere/sunset.mp4"
        storage.save_draft(draft)
        result = pipeline.render_theme_previews(
            draft, themes=["classic", "neon"], storage=storage, settings=s
        )
        # Existing selection preserved (sunset wasn't in the render set).
        assert result.theme == "sunset"


class TestSelectTheme:
    def test_select_updates_current(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        storage = Storage(s.db_path)
        draft = storage.save_draft(_finalized_draft())
        pipeline.render_theme_previews(
            draft, themes=["classic", "neon"], storage=storage, settings=s
        )
        result = pipeline.select_theme(draft, "neon", storage=storage, settings=s)
        assert result.theme == "neon"
        assert result.video_path == result.theme_previews["neon"]

    def test_select_unknown_theme_raises(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        storage = Storage(s.db_path)
        draft = storage.save_draft(_finalized_draft())
        pipeline.render_theme_previews(draft, themes=["classic"], storage=storage, settings=s)
        with pytest.raises(pipeline.PipelineError, match="no preview"):
            pipeline.select_theme(draft, "neon", storage=storage, settings=s)
