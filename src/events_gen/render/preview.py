"""Instant per-event still previews (no video encode).

The edit flow shows one still frame per selected event — background (image /
video-clip first-frame / promo) composited with the event's card and the chosen
text style — so changing a source or text style updates instantly instead of
waiting for a full ffmpeg render. The expensive video encode happens only once,
when the user combines the events into the final video.

Everything here is pure Pillow (plus a one-off ffmpeg frame-grab for video
clips, cached to disk), so a single still renders in well under a second.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from ..models import Event, FontStyle, PostContent
from .cards import DEFAULT_TEXT_STYLE, hex_to_rgba, render_card
from .formats import REEL, VideoFormat
from .themes import DEFAULT_THEME, Theme, get_theme, load_font_file
from .video import _vertical_anchor

logger = logging.getLogger(__name__)


def _dim(img: Image.Image, amount: float) -> Image.Image:
    """Darken an RGB image by ``amount`` (0..1) for text contrast."""
    if amount <= 0:
        return img
    from PIL import ImageEnhance

    return ImageEnhance.Brightness(img).enhance(max(0.0, 1.0 - amount))


def _clip_first_frame(clip_path: str) -> Image.Image | None:
    """Extract (and cache) the first frame of a video clip as a lossless PNG.

    PNG (not JPEG) keeps the frame pixel-exact so downstream cover-fit/upscale for
    the thumbnail stays as crisp as the source allows.
    """
    src = Path(clip_path)
    if not src.exists():
        return None
    frame_path = src.with_suffix(".frame.png")
    if not frame_path.exists():
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-frames:v", "1", str(frame_path)],
                capture_output=True,
                check=True,
            )
        except Exception:  # noqa: BLE001 - best-effort; caller falls back
            logger.warning("could not extract preview frame from %s", clip_path, exc_info=True)
            return None
    try:
        return Image.open(frame_path).convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def _fetch_vibrant_thumbnail_bg(
    city_name: str, size: tuple[int, int], settings: object | None = None
) -> Image.Image | None:
    """Fetch a vibrant, happy, high-energy image for the thumbnail background.

    Searches Pexels (photo API) for lively city/celebration imagery. Falls back to
    Openverse (keyless). The intent is an eye-catching thumbnail that makes people
    want to click — NOT a frame from the video (which is often dark/dimmed).
    """
    import random

    import httpx

    from ..content.images.resize import resize_for_target
    from ..settings import Settings, get_settings

    s: Settings = settings if isinstance(settings, Settings) else get_settings()
    queries = [
        f"{city_name} celebration crowd",
        f"{city_name} vibrant nightlife",
        "happy people party colorful",
        "festival crowd confetti",
        "city lights vibrant night",
    ]
    random.shuffle(queries)
    client = httpx.Client(timeout=20.0, headers={"User-Agent": "events-gen/0.1 (thumbnail bg)"})
    try:
        for query in queries[:3]:
            url = _pexels_photo_url(client, query, s) or _openverse_photo_url(client, query)
            if url:
                try:
                    from io import BytesIO

                    resp = client.get(url, follow_redirects=True)
                    resp.raise_for_status()
                    raw = Image.open(BytesIO(resp.content)).convert("RGB")
                    return resize_for_target(raw, size[0], size[1])
                except Exception:  # noqa: BLE001
                    continue
    finally:
        client.close()
    return None


def _pexels_photo_url(client: httpx.Client, query: str, settings: object) -> str | None:
    """Return the top Pexels photo URL for ``query`` (or None)."""
    from ..settings import Settings

    s = settings if isinstance(settings, Settings) else None
    if s is None or not s.pexels_api_key:
        return None
    try:
        resp = client.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 5, "orientation": "portrait"},
            headers={"Authorization": s.pexels_api_key},
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if photos:
            import random

            photo = random.choice(photos[:5])
            return str(photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large", ""))
    except Exception:  # noqa: BLE001
        pass
    return None


def _openverse_photo_url(client: httpx.Client, query: str) -> str | None:
    """Return the top Openverse photo URL for ``query`` (keyless)."""
    try:
        resp = client.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": 5},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            import random

            return str(random.choice(results[:5]).get("url", ""))
    except Exception:  # noqa: BLE001
        pass
    return None


def _event_background(
    content: PostContent, event: Event, size: tuple[int, int], theme: Theme
) -> Image.Image:
    """Resolve one event's background as a cover-fit Pillow image (matches the renderer).

    Priority mirrors ``render_video``: promo override → video clip first-frame →
    per-event smart background → shared background → solid theme fill.
    """
    from ..content.images.resize import resize_for_target

    raw: Image.Image | None = None

    # Promo override (animated in video; a still here).
    if content.event_background_overrides.get(event.id) == "promo" and event.image_url:
        try:
            import httpx

            resp = httpx.get(
                str(event.image_url),
                follow_redirects=True,
                timeout=20.0,
                headers={"User-Agent": "events-gen/0.1 (preview)"},
            )
            resp.raise_for_status()
            from io import BytesIO

            raw = Image.open(BytesIO(resp.content)).convert("RGB")
        except Exception:  # noqa: BLE001
            raw = None

    # Video clip → first frame.
    if raw is None:
        clip = content.event_video_clips.get(event.id)
        if clip:
            raw = _clip_first_frame(clip)

    # Per-event smart background image.
    if raw is None:
        bg = content.event_backgrounds.get(event.id)
        if bg and Path(bg).exists():
            raw = Image.open(bg).convert("RGB")

    # Shared background image.
    if raw is None:
        shared = content.background_image_path
        if shared and Path(shared).exists():
            raw = Image.open(shared).convert("RGB")

    if raw is None:
        return Image.new("RGB", size, theme.solid_background)

    fitted = resize_for_target(raw, size[0], size[1])
    return _dim(fitted, theme.background_dim)


def render_event_still(
    content: PostContent,
    event: Event,
    index: int,
    total: int,
    *,
    fmt: VideoFormat = REEL,
    theme: Theme | str | None = None,
    intensity: float | None = None,
    text_position: str = "center",
    text_style: str = DEFAULT_TEXT_STYLE,
    font_style: FontStyle | None = None,
) -> Image.Image:
    """Composite a single event's frame (background + card) as a still image.

    This is the instant, encode-free counterpart to one card-segment of
    ``render_video`` — same background priority, card, and anchor — so the still
    faithfully previews how that event looks in the final video. When
    ``font_style`` is set it drives the typography and placement (overriding
    ``text_position``/``text_style``), so the pane can preview font changes live.
    """
    resolved_theme = theme if isinstance(theme, Theme) else get_theme(theme or DEFAULT_THEME)
    frame = _event_background(content, event, fmt.size, resolved_theme).convert("RGBA")

    if font_style is not None:
        text_position = font_style.placement

    card = render_card(
        event,
        fmt,
        index=index,
        total=total,
        theme=resolved_theme,
        intensity=intensity,
        text_style=text_style,
        font_style=font_style,
    )
    x = (fmt.width - card.width) // 2
    y = _vertical_anchor(fmt, card.height, text_position)
    frame.alpha_composite(card, (x, y))
    return frame.convert("RGB")


# Heading layouts for thumbnail variants — where the headline block sits and how
# it's treated. Each is a distinct look; combined with different background frames
# this yields the gallery of options.
THUMBNAIL_LAYOUTS: tuple[str, ...] = (
    "center-block",  # centered, big, drop-shadow
    "bottom-bar",  # headline over a solid bar across the bottom
    "top-banner",  # headline in a banner across the top
    "left-align",  # left-aligned lower third
    "boxed-center",  # headline inside a translucent rounded box, centered
)


def _wrap_to_width(
    draw: ImageDraw.ImageDraw, text: str, font: object, max_w: int
) -> list[str]:
    """Word-wrap ``text`` to ``max_w`` px; returns a list of lines."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def render_thumbnail(
    content: PostContent,
    events: list[Event],
    out_path: Path,
    *,
    fmt: VideoFormat = REEL,
    theme: Theme | str | None = None,
    title: str | None = None,
    layout: str = "center-block",
    bg_event: Event | None = None,
    bg_image: Image.Image | None = None,
    font_style: FontStyle | None = None,
) -> Path:
    """Render the video's poster thumbnail (one variant) and save it as a JPEG.

    ``layout`` selects the heading arrangement (see :data:`THUMBNAIL_LAYOUTS`);
    ``bg_image`` is an explicit background image (e.g. a vibrant photo fetched from
    Pexels); if None, falls back to ``bg_event``'s frame → event clip → solid.
    ``font_style`` applies the user's chosen font/colors. This is what viewers see
    before pressing play.
    """
    from PIL import ImageDraw

    from ..content.images.resize import resize_for_target

    resolved_theme = theme if isinstance(theme, Theme) else get_theme(theme or DEFAULT_THEME)
    ss = 2
    W, H = fmt.width * ss, fmt.height * ss

    if bg_image is not None:
        base = resize_for_target(bg_image, W, H).convert("RGBA")
    else:
        bg = bg_event or (events[0] if events else None)
        if bg is not None:
            base = _event_background(content, bg, (W, H), resolved_theme).convert("RGBA")
        else:
            base = Image.new("RGBA", (W, H), (*resolved_theme.solid_background, 255))
    base = _dim(base.convert("RGB"), 0.22).convert("RGBA")

    draw = ImageDraw.Draw(base)
    uppercase = font_style.uppercase_titles if font_style else resolved_theme.uppercase_titles
    headline = (title if title is not None else content.title).strip()
    if uppercase:
        headline = headline.upper()

    # Fonts + colors (font_style overrides the theme when set). Sizes scale with W.
    title_size = max(52 * ss, int(W * (font_style.title_size / 1080 if font_style else 0.078)))
    badge_size = max(28 * ss, int(W * 0.036))
    if font_style:
        font = load_font_file(font_style.font_path, title_size, resolved_theme.title_fonts)
        badge_font = load_font_file(font_style.font_path, badge_size, resolved_theme.body_fonts)
        title_fill = hex_to_rgba(font_style.title_color)
        accent_fill = hex_to_rgba(font_style.accent_color)
    else:
        from .themes import load_font

        font = load_font(resolved_theme.title_fonts, title_size)
        badge_font = load_font(resolved_theme.body_fonts, badge_size)
        title_fill = resolved_theme.title_color
        accent_fill = resolved_theme.accent_color

    stroke = max(2, title_size // 20)
    max_w = int(W * (0.82 if layout in ("left-align", "boxed-center") else 0.9))
    lines = _wrap_to_width(draw, headline, font, max_w)
    line_h = title_size + int(title_size * 0.25)
    block_h = line_h * len(lines)
    margin = int(H * 0.06)

    # Anchor the block per layout.
    if layout == "bottom-bar":
        top_y = H - block_h - int(margin * 1.5)
        bar_top = top_y - int(margin * 0.6)
        draw.rectangle([(0, bar_top), (W, H)], fill=(0, 0, 0, 170))
    elif layout == "top-banner":
        top_y = margin
        draw.rectangle([(0, 0), (W, block_h + int(margin * 1.6))], fill=(0, 0, 0, 170))
    elif layout == "left-align":
        top_y = int(H * 0.62)
    elif layout == "boxed-center":
        top_y = (H - block_h) // 2
        pad = int(margin * 0.7)
        draw.rounded_rectangle(
            [(int(W * 0.06), top_y - pad), (int(W * 0.94), top_y + block_h + pad)],
            radius=int(W * 0.03),
            fill=(0, 0, 0, 150),
        )
    else:  # center-block
        top_y = (H - block_h) // 2

    left_x = int(W * 0.08)
    y = top_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = left_x if layout == "left-align" else (W - lw) // 2
        draw.text(
            (x, y), line, font=font, fill=title_fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 235)
        )
        y += line_h

    # "N events" badge.
    n = len(events)
    if n:
        badge = f"{n} EVENT{'S' if n != 1 else ''}"
        bb = draw.textbbox((0, 0), badge, font=badge_font)
        bw = bb[2] - bb[0]
        bx = left_x if layout == "left-align" else (W - bw) // 2
        draw.text(
            (bx, y + int(title_size * 0.15)), badge, font=badge_font, fill=accent_fill,
            stroke_width=2 * ss, stroke_fill=(0, 0, 0, 235),
        )

    # Downscale from 2× to the target for crisp edges, save at high quality.
    final = base.convert("RGB").resize(fmt.size, Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(out_path, quality=95, subsampling=0)
    return out_path


def render_thumbnail_variants(
    content: PostContent,
    events: list[Event],
    out_dir: Path,
    *,
    fmt: VideoFormat = REEL,
    theme: Theme | str | None = None,
    title: str | None = None,
    font_style: FontStyle | None = None,
    city_name: str = "",
    count: int = 10,
    settings: object | None = None,
) -> dict[str, Path]:
    """Render a gallery of ``count`` distinct thumbnail options.

    Each option pairs a *heading layout* with a *vibrant background image* fetched
    from Pexels/Openverse (happy, celebration, crowd vibes — NOT a frame from the
    video). This makes thumbnails eye-catching and encourages clicks. Falls back to
    event frames when no photo API result is available.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    variants: dict[str, Path] = {}
    n_layouts = len(THUMBNAIL_LAYOUTS)

    # Fetch a pool of vibrant background photos (best-effort; falls back to event frames).
    vibrant_bgs: list[Image.Image | None] = []
    for _ in range(min(count, 5)):
        img = _fetch_vibrant_thumbnail_bg(city_name or "city", fmt.size, settings)
        vibrant_bgs.append(img)
    # Pad with None so we always have `count` entries to cycle.
    while len(vibrant_bgs) < count:
        vibrant_bgs.append(None)

    bg_events: list[Event | None] = list(events) if events else [None]
    for i in range(count):
        layout = THUMBNAIL_LAYOUTS[i % n_layouts]
        bg_img = vibrant_bgs[i % len(vibrant_bgs)]
        bg_ev = bg_events[i % len(bg_events)] if bg_img is None else None
        key = f"opt{i:02d}"
        path = out_dir / f"thumb_{i:02d}.jpg"
        try:
            render_thumbnail(
                content, events, path, fmt=fmt, theme=theme, title=title,
                layout=layout, bg_event=bg_ev, bg_image=bg_img, font_style=font_style,
            )
            variants[key] = path
        except Exception:  # noqa: BLE001 - one bad variant shouldn't stop the rest
            logger.warning("thumbnail variant %s failed", key, exc_info=True)
    return variants
