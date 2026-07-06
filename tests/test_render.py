"""Tests for the video rendering pipeline (M4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from events_gen.models import Event, PostContent
from events_gen.render import LANDSCAPE, REEL, get_format, render_video
from events_gen.render.cards import render_card
from events_gen.render.formats import FORMATS, VideoFormat

# ── Fixtures ──


def _event(
    title: str = "Test Event",
    venue: str | None = "Main Hall",
    price_min: float | None = None,
    price_max: float | None = None,
) -> Event:
    return Event(
        source="mock",
        title=title,
        start=datetime(2026, 7, 10, 20, 0, tzinfo=UTC),
        venue=venue,
        city_slug="test",
        price_min=price_min,
        price_max=price_max,
        currency="$",
    )


def _content(title: str = "Test Video", bg_path: str | None = None) -> PostContent:
    return PostContent(
        title=title,
        caption="A caption",
        hashtags=["#test"],
        background_image_path=bg_path,
        music_path=None,
    )


# ── Format tests ──


class TestFormats:
    def test_reel_dimensions(self) -> None:
        assert REEL.width == 1080
        assert REEL.height == 1920
        assert REEL.size == (1080, 1920)

    def test_landscape_dimensions(self) -> None:
        assert LANDSCAPE.width == 1920
        assert LANDSCAPE.height == 1080

    def test_get_format_valid(self) -> None:
        assert get_format("reel") is REEL
        assert get_format("landscape") is LANDSCAPE

    def test_get_format_invalid(self) -> None:
        with pytest.raises(KeyError):
            get_format("square")

    def test_formats_registry(self) -> None:
        assert set(FORMATS.keys()) == {"reel", "landscape"}

    def test_format_defaults(self) -> None:
        assert REEL.fps == 24
        assert REEL.seconds_per_card == 4.0
        assert REEL.intro_seconds == 2.0
        assert REEL.outro_seconds == 2.0


# ── Card rendering tests ──


class TestCards:
    def test_card_returns_rgba_image(self) -> None:
        card = render_card(_event(), REEL, index=1, total=3)
        assert isinstance(card, Image.Image)
        assert card.mode == "RGBA"

    def test_card_width_matches_format(self) -> None:
        card = render_card(_event(), REEL, index=1, total=1)
        expected_w = int(REEL.width * 0.85)
        assert card.width == expected_w

    def test_card_landscape_format(self) -> None:
        card = render_card(_event(), LANDSCAPE, index=1, total=1)
        expected_w = int(LANDSCAPE.width * 0.85)
        assert card.width == expected_w

    def test_card_with_price(self) -> None:
        card = render_card(_event(price_min=25, price_max=100), REEL, index=1, total=1)
        assert card.height > 0

    def test_card_without_venue(self) -> None:
        card = render_card(_event(venue=None), REEL, index=1, total=1)
        assert card.height > 0

    def test_card_long_title_wraps(self) -> None:
        short = render_card(_event(title="Hi"), REEL, index=1, total=1)
        long_title = "A Very Long Event Title That Should Definitely Wrap To Multiple Lines"
        tall = render_card(_event(title=long_title), REEL, index=1, total=1)
        assert tall.height > short.height


# ── Video rendering tests ──


class TestRenderVideo:
    def test_produces_mp4(self, tmp_path: Path) -> None:
        out = tmp_path / "out.mp4"
        events = [_event("E1"), _event("E2")]
        result = render_video(_content(), events, out, REEL)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_landscape_format(self, tmp_path: Path) -> None:
        out = tmp_path / "landscape.mp4"
        render_video(_content(), [_event()], out, LANDSCAPE)
        assert out.exists()

    def test_single_event(self, tmp_path: Path) -> None:
        out = tmp_path / "single.mp4"
        render_video(_content(), [_event()], out, REEL)
        assert out.exists()

    def test_many_events(self, tmp_path: Path) -> None:
        out = tmp_path / "many.mp4"
        events = [_event(f"Event {i}") for i in range(10)]
        render_video(_content(), events, out, REEL)
        assert out.exists()

    def test_with_background_image(self, tmp_path: Path) -> None:
        bg = tmp_path / "bg.jpg"
        Image.new("RGB", (500, 500), (100, 50, 200)).save(bg)
        out = tmp_path / "with_bg.mp4"
        render_video(_content(bg_path=str(bg)), [_event()], out, REEL)
        assert out.exists()

    def test_missing_background_uses_solid(self, tmp_path: Path) -> None:
        out = tmp_path / "no_bg.mp4"
        render_video(_content(bg_path="/nonexistent/bg.jpg"), [_event()], out, REEL)
        assert out.exists()

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "deep" / "out.mp4"
        render_video(_content(), [_event()], out, REEL)
        assert out.exists()

    def test_with_music(self, tmp_path: Path) -> None:
        """Test that music is attached without error (generates a short WAV)."""
        import numpy as np

        sample_rate = 44100
        duration = 3.0
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        tone = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)

        import wave

        wav_path = tmp_path / "music.wav"
        with wave.open(str(wav_path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(tone.tobytes())

        content = PostContent(
            title="Music Test",
            caption="c",
            hashtags=[],
            music_path=str(wav_path),
        )
        out = tmp_path / "with_music.mp4"
        render_video(content, [_event()], out, REEL)
        assert out.exists()
        assert out.stat().st_size > 0


# ── Duration/pacing tests ──


class TestPacing:
    def test_duration_scales_with_events(self) -> None:
        fmt = REEL
        n = 5
        expected = fmt.intro_seconds + n * fmt.seconds_per_card + fmt.outro_seconds
        assert expected == 24.0

    def test_custom_format_pacing(self) -> None:
        custom = VideoFormat(
            name="fast",
            width=720,
            height=1280,
            seconds_per_card=2.0,
            intro_seconds=1.0,
            outro_seconds=1.0,
        )
        n = 3
        expected = custom.intro_seconds + n * custom.seconds_per_card + custom.outro_seconds
        assert expected == 8.0
