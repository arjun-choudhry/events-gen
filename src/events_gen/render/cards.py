"""Per-event card rendering with Pillow.

Each card is a rounded rectangle overlay showing the event title, date/time,
venue, and (optionally) a price range. Cards are sized relative to the video
format so they look good at both 9:16 and 16:9.
"""

from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from ..models import Event
from .formats import VideoFormat


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


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
) -> Image.Image:
    """Render a single event card as an RGBA Pillow image.

    The card is sized to ~80% of the format width and scaled height, with a
    semi-transparent dark background and white text.
    """
    card_w = int(fmt.width * 0.85)
    padding = int(card_w * 0.06)

    title_size = max(28, int(fmt.width * 0.038))
    detail_size = max(20, int(fmt.width * 0.026))
    index_size = max(18, int(fmt.width * 0.022))

    title_font = _load_font(title_size)
    detail_font = _load_font(detail_size)
    index_font = _load_font(index_size)

    scratch = Image.new("RGBA", (card_w, 1000), (0, 0, 0, 0))
    draw = ImageDraw.Draw(scratch)

    text_area_w = card_w - 2 * padding
    y = padding

    # Event number
    idx_text = f"{index}/{total}"
    draw.text((padding, y), idx_text, fill=(200, 200, 200, 220), font=index_font)
    idx_bbox = draw.textbbox((0, 0), idx_text, font=index_font)
    y += (idx_bbox[3] - idx_bbox[1]) + int(padding * 0.4)

    # Title (wrapped)
    title_lines = _wrap_text(event.title, title_font, text_area_w, draw)
    for line in title_lines:
        draw.text((padding, y), line, fill=(255, 255, 255, 255), font=title_font)
        bbox = draw.textbbox((0, 0), line, font=title_font)
        y += (bbox[3] - bbox[1]) + 4
    y += int(padding * 0.5)

    # Date/time
    when = _format_datetime(event.start)
    draw.text((padding, y), when, fill=(220, 220, 220, 240), font=detail_font)
    bbox = draw.textbbox((0, 0), when, font=detail_font)
    y += (bbox[3] - bbox[1]) + 6

    # Venue
    if event.venue:
        venue_lines = _wrap_text(event.venue, detail_font, text_area_w, draw)
        for line in venue_lines:
            draw.text((padding, y), line, fill=(200, 200, 200, 230), font=detail_font)
            bbox = draw.textbbox((0, 0), line, font=detail_font)
            y += (bbox[3] - bbox[1]) + 4
        y += 4

    # Price
    if event.price_min is not None:
        price = _format_price(event)
        draw.text((padding, y), price, fill=(180, 220, 180, 230), font=detail_font)
        bbox = draw.textbbox((0, 0), price, font=detail_font)
        y += (bbox[3] - bbox[1]) + 4

    y += padding
    card_h = y

    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card)
    radius = int(card_w * 0.03)
    card_draw.rounded_rectangle(
        [(0, 0), (card_w - 1, card_h - 1)],
        radius=radius,
        fill=(20, 20, 30, 200),
    )
    card.paste(scratch.crop((0, 0, card_w, card_h)), (0, 0), scratch.crop((0, 0, card_w, card_h)))

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
