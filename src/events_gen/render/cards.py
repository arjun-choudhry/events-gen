"""Per-event card rendering with Pillow.

Each card is a rounded rectangle overlay showing the event title, date/time,
venue, and (optionally) a price range. Cards are sized relative to the video
format so they look good at both 9:16 and 16:9, and styled by a :class:`Theme`
(fonts, colors, scrim intensity).
"""

from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from ..models import Event
from .formats import VideoFormat
from .themes import DEFAULT_THEME, Theme, get_theme, load_font


def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def render_card(
    event: Event,
    fmt: VideoFormat,
    index: int,
    total: int,
    *,
    theme: Theme | None = None,
    intensity: float | None = None,
    supersample: int = 2,
) -> Image.Image:
    """Render a single event card as an RGBA Pillow image.

    Cards are rendered at ``supersample``× resolution then downscaled with
    LANCZOS for crisp, sub-pixel-smooth text edges.

    ``theme`` controls fonts/colors/scrim; ``intensity`` (0..1) overrides the
    theme's scrim opacity — higher makes the panel behind the text more opaque
    (more readable), lower lets more of the background show through.
    """
    theme = theme or get_theme(DEFAULT_THEME)
    ss = max(1, supersample)
    card_w = int(fmt.width * 0.85) * ss
    padding = int(card_w * 0.06)

    title_size = max(28, int(fmt.width * 0.038)) * ss
    detail_size = max(20, int(fmt.width * 0.026)) * ss
    index_size = max(18, int(fmt.width * 0.022)) * ss

    title_font = load_font(theme.title_fonts, title_size)
    detail_font = load_font(theme.body_fonts, detail_size)
    index_font = load_font(theme.body_fonts, index_size)

    scratch = Image.new("RGBA", (card_w, 1000), (0, 0, 0, 0))
    draw = ImageDraw.Draw(scratch)

    text_area_w = card_w - 2 * padding
    y = padding

    # Event number
    idx_text = f"{index}/{total}"
    draw.text((padding, y), idx_text, fill=theme.index_color, font=index_font)
    idx_bbox = draw.textbbox((0, 0), idx_text, font=index_font)
    y += (idx_bbox[3] - idx_bbox[1]) + int(padding * 0.4)

    # Title (wrapped)
    title_text = event.title.upper() if theme.uppercase_titles else event.title
    title_lines = _wrap_text(title_text, title_font, text_area_w, draw)
    for line in title_lines:
        draw.text((padding, y), line, fill=theme.title_color, font=title_font)
        bbox = draw.textbbox((0, 0), line, font=title_font)
        y += (bbox[3] - bbox[1]) + 4
    y += int(padding * 0.5)

    # Date/time
    when = _format_datetime(event.start)
    draw.text((padding, y), when, fill=theme.text_color, font=detail_font)
    bbox = draw.textbbox((0, 0), when, font=detail_font)
    y += (bbox[3] - bbox[1]) + 6

    # Venue
    if event.venue:
        venue_lines = _wrap_text(event.venue, detail_font, text_area_w, draw)
        for line in venue_lines:
            draw.text((padding, y), line, fill=theme.text_color, font=detail_font)
            bbox = draw.textbbox((0, 0), line, font=detail_font)
            y += (bbox[3] - bbox[1]) + 4
        y += 4

    # Price
    if event.price_min is not None:
        price = _format_price(event)
        draw.text((padding, y), price, fill=theme.accent_color, font=detail_font)
        bbox = draw.textbbox((0, 0), price, font=detail_font)
        y += (bbox[3] - bbox[1]) + 4

    y += padding
    card_h = y

    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card)
    radius = int(card_w * theme.card_radius_frac)
    scrim_fill = (*theme.card_color, theme.scaled_opacity(intensity))
    card_draw.rounded_rectangle(
        [(0, 0), (card_w - 1, card_h - 1)],
        radius=radius,
        fill=scrim_fill,
    )
    card.paste(scratch.crop((0, 0, card_w, card_h)), (0, 0), scratch.crop((0, 0, card_w, card_h)))

    # Downscale from supersample resolution to the actual target for crisp edges.
    if ss > 1:
        final_w = card_w // ss
        final_h = card_h // ss
        card = card.resize((final_w, final_h), Image.LANCZOS)

    return card


def _format_datetime(dt: datetime) -> str:
    return dt.strftime("%a %d %b · %H:%M")


def _format_price(event: Event) -> str:
    currency = event.currency or "$"
    if (
        event.price_min is not None
        and event.price_max is not None
        and event.price_min != event.price_max
    ):
        return f"{currency}{event.price_min:.0f}–{currency}{event.price_max:.0f}"
    if event.price_min is not None:
        return f"From {currency}{event.price_min:.0f}"
    return ""
