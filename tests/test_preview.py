"""Tests for instant per-event still previews (render/preview.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from events_gen.models import Event, FontStyle, PostContent
from events_gen.render import (
    REEL,
    available_fonts,
    render_event_segment,
    render_event_still,
    render_thumbnail,
    render_thumbnail_variants,
)
from events_gen.render.preview import THUMBNAIL_LAYOUTS


def _event(title: str = "Jazz Night") -> Event:
    return Event(
        source="mock",
        title=title,
        start=datetime(2026, 7, 10, 20, 0, tzinfo=UTC),
        venue="Blue Note",
        city_slug="nyc",
        price_min=25.0,
        currency="$",
    )


def _content(bg_path: str | None = None) -> PostContent:
    return PostContent(
        title="This Week in NYC",
        caption="c",
        hashtags=[],
        background_image_path=bg_path,
    )


class TestRenderEventStill:
    def test_returns_full_frame_rgb(self) -> None:
        img = render_event_still(_content(), _event(), 1, 5, fmt=REEL)
        assert img.size == REEL.size
        assert img.mode == "RGB"

    def test_each_text_style_renders(self) -> None:
        for style in ("panel", "outline", "shadow"):
            img = render_event_still(_content(), _event(), 1, 3, fmt=REEL, text_style=style)
            assert img.size == REEL.size

    def test_font_style_drives_preview(self) -> None:
        # A FontStyle applied to the still preview (used for the live font pane).
        fs = FontStyle(
            title_size=100, title_color="#ff3366", placement="bottom", text_style="shadow"
        )
        img = render_event_still(_content(), _event(), 1, 3, fmt=REEL, font_style=fs)
        assert img.size == REEL.size
        assert img.mode == "RGB"

    def test_uses_shared_background_image(self, tmp_path: Path) -> None:
        bg = tmp_path / "bg.jpg"
        Image.new("RGB", (1200, 2000), (10, 120, 200)).save(bg)
        img = render_event_still(_content(str(bg)), _event(), 1, 1, fmt=REEL)
        # A blue-ish background should dominate the top strip (above the centered card).
        top_pixel = img.getpixel((img.width // 2, 40))
        assert top_pixel[2] > top_pixel[0]  # more blue than red

    def test_solid_fill_when_no_background(self) -> None:
        # No background path and no per-event assets → solid theme fill, still valid.
        img = render_event_still(_content(), _event(), 2, 4, fmt=REEL)
        assert img.size == REEL.size

    def test_promo_override_without_url_falls_back(self) -> None:
        content = _content()
        ev = _event()
        content.event_background_overrides[ev.id] = "promo"  # but event has no image_url
        img = render_event_still(content, ev, 1, 1, fmt=REEL)
        assert img.size == REEL.size  # falls back to solid fill, no crash


class TestRenderEventSegment:
    def test_produces_playable_video(self, tmp_path: Path) -> None:
        out = tmp_path / "seg.mp4"
        result = render_event_segment(_content(), _event(), 1, 3, out, REEL)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_uses_shared_background(self, tmp_path: Path) -> None:
        bg = tmp_path / "bg.jpg"
        Image.new("RGB", (1200, 2000), (20, 80, 160)).save(bg)
        out = tmp_path / "seg.mp4"
        render_event_segment(_content(str(bg)), _event(), 1, 1, out, REEL, text_style="outline")
        assert out.exists()

    def test_each_text_style(self, tmp_path: Path) -> None:
        for style in ("panel", "outline", "shadow"):
            out = tmp_path / f"{style}.mp4"
            render_event_segment(_content(), _event(), 1, 2, out, REEL, text_style=style)
            assert out.exists()


class TestRenderThumbnail:
    def test_produces_jpeg(self, tmp_path: Path) -> None:
        out = tmp_path / "thumb.jpg"
        result = render_thumbnail(_content(), [_event()], out, fmt=REEL)
        assert result == out
        assert out.exists()
        img = Image.open(out)
        assert img.size == REEL.size

    def test_output_is_full_resolution_and_high_quality(self, tmp_path: Path) -> None:
        # Supersampled + quality-95 render: exact target dims and a non-trivial file
        # size (a pixelated low-quality JPEG at this resolution would be far smaller).
        out = tmp_path / "thumb.jpg"
        render_thumbnail(_content(), [_event()], out, fmt=REEL, title="Crisp Headline Test")
        img = Image.open(out)
        assert img.size == REEL.size
        assert out.stat().st_size > 20_000

    def test_title_override(self, tmp_path: Path) -> None:
        # A custom headline renders without error (visual text not asserted).
        out = tmp_path / "thumb.jpg"
        render_thumbnail(_content(), [_event()], out, fmt=REEL, title="CUSTOM HEADLINE")
        assert out.exists()

    def test_handles_no_events(self, tmp_path: Path) -> None:
        out = tmp_path / "thumb.jpg"
        render_thumbnail(_content(), [], out, fmt=REEL)
        assert out.exists()  # solid-fill fallback, no crash

    def test_each_layout_renders(self, tmp_path: Path) -> None:
        for layout in THUMBNAIL_LAYOUTS:
            out = tmp_path / f"{layout}.jpg"
            render_thumbnail(_content(), [_event()], out, fmt=REEL, layout=layout)
            assert out.exists()

    def test_font_style_applied(self, tmp_path: Path) -> None:
        fonts = available_fonts()
        fp = next(iter(fonts.values())) if fonts else None
        fs = FontStyle(font_path=fp, title_color="#ff0000", title_size=80, placement="bottom")
        out = tmp_path / "styled.jpg"
        render_thumbnail(_content(), [_event()], out, fmt=REEL, font_style=fs)
        assert out.exists()


class TestThumbnailVariants:
    def test_generates_requested_count(self, tmp_path: Path) -> None:
        events = [_event("A"), _event("B"), _event("C")]
        variants = render_thumbnail_variants(_content(), events, tmp_path, fmt=REEL, count=10)
        assert len(variants) == 10
        for p in variants.values():
            assert p.exists()

    def test_variants_are_distinct_files(self, tmp_path: Path) -> None:
        variants = render_thumbnail_variants(_content(), [_event()], tmp_path, fmt=REEL, count=6)
        # Distinct output paths (options don't overwrite each other).
        assert len(set(variants.values())) == len(variants)


class TestAvailableFonts:
    def test_returns_name_to_path_map(self) -> None:
        fonts = available_fonts()
        assert isinstance(fonts, dict)
        # Every value is an existing font file path.
        for path in list(fonts.values())[:5]:
            assert Path(path).exists()
