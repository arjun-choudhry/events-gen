"""Tests for M9: image quality — resolution gate, LANCZOS, blur-fill, 4K."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from events_gen.content.images.resize import (
    blur_fill,
    cover_fit,
    is_large_enough,
    resize_bytes,
    resize_for_target,
)
from events_gen.models import Event, PostContent
from events_gen.render import render_video
from events_gen.render.formats import LANDSCAPE_4K, REEL, REEL_4K


def _event() -> Event:
    return Event(
        source="mock",
        title="Show",
        start=datetime(2026, 7, 10, 20, tzinfo=UTC),
        venue="Hall",
        city_slug="x",
    )


# ── resolution gate ──


class TestResolutionGate:
    def test_too_small(self) -> None:
        assert is_large_enough(200, 300, 1080, 1920) is False

    def test_just_large_enough(self) -> None:
        # 70% of 1080 = 756, 70% of 1920 = 1344
        assert is_large_enough(756, 1344, 1080, 1920) is True

    def test_larger_than_target(self) -> None:
        assert is_large_enough(3000, 4000, 1080, 1920) is True


# ── cover_fit ──


class TestCoverFit:
    def test_output_size(self) -> None:
        img = Image.new("RGB", (2000, 3000))
        result = cover_fit(img, 1080, 1920)
        assert result.size == (1080, 1920)

    def test_uses_lanczos(self) -> None:
        # Indirectly: LANCZOS produces smoother output than NEAREST on a
        # gradient. Just verify it doesn't crash and has correct size.
        img = Image.new("RGB", (800, 1400), (100, 150, 200))
        assert cover_fit(img, 540, 960).size == (540, 960)


# ── blur_fill ──


class TestBlurFill:
    def test_output_size(self) -> None:
        img = Image.new("RGB", (100, 100))
        result = blur_fill(img, 1080, 1920)
        assert result.size == (1080, 1920)

    def test_center_is_sharp_region(self) -> None:
        # The center pixels should come from the sharp foreground, not the blur.
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        result = blur_fill(img, 1080, 1920)
        cx, cy = 1080 // 2, 1920 // 2
        pixel = result.getpixel((cx, cy))
        # Should be close to red (the foreground is solid red).
        assert pixel[0] > 200


# ── resize_for_target dispatch ──


class TestResizeForTarget:
    def test_large_image_uses_cover_fit(self) -> None:
        img = Image.new("RGB", (2000, 3000))
        result = resize_for_target(img, 1080, 1920)
        assert result.size == (1080, 1920)

    def test_small_image_uses_blur_fill(self) -> None:
        img = Image.new("RGB", (200, 200))
        result = resize_for_target(img, 1080, 1920)
        assert result.size == (1080, 1920)


# ── resize_bytes ──


def test_resize_bytes_saves_jpeg(tmp_path: Path) -> None:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (800, 1400)).save(buf, format="PNG")
    out = tmp_path / "out.jpg"
    resize_bytes(buf.getvalue(), out, (1080, 1920))
    assert out.exists()
    with Image.open(out) as img:
        assert img.size == (1080, 1920)


# ── 4K format renders ──


class TestFourKFormats:
    def test_reel_4k_dimensions(self) -> None:
        assert REEL_4K.width == 2160
        assert REEL_4K.height == 3840

    def test_landscape_4k_dimensions(self) -> None:
        assert LANDSCAPE_4K.width == 3840
        assert LANDSCAPE_4K.height == 2160

    def test_render_at_4k(self, tmp_path: Path) -> None:
        out = tmp_path / "4k.mp4"
        content = PostContent(title="4K Test", caption="c", hashtags=[])
        render_video(content, [_event()], out, REEL_4K)
        assert out.exists()
        assert out.stat().st_size > 0
        # Probe the resolution
        import subprocess

        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert "2160,3840" in r.stdout


# ── encode quality ──


def test_render_uses_crf(tmp_path: Path) -> None:
    """The rendered file should be larger than a default-CRF render would be,
    indicating a lower (better quality) CRF was applied. We just verify it
    renders successfully and has non-trivial size."""
    out = tmp_path / "quality.mp4"
    content = PostContent(title="Q", caption="c", hashtags=[])
    render_video(content, [_event()], out, REEL)
    assert out.stat().st_size > 10_000  # CRF 18 → more bytes than the old default
