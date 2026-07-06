"""Animation presets for video rendering (M12).

Each :class:`AnimationPreset` defines motion parameters independently of the
visual theme (fonts/colors): background Ken-Burns zoom, card entrance style,
and an optional scroll-stopping hook intro. Three presets ship:

- **"none"** — current behavior: static background, fade-in/out cards.
- **"hype"** — TikTok/Reels-native: fast zoom, slide-up cards, emoji hook.
- **"cinematic"** — polished editorial: subtle Ken Burns, slow fade, elegant hook.

Presets are composable with any visual :class:`Theme`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class AnimationPreset:
    """Motion config for a rendered video."""

    name: str
    description: str
    # Background Ken Burns zoom (1.0 = no motion).
    bg_zoom_start: float = 1.0
    bg_zoom_end: float = 1.0
    # Card entrance: "fade" | "slide_up" | "slide_left"
    card_enter: str = "fade"
    card_enter_duration: float = 0.4
    # Hook intro (short attention-grabbing text before the title card).
    hook_enabled: bool = False
    hook_text_template: str = "{city} — {n} events this week"
    hook_duration: float = 1.5
    hook_zoom: float = 1.0  # >1 = text zooms in from larger


# ── Preset registry ──


ANIMATIONS: dict[str, AnimationPreset] = {
    "none": AnimationPreset(
        name="none",
        description="Static — no motion (current default).",
    ),
    "hype": AnimationPreset(
        name="hype",
        description="Fast zoom, slide-up cards, emoji hook — TikTok/Reels native.",
        bg_zoom_start=1.0,
        bg_zoom_end=1.12,
        card_enter="slide_up",
        card_enter_duration=0.3,
        hook_enabled=True,
        hook_text_template="🔥 TOP {n} IN {city} 🔥",
        hook_duration=1.5,
        hook_zoom=1.2,
    ),
    "cinematic": AnimationPreset(
        name="cinematic",
        description="Subtle Ken Burns, slow fade, elegant hook — polished feel.",
        bg_zoom_start=1.0,
        bg_zoom_end=1.04,
        card_enter="fade",
        card_enter_duration=0.6,
        hook_enabled=True,
        hook_text_template="{city} — {n} events this week",
        hook_duration=2.0,
        hook_zoom=1.0,
    ),
}

DEFAULT_ANIMATION = "none"


def get_animation(name: str | None) -> AnimationPreset:
    """Return the preset by name; falls back to "none" for unknown/None."""
    if not name:
        return ANIMATIONS[DEFAULT_ANIMATION]
    return ANIMATIONS.get(name, ANIMATIONS[DEFAULT_ANIMATION])


# ── Motion helpers (used by video.py) ──


def ken_burns_frame(
    oversized: np.ndarray,
    t: float,
    duration: float,
    target_w: int,
    target_h: int,
    zoom_start: float,
    zoom_end: float,
) -> np.ndarray:
    """Return a single frame of the Ken Burns zoom effect.

    ``oversized`` is the background rendered at ``zoom_end × target_size``. Each
    frame crops a progressively-smaller region from center, simulating a zoom-in.
    """
    progress = t / max(duration, 0.001)
    # Current scale relative to the oversized image.
    current_zoom = zoom_start + (zoom_end - zoom_start) * progress
    # The crop region shrinks as zoom increases (crop more = zoom in).
    crop_w = int(target_w * zoom_end / current_zoom)
    crop_h = int(target_h * zoom_end / current_zoom)
    h, w = oversized.shape[:2]
    x = (w - crop_w) // 2
    y = (h - crop_h) // 2
    cropped = oversized[y : y + crop_h, x : x + crop_w]
    # Resize cropped region back to target dimensions.
    from PIL import Image

    img = Image.fromarray(cropped).resize((target_w, target_h), Image.LANCZOS)
    return np.array(img)


def slide_up_position(
    center_x: int,
    center_y: int,
    offset: int,
    enter_duration: float,
    total_duration: float,
) -> Callable[[float], tuple[int, int]]:
    """Return a position function for a slide-up entrance.

    The clip starts ``offset`` pixels below center and slides to center over
    ``enter_duration``, then stays put for the rest.
    """

    def pos(t: float) -> tuple[int, int]:
        if t >= enter_duration:
            return (center_x, center_y)
        progress = t / enter_duration
        # Ease-out (decelerate).
        eased = 1.0 - (1.0 - progress) ** 2
        y = int(center_y + offset * (1.0 - eased))
        return (center_x, y)

    return pos


def slide_left_position(
    center_x: int,
    center_y: int,
    offset: int,
    enter_duration: float,
    total_duration: float,
) -> Callable[[float], tuple[int, int]]:
    """Return a position function for a slide-from-right entrance."""

    def pos(t: float) -> tuple[int, int]:
        if t >= enter_duration:
            return (center_x, center_y)
        progress = t / enter_duration
        eased = 1.0 - (1.0 - progress) ** 2
        x = int(center_x + offset * (1.0 - eased))
        return (center_x, center_y) if t >= enter_duration else (x, center_y)

    return pos
