"""Tests for the publishing layer (M6): base, hosting, YouTube, Instagram, orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from events_gen.models import DraftStatus, Event, Platform, PostContent, PostDraft
from events_gen.publish import get_publisher, publish_draft
from events_gen.publish.base import PublishError
from events_gen.publish.hosting import HostingError, VideoHost
from events_gen.publish.instagram import InstagramPublisher
from events_gen.publish.youtube import YouTubePublisher
from events_gen.settings import Settings
from events_gen.storage import Storage


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        EG_DATA_DIR=str(tmp_path / "data"),
    )


def _rendered_draft(tmp_path: Path, **overrides: object) -> PostDraft:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-mp4-bytes")
    base: dict[str, object] = {
        "city_slug": "tokyo",
        "window": "week",
        "event_count": 2,
        "events": [
            Event(
                source="mock",
                title="Show",
                start=datetime(2026, 7, 8, 20, tzinfo=UTC),
                city_slug="tokyo",
            )
        ],
        "content": PostContent(
            title="Tokyo This Week", caption="Great events!", hashtags=["#tokyo", "#events"]
        ),
        "video_path": str(video),
    }
    base.update(overrides)
    return PostDraft(**base)  # type: ignore[arg-type]


# ── base / validation ──


class TestValidation:
    def test_publish_without_video_raises(self, settings: Settings, tmp_path: Path) -> None:
        draft = _rendered_draft(tmp_path, video_path=None)
        yt = YouTubePublisher(settings=settings)
        with pytest.raises(PublishError, match="no rendered video"):
            yt.publish(draft, dry_run=True)

    def test_publish_missing_file_raises(self, settings: Settings, tmp_path: Path) -> None:
        draft = _rendered_draft(tmp_path, video_path="/nope/gone.mp4")
        yt = YouTubePublisher(settings=settings)
        with pytest.raises(PublishError, match="missing on disk"):
            yt.publish(draft, dry_run=True)

    def test_publish_without_content_raises(self, settings: Settings, tmp_path: Path) -> None:
        draft = _rendered_draft(tmp_path, content=None)
        yt = YouTubePublisher(settings=settings)
        with pytest.raises(PublishError, match="no content"):
            yt.publish(draft, dry_run=True)


# ── dry-run ──


class TestDryRun:
    def test_youtube_dry_run(self, settings: Settings, tmp_path: Path) -> None:
        draft = _rendered_draft(tmp_path)
        result = YouTubePublisher(settings=settings).publish(draft, dry_run=True)
        assert result.success
        assert result.platform is Platform.YOUTUBE
        assert result.external_id
        assert result.url and "youtube.com" in result.url

    def test_instagram_dry_run_needs_no_hosting(self, settings: Settings, tmp_path: Path) -> None:
        # dry-run must work even without a public host configured
        draft = _rendered_draft(tmp_path)
        result = InstagramPublisher(settings=settings).publish(draft, dry_run=True)
        assert result.success
        assert result.platform is Platform.INSTAGRAM
        assert result.url and "instagram.com" in result.url


# ── configured gating ──


class TestConfigured:
    def test_youtube_unconfigured_by_default(self, settings: Settings) -> None:
        assert YouTubePublisher(settings=settings).is_configured() is False

    def test_youtube_configured_with_secrets(self, settings: Settings, tmp_path: Path) -> None:
        secrets = tmp_path / "cs.json"
        secrets.write_text("{}")
        s = settings.model_copy(update={"youtube_client_secrets_file": secrets})
        assert YouTubePublisher(settings=s).is_configured() is True

    def test_instagram_configured_needs_both(self, settings: Settings) -> None:
        s = settings.model_copy(
            update={"instagram_access_token": "tok", "instagram_business_account_id": "123"}
        )
        assert InstagramPublisher(settings=s).is_configured() is True
        s2 = settings.model_copy(update={"instagram_access_token": "tok"})
        assert InstagramPublisher(settings=s2).is_configured() is False

    def test_live_publish_unconfigured_raises(self, settings: Settings, tmp_path: Path) -> None:
        draft = _rendered_draft(tmp_path)
        with pytest.raises(PublishError, match="not configured"):
            YouTubePublisher(settings=settings).publish(draft, dry_run=False)


# ── hosting ──


class TestHosting:
    def test_no_base_url_raises(self, settings: Settings) -> None:
        host = VideoHost(settings=settings)
        assert host.is_configured() is False
        with pytest.raises(HostingError):
            host.public_url("/data/output/abc/reel.mp4")

    def test_public_url_uses_relative_layout(self, tmp_path: Path) -> None:
        s = Settings(  # type: ignore[call-arg]
            _env_file=None,
            EG_DATA_DIR=str(tmp_path / "data"),
            EG_PUBLIC_VIDEO_BASE_URL="https://cdn.example.com/vids",
        )
        s.ensure_dirs()
        local = s.output_dir / "draft123" / "reel.mp4"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(b"x")
        url = VideoHost(settings=s).public_url(local)
        assert url == "https://cdn.example.com/vids/draft123/reel.mp4"

    def test_public_url_trims_trailing_slash(self, tmp_path: Path) -> None:
        s = Settings(  # type: ignore[call-arg]
            _env_file=None,
            EG_DATA_DIR=str(tmp_path / "data"),
            EG_PUBLIC_VIDEO_BASE_URL="https://cdn.example.com/",
        )
        url = VideoHost(settings=s).public_url("/elsewhere/reel.mp4")
        assert url == "https://cdn.example.com/reel.mp4"


# ── Instagram two-step flow (mocked HTTP) ──


class TestInstagramFlow:
    def _host(self, settings: Settings) -> VideoHost:
        s = settings.model_copy(update={"public_video_base_url": "https://cdn.example.com"})
        return VideoHost(settings=s)

    def _configured_settings(self, settings: Settings) -> Settings:
        return settings.model_copy(
            update={
                "instagram_access_token": "tok",
                "instagram_business_account_id": "acct",
                "public_video_base_url": "https://cdn.example.com",
            }
        )

    def test_full_flow_success(self, settings: Settings, tmp_path: Path) -> None:
        s = self._configured_settings(settings)
        s.ensure_dirs()
        draft = _rendered_draft(tmp_path)

        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            calls.append(url)
            if url.endswith("/media"):
                return httpx.Response(200, json={"id": "container-1"})
            if "media_publish" in url:
                return httpx.Response(200, json={"id": "media-99"})
            # status poll
            return httpx.Response(200, json={"status_code": "FINISHED"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        pub = InstagramPublisher(
            settings=s, host=VideoHost(settings=s), client=client, poll_interval=0
        )
        result = pub.publish(draft, dry_run=False)

        assert result.success
        assert result.external_id == "media-99"
        assert any("/media" in c for c in calls)
        assert any("media_publish" in c for c in calls)

    def test_container_error_fails(self, settings: Settings, tmp_path: Path) -> None:
        s = self._configured_settings(settings)
        s.ensure_dirs()
        draft = _rendered_draft(tmp_path)

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith("/media"):
                return httpx.Response(200, json={"id": "c1"})
            return httpx.Response(200, json={"status_code": "ERROR"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        pub = InstagramPublisher(settings=s, client=client, poll_interval=0)
        with pytest.raises(PublishError, match="failed to process"):
            pub.publish(draft, dry_run=False)

    def test_live_without_hosting_raises(self, settings: Settings, tmp_path: Path) -> None:
        s = settings.model_copy(
            update={"instagram_access_token": "tok", "instagram_business_account_id": "acct"}
        )
        draft = _rendered_draft(tmp_path)
        with pytest.raises(PublishError, match="public video URL"):
            InstagramPublisher(settings=s).publish(draft, dry_run=False)


# ── orchestrator ──


class TestPublishDraft:
    def test_dry_run_both_targets(self, settings: Settings, tmp_path: Path) -> None:
        storage = Storage(settings.db_path)
        draft = _rendered_draft(tmp_path, targets=[Platform.YOUTUBE, Platform.INSTAGRAM])
        results = publish_draft(draft, dry_run=True, storage=storage, settings=settings)
        assert len(results) == 2
        assert all(r.success for r in results)
        reloaded = storage.get_draft(draft.id)
        assert reloaded is not None
        assert reloaded.status is DraftStatus.PUBLISHED
        assert len(reloaded.results) == 2

    def test_records_history_job(self, settings: Settings, tmp_path: Path) -> None:
        storage = Storage(settings.db_path)
        draft = _rendered_draft(tmp_path)
        publish_draft(
            draft, targets=[Platform.YOUTUBE], dry_run=True, storage=storage, settings=settings
        )
        jobs = storage.list_jobs(draft_id=draft.id)
        assert len(jobs) == 1
        assert jobs[0].kind == "publish"
        assert "dry-run" in (jobs[0].detail or "")

    def test_no_targets_raises(self, settings: Settings, tmp_path: Path) -> None:
        draft = _rendered_draft(tmp_path, targets=[])
        with pytest.raises(PublishError, match="no publish targets"):
            publish_draft(draft, storage=Storage(settings.db_path), settings=settings)

    def test_failure_isolated_and_marked_failed(self, settings: Settings, tmp_path: Path) -> None:
        # YouTube live (unconfigured) fails, but the call returns a result rather than raising.
        storage = Storage(settings.db_path)
        draft = _rendered_draft(tmp_path)
        results = publish_draft(
            draft, targets=[Platform.YOUTUBE], dry_run=False, storage=storage, settings=settings
        )
        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error
        reloaded = storage.get_draft(draft.id)
        assert reloaded is not None
        assert reloaded.status is DraftStatus.FAILED

    def test_get_publisher_maps_platforms(self, settings: Settings) -> None:
        assert isinstance(get_publisher(Platform.YOUTUBE, settings=settings), YouTubePublisher)
        assert isinstance(get_publisher(Platform.INSTAGRAM, settings=settings), InstagramPublisher)
