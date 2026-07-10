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
from typing import Any

import numpy as np
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
)
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut
from moviepy.video.fx import FadeIn, FadeOut
from PIL import Image

from ..models import Event, FontStyle, PostContent
from .animations import (
    DEFAULT_ANIMATION,
    AnimationPreset,
    get_animation,
    ken_burns_frame,
    slide_left_position,
    slide_up_position,
)
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
        from ..content.images.resize import resize_for_target

        img = Image.open(path).convert("RGB")
        img = resize_for_target(img, size[0], size[1])
        img = _dim(img, theme.background_dim)
    else:
        img = Image.new("RGB", size, theme.solid_background)
    return _pillow_to_numpy(img)


def _load_promo_image(url: str, size: tuple[int, int], theme: Theme) -> np.ndarray | None:
    """Download an event's promo image and cover-fit it to ``size`` (or None on failure)."""
    import httpx

    from ..content.images.resize import resize_for_target

    try:
        from io import BytesIO

        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=20.0,
            headers={"User-Agent": "events-gen/0.1 (promo image fetch)"},
        )
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img = resize_for_target(img, size[0], size[1])
        img = _dim(img, theme.background_dim)
        return _pillow_to_numpy(img)
    except Exception:  # noqa: BLE001 - best-effort; caller falls through
        logger.warning("failed to load promo image %s", url, exc_info=True)
        return None


def _cover_fit_clip(clip_path: str, fmt: VideoFormat) -> Any:
    """Load a video clip and cover-fit it to ``fmt.size`` (scale-to-fill + crop).

    Preserves aspect ratio — the clip is scaled so the frame is fully covered,
    then center-cropped, so it never looks stretched or squished.
    """
    from moviepy import VideoFileClip
    from moviepy.video.fx import Crop, Resize

    clip = VideoFileClip(clip_path)
    target_w, target_h = fmt.size
    scale = max(target_w / clip.w, target_h / clip.h)
    new_w = round(clip.w * scale)
    new_h = round(clip.h * scale)
    clip = clip.with_effects([Resize((new_w, new_h))])
    # Center-crop to the exact target dimensions.
    return clip.with_effects(
        [Crop(width=target_w, height=target_h, x_center=new_w // 2, y_center=new_h // 2)]
    )


def _make_ken_burns_clip(
    bg_arr: np.ndarray,
    fmt: VideoFormat,
    duration: float,
    zoom_start: float,
    zoom_end: float,
) -> VideoClip:
    """Create a background clip with Ken Burns (slow zoom) motion."""
    target_w, target_h = fmt.size
    # Render the background at the max zoom scale so we can crop in.
    max_zoom = max(zoom_start, zoom_end)
    oversized_w = int(target_w * max_zoom)
    oversized_h = int(target_h * max_zoom)
    oversized = np.array(Image.fromarray(bg_arr).resize((oversized_w, oversized_h), Image.LANCZOS))

    def make_frame(t: float) -> np.ndarray:
        return ken_burns_frame(oversized, t, duration, target_w, target_h, zoom_start, zoom_end)

    return VideoClip(make_frame, duration=duration).with_fps(fmt.fps)


def _make_hook_card(text: str, fmt: VideoFormat, theme: Theme) -> Image.Image:
    """Render a big scroll-stopping hook text overlay."""
    from PIL import ImageDraw

    img = Image.new("RGBA", fmt.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    size = max(48, int(fmt.width * 0.065))
    font = load_font(theme.title_fonts, size)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (fmt.width - tw) // 2
    y = (fmt.height - th) // 2

    pad = int(size * 0.6)
    draw.rounded_rectangle(
        [(x - pad, y - pad), (x + tw + pad, y + th + pad)],
        radius=int(pad * 0.5),
        fill=(*theme.card_color, theme.card_opacity),
    )
    draw.text((x, y), text, fill=theme.title_color, font=font)
    return img


def _vertical_anchor(fmt: VideoFormat, overlay_h: int, text_position: str) -> int:
    """Return the y-coordinate for the overlay given a top/center/bottom anchor."""
    margin = int(fmt.height * 0.08)
    if text_position == "top":
        return margin
    if text_position == "bottom":
        return fmt.height - overlay_h - margin
    return (fmt.height - overlay_h) // 2  # center (default)


def _overlay_clip(
    overlay: Image.Image,
    fmt: VideoFormat,
    start: float,
    duration: float,
    fade_duration: float = 0.4,
    animation: AnimationPreset | None = None,
    text_position: str = "center",
) -> ImageClip:
    """Create a positioned MoviePy clip from a Pillow RGBA overlay."""
    # Pass the full RGBA array so MoviePy preserves the alpha channel (semi-transparent
    # panel, stroke edges, etc.) when compositing over the background layers.
    arr = np.array(overlay.convert("RGBA"))
    clip = ImageClip(arr).with_duration(duration).with_start(start)

    ox = (fmt.width - overlay.width) // 2
    oy = _vertical_anchor(fmt, overlay.height, text_position)

    anim = animation or get_animation(DEFAULT_ANIMATION)
    if anim.card_enter == "slide_up":
        offset = int(fmt.height * 0.15)
        clip = clip.with_effects([FadeOut(fade_duration)])
        return clip.with_position(
            slide_up_position(ox, oy, offset, anim.card_enter_duration, duration)
        )
    if anim.card_enter == "slide_left":
        offset = int(fmt.width * 0.3)
        clip = clip.with_effects([FadeOut(fade_duration)])
        return clip.with_position(
            slide_left_position(ox, oy, offset, anim.card_enter_duration, duration)
        )
    # Default: fade in + out, static position.
    clip = clip.with_effects([FadeIn(fade_duration), FadeOut(fade_duration)])
    return clip.with_position((ox, oy))


def render_video(
    content: PostContent,
    events: list[Event],
    out_path: Path,
    fmt: VideoFormat = REEL,
    *,
    theme: Theme | str | None = None,
    intensity: float | None = None,
    animation: AnimationPreset | str | None = None,
    text_position: str = "center",
    text_style: str = "panel",
    font_style: FontStyle | None = None,
    fade_duration: float = 0.4,
) -> Path:
    """Render the final slideshow video and write to ``out_path``.

    ``theme`` selects the base visual style; ``animation`` selects the motion
    preset ("none" / "hype" / "cinematic"). ``font_style`` (when set) is the single
    user-chosen typography override applied to all cards — its font, sizes, colors,
    placement, and legibility style win over ``theme``/``intensity``/``text_*``.
    Returns the output path.
    """
    # font_style, when present, is the authoritative source for placement + style.
    if font_style is not None:
        text_position = font_style.placement
        text_style = font_style.text_style
    resolved_theme = theme if isinstance(theme, Theme) else get_theme(theme or DEFAULT_THEME)
    resolved_anim = (
        animation if isinstance(animation, AnimationPreset) else get_animation(animation)
    )

    n_events = len(events)
    # No title-intro or outro cards: the video opens directly on the first event
    # (the thumbnail carries the "what/where" framing instead). Only the optional
    # animation hook may precede the events.
    hook_dur = resolved_anim.hook_duration if resolved_anim.hook_enabled else 0.0
    intro_dur = 0.0
    card_dur = fmt.seconds_per_card
    outro_dur = 0.0
    total_dur = hook_dur + intro_dur + (card_dur * n_events) + outro_dur

    logger.info(
        "rendering %s video: %d events, %.1fs total, %dx%d, theme=%s, anim=%s",
        fmt.name,
        n_events,
        total_dur,
        fmt.width,
        fmt.height,
        resolved_theme.name,
        resolved_anim.name,
    )

    # Base background clip — Ken Burns if animation has zoom, else static.
    base_bg_arr = _load_background(content.background_image_path, fmt.size, resolved_theme)
    if resolved_anim.bg_zoom_end != 1.0 or resolved_anim.bg_zoom_start != 1.0:
        layers: list[ImageClip | Any] = [
            _make_ken_burns_clip(
                base_bg_arr, fmt, total_dur, resolved_anim.bg_zoom_start, resolved_anim.bg_zoom_end
            )
        ]
    else:
        layers = [ImageClip(base_bg_arr).with_duration(total_dur)]

    # Per-event background segments: video clips (M16) take priority over images.
    cards_start = hook_dur + intro_dur
    for i, event in enumerate(events):
        start_t = cards_start + i * card_dur

        # Per-event override: animated promo image (edit-pane toggle).
        if content.event_background_overrides.get(event.id) == "promo" and event.image_url:
            promo_arr = _load_promo_image(str(event.image_url), fmt.size, resolved_theme)
            if promo_arr is not None:
                layers.append(
                    _make_ken_burns_clip(promo_arr, fmt, card_dur, 1.0, 1.08)
                    .with_start(start_t)
                    .with_effects([FadeIn(fade_duration), FadeOut(fade_duration)])
                )
                continue

        # Video clip background (M16). Cover-fit (scale to fill + center-crop) so
        # the clip keeps its aspect ratio instead of stretching to the frame.
        event_clip = content.event_video_clips.get(event.id)
        if event_clip and Path(event_clip).exists():
            clip = _cover_fit_clip(event_clip, fmt)
            if clip.duration > card_dur:
                clip = clip.subclipped(0, card_dur)
            layers.append(
                clip.with_duration(card_dur)
                .with_start(start_t)
                .with_effects([FadeIn(fade_duration), FadeOut(fade_duration)])
            )
            continue
        # Image background (smart backgrounds).
        event_bg = content.event_backgrounds.get(event.id)
        if event_bg and Path(event_bg).exists():
            seg_arr = _load_background(event_bg, fmt.size, resolved_theme)
            layers.append(
                ImageClip(seg_arr)
                .with_duration(card_dur)
                .with_start(start_t)
                .with_effects([FadeIn(fade_duration), FadeOut(fade_duration)])
            )

    overlays: list[ImageClip] = []

    # Hook intro (if animation enables it)
    if resolved_anim.hook_enabled:
        hook_text = resolved_anim.hook_text_template.format(
            city=content.title.split(" in ")[-1] if " in " in content.title else "YOUR CITY",
            n=n_events,
        )
        hook_img = _make_hook_card(hook_text, fmt, resolved_theme)
        overlays.append(_overlay_clip(hook_img, fmt, start=0, duration=hook_dur, fade_duration=0.2))

    # Event cards
    for i, event in enumerate(events):
        card_img = render_card(
            event,
            fmt,
            index=i + 1,
            total=n_events,
            theme=resolved_theme,
            intensity=intensity,
            text_style=text_style,
            font_style=font_style,
        )
        start_t = cards_start + i * card_dur
        overlays.append(
            _overlay_clip(
                card_img,
                fmt,
                start=start_t,
                duration=card_dur,
                fade_duration=fade_duration,
                animation=resolved_anim,
                text_position=text_position,
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

    from ..settings import get_settings as _get_settings

    crf = _get_settings().render_crf
    out_path.parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(
        str(out_path),
        fps=fmt.fps,
        codec="libx264",
        audio_codec="aac",
        ffmpeg_params=["-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"],
        logger=None,
    )
    logger.info("wrote %s (%.1f MB)", out_path, out_path.stat().st_size / 1_048_576)
    return out_path


def render_event_segment(
    content: PostContent,
    event: Event,
    index: int,
    total: int,
    out_path: Path,
    fmt: VideoFormat = REEL,
    *,
    theme: Theme | str | None = None,
    intensity: float | None = None,
    text_position: str = "center",
    text_style: str = "panel",
    font_style: FontStyle | None = None,
    fade_duration: float = 0.4,
) -> Path:
    """Render ONE event's card segment as a short standalone video (clip + text).

    This is the moving counterpart to :func:`render_event_still`: it plays the
    event's own background (video clip / promo / image / shared / solid) with the
    card + text composited on top, plus the shared music — exactly one card's
    worth of the final combined video. Used for the per-event "play" preview so
    the user sees motion without encoding the whole video.
    """
    if font_style is not None:
        text_position = font_style.placement
        text_style = font_style.text_style
    resolved_theme = theme if isinstance(theme, Theme) else get_theme(theme or DEFAULT_THEME)
    dur = fmt.seconds_per_card

    # Background layer, mirroring render_video's per-event priority.
    layers: list[ImageClip | Any] = []
    bg_added = False
    if content.event_background_overrides.get(event.id) == "promo" and event.image_url:
        promo_arr = _load_promo_image(str(event.image_url), fmt.size, resolved_theme)
        if promo_arr is not None:
            layers.append(_make_ken_burns_clip(promo_arr, fmt, dur, 1.0, 1.08))
            bg_added = True
    if not bg_added:
        event_clip = content.event_video_clips.get(event.id)
        if event_clip and Path(event_clip).exists():
            clip = _cover_fit_clip(event_clip, fmt)
            if clip.duration > dur:
                clip = clip.subclipped(0, dur)
            layers.append(clip.with_duration(dur))
            bg_added = True
    if not bg_added:
        event_bg = content.event_backgrounds.get(event.id) or content.background_image_path
        seg_arr = _load_background(event_bg, fmt.size, resolved_theme)
        layers.append(ImageClip(seg_arr).with_duration(dur))

    # Card + text overlay (same compositing as the final render).
    card_img = render_card(
        event,
        fmt,
        index=index,
        total=total,
        theme=resolved_theme,
        intensity=intensity,
        text_style=text_style,
        font_style=font_style,
    )
    layers.append(
        _overlay_clip(
            card_img, fmt, start=0, duration=dur, fade_duration=fade_duration,
            text_position=text_position,
        )
    )

    video = CompositeVideoClip(layers, size=fmt.size).with_duration(dur)

    if content.music_path and Path(content.music_path).exists():
        audio = AudioFileClip(content.music_path)
        if audio.duration > dur:
            audio = audio.subclipped(0, dur)
        video = video.with_audio(audio.with_effects([AudioFadeIn(0.4), AudioFadeOut(0.6)]))

    from ..settings import get_settings as _get_settings

    crf = _get_settings().render_crf
    out_path.parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(
        str(out_path),
        fps=fmt.fps,
        codec="libx264",
        audio_codec="aac",
        ffmpeg_params=["-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"],
        logger=None,
    )
    logger.info("wrote event segment %s", out_path)
    return out_path
