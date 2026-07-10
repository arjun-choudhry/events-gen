"""Tests for the video rendering pipeline (M4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from events_gen.models import Event, PostContent
from events_gen.render import LANDSCAPE, REEL, get_format, render_video
from events_gen.render.cards import render_card
from events_gen.render.formats import FORMATS

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
        assert set(FORMATS.keys()) == {"reel", "landscape", "reel_4k", "landscape_4k"}

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

    def test_font_style_override(self, tmp_path: Path) -> None:
        # A single FontStyle applies to all cards (custom font/colors/placement).
        from events_gen.models import FontStyle

        fs = FontStyle(
            title_size=90, title_color="#ff3366", body_color="#ffffff",
            placement="bottom", text_style="shadow", uppercase_titles=True,
        )
        out = tmp_path / "styled.mp4"
        render_video(_content(), [_event("E1"), _event("E2")], out, REEL, font_style=fs)
        assert out.exists()
        assert out.stat().st_size > 0

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
    def test_video_has_no_intro_or_outro(self, tmp_path: Path) -> None:
        # The video now opens straight on the first event: duration == n * card
        # (no title-intro / outro cards). Verify via the rendered file's duration.
        import subprocess

        n = 2
        out = tmp_path / "v.mp4"
        render_video(_content(), [_event(), _event("Second")], out, REEL, animation="none")
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(out)],
            capture_output=True, text=True, check=True,
        )
        assert abs(float(probe.stdout.strip()) - n * REEL.seconds_per_card) < 0.5


# ── Text position (M: placement) ──


class TestTextPosition:
    def test_vertical_anchor_top(self) -> None:
        from events_gen.render.video import _vertical_anchor

        y = _vertical_anchor(REEL, 400, "top")
        assert y == int(REEL.height * 0.08)

    def test_vertical_anchor_bottom(self) -> None:
        from events_gen.render.video import _vertical_anchor

        y = _vertical_anchor(REEL, 400, "bottom")
        assert y == REEL.height - 400 - int(REEL.height * 0.08)

    def test_vertical_anchor_center(self) -> None:
        from events_gen.render.video import _vertical_anchor

        y = _vertical_anchor(REEL, 400, "center")
        assert y == (REEL.height - 400) // 2

    def test_render_with_positions(self, tmp_path: Path) -> None:
        for pos in ("top", "center", "bottom"):
            out = tmp_path / f"{pos}.mp4"
            render_video(_content(), [_event()], out, REEL, text_position=pos)
            assert out.exists()


class TestTextStyle:
    def test_render_with_each_style(self, tmp_path: Path) -> None:
        for style in ("panel", "outline", "shadow"):
            out = tmp_path / f"{style}.mp4"
            render_video(_content(), [_event()], out, REEL, text_style=style)
            assert out.exists()

    def test_panel_style_draws_opaque_scrim(self) -> None:
        # The "panel" style paints an opaque rounded box, so the card has many
        # fully/near-opaque pixels; outline/shadow leave the card mostly transparent.
        panel = render_card(_event(), REEL, index=1, total=1, text_style="panel")
        outline = render_card(_event(), REEL, index=1, total=1, text_style="outline")
        panel_alpha = panel.split()[3]
        outline_alpha = outline.split()[3]
        # The panel scrim fills the whole card with a semi-opaque box; outline only
        # has opaque text/stroke pixels, so far fewer non-transparent pixels.
        panel_filled = sum(1 for a in panel_alpha.getdata() if a > 100)
        outline_filled = sum(1 for a in outline_alpha.getdata() if a > 100)
        assert panel_filled > outline_filled * 3

    def test_outline_style_has_transparent_background(self) -> None:
        # Without a panel, the vast majority of the card is transparent.
        card = render_card(_event(), REEL, index=1, total=1, text_style="outline")
        alpha = card.split()[3]
        transparent = sum(1 for a in alpha.getdata() if a == 0)
        assert transparent > (card.width * card.height) * 0.5
