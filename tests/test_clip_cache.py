"""Tests for the per-(draft, event, source) clip cache + source resolver."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from events_gen.content import clip_cache
from events_gen.models import Event, PostContent, PostDraft, TimeWindow
from events_gen.settings import Settings


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, EG_DATA_DIR=str(tmp_path / "data"))  # type: ignore[call-arg]


# ── clip_cache ──


class TestClipCache:
    def test_miss_returns_none(self, settings: Settings) -> None:
        assert clip_cache.get_cached(settings, "d1", "e1", "stock") is None

    def test_store_then_hit(self, settings: Settings, tmp_path: Path) -> None:
        src = tmp_path / "src.mp4"
        src.write_bytes(b"video-bytes")
        stored = clip_cache.store_clip(settings, "d1", "e1", "stock", src)
        assert stored.exists()
        hit = clip_cache.get_cached(settings, "d1", "e1", "stock")
        assert hit == stored

    def test_sources_isolated(self, settings: Settings, tmp_path: Path) -> None:
        src = tmp_path / "src.mp4"
        src.write_bytes(b"x")
        clip_cache.store_clip(settings, "d1", "e1", "stock", src)
        # Different source → separate slot, still a miss.
        assert clip_cache.get_cached(settings, "d1", "e1", "wikimedia") is None

    def test_clear_draft_cache(self, settings: Settings, tmp_path: Path) -> None:
        src = tmp_path / "src.mp4"
        src.write_bytes(b"x")
        clip_cache.store_clip(settings, "d1", "e1", "stock", src)
        clip_cache.clear_draft_cache(settings, "d1")
        assert clip_cache.get_cached(settings, "d1", "e1", "stock") is None

    def test_empty_file_is_miss(self, settings: Settings, tmp_path: Path) -> None:
        src = tmp_path / "empty.mp4"
        src.write_bytes(b"")
        clip_cache.store_clip(settings, "d1", "e1", "stock", src)
        assert clip_cache.get_cached(settings, "d1", "e1", "stock") is None


# ── resolve_event_sources ──


def _draft() -> PostDraft:
    ev = Event(
        id="e1",
        source="tm",
        title="Show",
        start=datetime(2026, 7, 8, tzinfo=UTC),
        venue="Hall",
        city_slug="tokyo",
    )
    return PostDraft(
        city_slug="tokyo",
        window=TimeWindow.WEEK,
        event_count=1,
        events=[ev],
        content=PostContent(title="T", caption="c", hashtags=[]),
    )


class TestResolveEventSources:
    def test_upload_uses_the_file(self, settings: Settings, tmp_path: Path) -> None:
        # Point registry at a config with tokyo so get_city works.
        import yaml

        from events_gen import pipeline

        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "cities.yaml").write_text(
            yaml.safe_dump(
                {
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
            )
        )
        (cfg / "event_types.yaml").write_text(yaml.safe_dump({"event_types": []}))
        s = Settings(  # type: ignore[call-arg]
            _env_file=None, EG_DATA_DIR=str(tmp_path / "data"), EG_CONFIG_DIR=str(cfg)
        )
        from events_gen.storage import Storage

        storage = Storage(s.db_path)
        draft = storage.save_draft(_draft())
        upload = tmp_path / "myclip.mp4"
        upload.write_bytes(b"my-uploaded-video")

        result = pipeline.resolve_event_sources(
            draft, {"e1": "upload"}, {"e1": upload}, storage=storage, settings=s
        )
        assert result.content is not None
        assert "e1" in result.content.event_video_clips
        assert result.content.event_clip_sources["e1"] == "upload"

    def test_promo_sets_override(self, settings: Settings, tmp_path: Path) -> None:
        import yaml

        from events_gen import pipeline

        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "cities.yaml").write_text(
            yaml.safe_dump(
                {
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
            )
        )
        (cfg / "event_types.yaml").write_text(yaml.safe_dump({"event_types": []}))
        s = Settings(  # type: ignore[call-arg]
            _env_file=None, EG_DATA_DIR=str(tmp_path / "data"), EG_CONFIG_DIR=str(cfg)
        )
        from events_gen.storage import Storage

        storage = Storage(s.db_path)
        draft = storage.save_draft(_draft())
        result = pipeline.resolve_event_sources(
            draft, {"e1": "promo"}, {}, storage=storage, settings=s
        )
        assert result.content is not None
        assert result.content.event_background_overrides["e1"] == "promo"
        assert result.content.event_clip_sources["e1"] == "promo"

    def test_link_source_uses_resolved_clip(
        self, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import yaml

        from events_gen import pipeline
        from events_gen.content import video_clips
        from events_gen.storage import Storage

        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "cities.yaml").write_text(
            yaml.safe_dump(
                {
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
            )
        )
        (cfg / "event_types.yaml").write_text(yaml.safe_dump({"event_types": []}))
        s = Settings(  # type: ignore[call-arg]
            _env_file=None, EG_DATA_DIR=str(tmp_path / "data"), EG_CONFIG_DIR=str(cfg)
        )
        storage = Storage(s.db_path)
        draft = storage.save_draft(_draft())

        # Stub the fetch so no network/ffmpeg runs; it "downloads" a fake clip.
        fake_clip = tmp_path / "resolved.mp4"
        fake_clip.write_bytes(b"resolved-video")

        def fake_fetch(link, out_dir, event_id, duration, **kw):  # type: ignore[no-untyped-def]
            return (fake_clip, "https://cdn.example/x.mp4")

        monkeypatch.setattr(video_clips, "fetch_link_clip", fake_fetch)

        result = pipeline.resolve_event_sources(
            draft,
            {"e1": "link"},
            links={"e1": "https://cdn.example/x.mp4"},
            storage=storage,
            settings=s,
        )
        assert result.content is not None
        assert "e1" in result.content.event_video_clips
        assert result.content.event_clip_sources["e1"] == "link"

    def test_bad_link_keeps_previous_background(
        self, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import yaml

        from events_gen import pipeline
        from events_gen.content import video_clips
        from events_gen.content.video_clips import ClipLinkError
        from events_gen.storage import Storage

        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "cities.yaml").write_text(
            yaml.safe_dump(
                {
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
            )
        )
        (cfg / "event_types.yaml").write_text(yaml.safe_dump({"event_types": []}))
        s = Settings(  # type: ignore[call-arg]
            _env_file=None, EG_DATA_DIR=str(tmp_path / "data"), EG_CONFIG_DIR=str(cfg)
        )
        storage = Storage(s.db_path)
        draft = storage.save_draft(_draft())

        def bad_fetch(link, out_dir, event_id, duration, **kw):  # type: ignore[no-untyped-def]
            raise ClipLinkError("copyrighted")

        monkeypatch.setattr(video_clips, "fetch_link_clip", bad_fetch)

        result = pipeline.resolve_event_sources(
            draft, {"e1": "link"}, links={"e1": "https://youtube.com/x"}, storage=storage, settings=s
        )
        assert result.content is not None
        # No clip set; the ClipLinkError was caught (not raised) — best-effort.
        assert "e1" not in result.content.event_video_clips
