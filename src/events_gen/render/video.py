"""Video composition using MoviePy.

Composes a slideshow video from a background image and per-event cards, with
optional background music. The output is a single mp4 file playable on
YouTube and Instagram.

Flow:
1. Background image → full-duration still clip
2. Per-event cards rendered via Pillow → overlaid sequentially with fade
3. Title card (intro) and outro card bookend the event slides
4. Music track (if any) → trimmed/faded to video length and mixed in
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
)
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut
from moviepy.video.fx import FadeIn, FadeOut
from PIL import Image

from ..models import Event, PostContent
from .cards import render_card
from .formats import REEL, VideoFormat
from .themes import DEFAULT_THEME, Theme, get_theme, load_font

logger = logging.getLogger(__name__)


def _pillow_to_numpy(img: Image.Image) -> np.ndarray:
    """Convert a Pillow RGBA/RGB image to a numpy array (RGB, uint8)."""
    return np.array(img.convert("RGB"))


def _dim(img: Image.Image, amount: float) -> Image.Image:
    """Darken an RGB image by ``amount`` (0..1) for text contrast."""
    if amount <= 0:
        return img
    from PIL import ImageEnhance

    return ImageEnhance.Brightness(img).enhance(max(0.0, 1.0 - amount))


def _load_background(path: str | None, size: tuple[int, int], theme: Theme) -> np.ndarray:
    """Load + dim a background image to a numpy array at ``size``, or a solid fill."""
    if path and Path(path).exists():
        img = Image.open(path).convert("RGB").resize(size)
        img = _dim(img, theme.background_dim)
    else:
        img = Image.new("RGB", size, theme.solid_background)
    return _pillow_to_numpy(img)


def _make_title_card(
    content: PostContent, fmt: VideoFormat, theme: Theme, intensity: float | None
) -> Image.Image:
    """Render a title intro card (post title on a themed scrim)."""
    from PIL import ImageDraw

    img = Image.new("RGBA", fmt.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    title_size = max(36, int(fmt.width * 0.045))
    font = load_font(theme.title_fonts, title_size)

    text = content.title.upper() if theme.uppercase_titles else content.title
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (fmt.width - tw) // 2
    y = (fmt.height - th) // 2

    pad = int(title_size * 0.8)
    draw.rounded_rectangle(
        [(x - pad, y - pad), (x + tw + pad, y + th + pad)],
        radius=int(pad * theme.card_radius_frac * 13),  # ~0.4 for the classic frac
        fill=(*theme.card_color, theme.scaled_opacity(intensity)),
    )
    draw.text((x, y), text, fill=theme.title_color, font=font)
    return img


def _make_outro_card(fmt: VideoFormat, theme: Theme) -> Image.Image:
    """Render a simple outro overlay."""
    from PIL import ImageDraw

    img = Image.new("RGBA", fmt.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    size = max(28, int(fmt.width * 0.032))
    font = load_font(theme.body_fonts, size)

    text = "See you at the next event!"
    if theme.uppercase_titles:
        text = text.upper()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (fmt.width - tw) // 2
    y = (fmt.height - th) // 2
    draw.text((x, y), text, fill=theme.text_color, font=font)
    return img


def _overlay_clip(
    overlay: Image.Image,
    fmt: VideoFormat,
    start: float,
    duration: float,
    fade_duration: float = 0.4,
) -> ImageClip:
    """Create a positioned MoviePy clip from a Pillow RGBA overlay."""
    arr = _pillow_to_numpy(overlay)
    clip = (
        ImageClip(arr)
        .with_duration(duration)
        .with_start(start)
        .with_effects([FadeIn(fade_duration), FadeOut(fade_duration)])
    )
    ox = (fmt.width - overlay.width) // 2
    oy = (fmt.height - overlay.height) // 2
    return clip.with_position((ox, oy))


def render_video(
    content: PostContent,
    events: list[Event],
    out_path: Path,
    fmt: VideoFormat = REEL,
    *,
    theme: Theme | str | None = None,
    intensity: float | None = None,
    fade_duration: float = 0.4,
) -> Path:
    """Render the final slideshow video and write to ``out_path``.

    ``theme`` selects the visual style (fonts/colors/scrim); pass a
    :class:`Theme`, a theme name, or None for the default. ``intensity`` (0..1)
    overrides the theme's scrim opacity — the "intensity of the background on
    which the fonts are added". Returns the output path on success.
    """
    resolved_theme = theme if isinstance(theme, Theme) else get_theme(theme or DEFAULT_THEME)

    n_events = len(events)
    intro_dur = fmt.intro_seconds
    card_dur = fmt.seconds_per_card
    outro_dur = fmt.outro_seconds
    total_dur = intro_dur + (card_dur * n_events) + outro_dur

    logger.info(
        "rendering %s video: %d events, %.1fs total, %dx%d, theme=%s",
        fmt.name,
        n_events,
        total_dur,
        fmt.width,
        fmt.height,
        resolved_theme.name,
    )

    # Base background clip spanning the whole video (used for intro/outro and as
    # the fallback for any event without a smart background).
    base_bg_arr = _load_background(content.background_image_path, fmt.size, resolved_theme)
    layers: list[ImageClip] = [ImageClip(base_bg_arr).with_duration(total_dur)]

    # Per-event background segments (smart backgrounds), timed to each card.
    for i, event in enumerate(events):
        event_bg = content.event_backgrounds.get(event.id)
        if event_bg and Path(event_bg).exists():
            seg_arr = _load_background(event_bg, fmt.size, resolved_theme)
            start_t = intro_dur + i * card_dur
            layers.append(
                ImageClip(seg_arr)
                .with_duration(card_dur)
                .with_start(start_t)
                .with_effects([FadeIn(fade_duration), FadeOut(fade_duration)])
            )

    overlays: list[ImageClip] = []

    # Title intro
    title_img = _make_title_card(content, fmt, resolved_theme, intensity)
    overlays.append(
        _overlay_clip(title_img, fmt, start=0, duration=intro_dur, fade_duration=fade_duration)
    )

    # Event cards
    for i, event in enumerate(events):
        card_img = render_card(
            event, fmt, index=i + 1, total=n_events, theme=resolved_theme, intensity=intensity
        )
        start_t = intro_dur + i * card_dur
        overlays.append(
            _overlay_clip(
                card_img, fmt, start=start_t, duration=card_dur, fade_duration=fade_duration
            )
        )

    # Outro
    outro_img = _make_outro_card(fmt, resolved_theme)
    outro_start = intro_dur + n_events * card_dur
    overlays.append(
        _overlay_clip(
            outro_img, fmt, start=outro_start, duration=outro_dur, fade_duration=fade_duration
        )
    )

    # Composite: base bg → per-event bg segments → card/text overlays.
    video = CompositeVideoClip(layers + overlays, size=fmt.size)

    # Music
    if content.music_path and Path(content.music_path).exists():
        audio = AudioFileClip(content.music_path)
        if audio.duration > total_dur:
            audio = audio.subclipped(0, total_dur)
        audio = audio.with_effects(
            [
                AudioFadeIn(min(fade_duration * 2, 1.0)),
                AudioFadeOut(min(fade_duration * 3, 2.0)),
            ]
        )
        video = video.with_audio(audio)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(
        str(out_path),
        fps=fmt.fps,
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )
    logger.info("wrote %s (%.1f MB)", out_path, out_path.stat().st_size / 1_048_576)
    return out_path
