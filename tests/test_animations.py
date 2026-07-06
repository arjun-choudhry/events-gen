"""Tests for M12: animation presets (Ken Burns, card transitions, hook intro)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from events_gen.models import Event, PostContent
from events_gen.render import REEL, render_video
from events_gen.render.animations import (
    ANIMATIONS,
    get_animation,
    ken_burns_frame,
    slide_up_position,
)


def _event() -> Event:
    return Event(
        source="mock",
        title="Show",
        start=datetime(2026, 7, 10, 20, tzinfo=UTC),
        venue="Hall",
        city_slug="x",
    )


class TestAnimationRegistry:
    def test_three_presets_available(self) -> None:
        assert set(ANIMATIONS.keys()) == {"none", "hype", "cinematic"}

    def test_get_animation_by_name(self) -> None:
        assert get_animation("hype").name == "hype"

    def test_get_animation_unknown_falls_back(self) -> None:
        assert get_animation("bogus").name == "none"

    def test_get_animation_none_falls_back(self) -> None:
        assert get_animation(None).name == "none"

    def test_hype_has_hook(self) -> None:
        assert ANIMATIONS["hype"].hook_enabled is True

    def test_none_has_no_hook(self) -> None:
        assert ANIMATIONS["none"].hook_enabled is False


class TestKenBurnsFrame:
    def test_output_correct_size(self) -> None:
        import numpy as np

        oversized = np.zeros((2150, 1210, 3), dtype=np.uint8)
        frame = ken_burns_frame(oversized, 0.5, 2.0, 1080, 1920, 1.0, 1.12)
        assert frame.shape == (1920, 1080, 3)

    def test_start_and_end_differ(self) -> None:
        import numpy as np

        # A gradient so frames at t=0 and t=end are visibly different.
        h, w = 2150, 1210
        oversized = np.tile(np.arange(w, dtype=np.uint8), (h, 1))[..., None].repeat(3, axis=2)
        frame_start = ken_burns_frame(oversized, 0.0, 2.0, 1080, 1920, 1.0, 1.12)
        frame_end = ken_burns_frame(oversized, 2.0, 2.0, 1080, 1920, 1.0, 1.12)
        # They should differ (zoomed in more at end).
        assert not np.array_equal(frame_start, frame_end)


class TestSlideUpPosition:
    def test_starts_below_center(self) -> None:
        pos_fn = slide_up_position(100, 200, 300, 0.3, 4.0)
        x, y = pos_fn(0.0)
        assert x == 100
        assert y > 200  # below center

    def test_reaches_center_after_enter(self) -> None:
        pos_fn = slide_up_position(100, 200, 300, 0.3, 4.0)
        x, y = pos_fn(0.3)
        assert (x, y) == (100, 200)

    def test_stays_at_center_after_enter(self) -> None:
        pos_fn = slide_up_position(100, 200, 300, 0.3, 4.0)
        assert pos_fn(2.0) == (100, 200)


class TestRenderWithAnimation:
    def test_none_produces_video(self, tmp_path: Path) -> None:
        out = tmp_path / "none.mp4"
        content = PostContent(title="T", caption="c", hashtags=[])
        render_video(content, [_event()], out, REEL, animation="none")
        assert out.exists()

    def test_hype_produces_longer_video(self, tmp_path: Path) -> None:
        out_none = tmp_path / "none.mp4"
        out_hype = tmp_path / "hype.mp4"
        content = PostContent(title="NYC This Week", caption="c", hashtags=[])
        render_video(content, [_event()], out_none, REEL, animation="none")
        render_video(content, [_event()], out_hype, REEL, animation="hype")
        # Hype has a hook → longer duration.
        dur_none = _probe_duration(out_none)
        dur_hype = _probe_duration(out_hype)
        assert dur_hype > dur_none

    def test_cinematic_produces_video(self, tmp_path: Path) -> None:
        out = tmp_path / "cin.mp4"
        content = PostContent(title="T", caption="c", hashtags=[])
        render_video(content, [_event()], out, REEL, animation="cinematic")
        assert out.exists() and out.stat().st_size > 0

    def test_animation_with_theme(self, tmp_path: Path) -> None:
        out = tmp_path / "combo.mp4"
        content = PostContent(title="T", caption="c", hashtags=[])
        render_video(content, [_event()], out, REEL, theme="neon", animation="hype")
        assert out.exists()


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    return float(r.stdout.strip())
