"""Video format presets.

Each preset defines resolution, aspect ratio, and pacing parameters for a
target platform. The renderer picks a preset by name (from the CLI or UI).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VideoFormat:
    """Immutable specification for a video render target."""

    name: str
    width: int
    height: int
    fps: int = 24
    seconds_per_card: float = 4.0
    intro_seconds: float = 2.0
    outro_seconds: float = 2.0

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


REEL = VideoFormat(name="reel", width=1080, height=1920)
LANDSCAPE = VideoFormat(name="landscape", width=1920, height=1080)
REEL_4K = VideoFormat(name="reel_4k", width=2160, height=3840)
LANDSCAPE_4K = VideoFormat(name="landscape_4k", width=3840, height=2160)

FORMATS: dict[str, VideoFormat] = {
    "reel": REEL,
    "landscape": LANDSCAPE,
    "reel_4k": REEL_4K,
    "landscape_4k": LANDSCAPE_4K,
}


def get_format(name: str) -> VideoFormat:
    """Lookup a format by name; raises KeyError if unknown."""
    return FORMATS[name]
