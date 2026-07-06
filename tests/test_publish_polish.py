"""Tests for M14: pre-publish validation + configurable YouTube privacy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from events_gen.models import Event, PostContent, PostDraft
from events_gen.publish.base import validate_draft
from events_gen.publish.youtube import YouTubePublisher
from events_gen.settings import Settings


def _draft(tmp_path: Path, **overrides: object) -> PostDraft:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    base: dict[str, object] = {
        "city_slug": "x",
        "window": "week",
        "event_count": 1,
        "events": [
            Event(source="mock", title="E", start=datetime(2026, 7, 8, tzinfo=UTC), city_slug="x")
        ],
        "content": PostContent(title="T", caption="Short caption", hashtags=["#a", "#b"]),
        "video_path": str(video),
    }
    base.update(overrides)
    return PostDraft(**base)  # type: ignore[arg-type]


# ── Validation ──


class TestValidation:
    def test_valid_draft_returns_empty(self, tmp_path: Path) -> None:
        assert validate_draft(_draft(tmp_path)) == []

    def test_no_video_path(self, tmp_path: Path) -> None:
        issues = validate_draft(_draft(tmp_path, video_path=None))
        assert any("no rendered" in i.lower() for i in issues)

    def test_missing_video_file(self, tmp_path: Path) -> None:
        issues = validate_draft(_draft(tmp_path, video_path="/nope/gone.mp4"))
        assert any("missing" in i.lower() for i in issues)

    def test_no_content(self, tmp_path: Path) -> None:
        issues = validate_draft(_draft(tmp_path, content=None))
        assert any("no content" in i.lower() for i in issues)

    def test_caption_too_long_for_ig(self, tmp_path: Path) -> None:
        long_caption = "x" * 2300
        content = PostContent(title="T", caption=long_caption, hashtags=[])
        issues = validate_draft(_draft(tmp_path, content=content))
        assert any("instagram" in i.lower() and "2200" in i for i in issues)

    def test_too_many_hashtags(self, tmp_path: Path) -> None:
        content = PostContent(title="T", caption="c", hashtags=[f"#{i}" for i in range(35)])
        issues = validate_draft(_draft(tmp_path, content=content))
        assert any("hashtag" in i.lower() for i in issues)


# ── YouTube privacy ──


class TestYouTubePrivacy:
    def test_default_is_unlisted(self) -> None:
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        yt = YouTubePublisher(settings=s)
        assert yt.privacy_status == "unlisted"

    def test_override_from_settings(self) -> None:
        s = Settings(_env_file=None, EG_YOUTUBE_PRIVACY="public")  # type: ignore[call-arg]
        yt = YouTubePublisher(settings=s)
        assert yt.privacy_status == "public"

    def test_explicit_param_overrides_settings(self) -> None:
        s = Settings(_env_file=None, EG_YOUTUBE_PRIVACY="public")  # type: ignore[call-arg]
        yt = YouTubePublisher(settings=s, privacy_status="private")
        assert yt.privacy_status == "private"
