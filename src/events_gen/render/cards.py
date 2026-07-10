"""Per-event card rendering with Pillow.

Each card is a rounded rectangle overlay showing the event title, date/time,
venue, and (optionally) a price range. Cards are sized relative to the video
format so they look good at both 9:16 and 16:9, and styled by a :class:`Theme`
(fonts, colors, scrim intensity).
"""

from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from ..models import Event, FontStyle
from .formats import VideoFormat
from .themes import DEFAULT_THEME, Theme, get_theme, load_font, load_font_file

# How the card text is made legible over the background:
#   "panel"   — opaque rounded panel behind the text (classic; hides the video)
#   "outline" — dark stroke around each glyph, no panel (video stays visible)
#   "shadow"  — soft drop shadow behind the text, no panel (video stays visible)
TEXT_STYLES = ("panel", "outline", "shadow")
DEFAULT_TEXT_STYLE = "panel"


def _text_decoration(style: str, ss: int) -> tuple[int, tuple[int, int, int, int] | None, int]:
    """Return (stroke_width, stroke_fill, shadow_offset) for a text style at scale ``ss``."""
    if style == "outline":
        return (max(1, 2 * ss), (0, 0, 0, 230), 0)
    if style == "shadow":
        return (0, None, max(2, 3 * ss))
    return (0, None, 0)  # panel: readability comes from the panel, not the glyphs


def hex_to_rgba(hex_str: str, alpha: int = 255) -> tuple[int, int, int, int]:
    """Parse a ``#rrggbb`` (or ``#rgb``) color into an RGBA tuple."""
    s = hex_str.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        r, g, b = (int(s[i : i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (255, 255, 255, alpha)
    return (r, g, b, alpha)


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
    text_style: str = DEFAULT_TEXT_STYLE,
    font_style: FontStyle | None = None,
    supersample: int = 2,
) -> Image.Image:
    """Render a single event card as an RGBA Pillow image.

    Cards are rendered at ``supersample``× resolution then downscaled with
    LANCZOS for crisp, sub-pixel-smooth text edges.

    ``theme`` provides the base look. ``font_style`` (when set) is the single
    user-chosen typography override applied to ALL text — font file, sizes,
    colors, legibility style, and panel opacity — and takes precedence over the
    theme/``intensity``/``text_style`` args.
    """
    theme = theme or get_theme(DEFAULT_THEME)
    ss = max(1, supersample)

    # Resolve the effective look: font_style overrides theme where present.
    eff_style = font_style.text_style if font_style else text_style
    stroke_w, stroke_fill, shadow_off = _text_decoration(eff_style, ss)
    uppercase = font_style.uppercase_titles if font_style else theme.uppercase_titles

    if font_style:
        title_color = hex_to_rgba(font_style.title_color)
        body_color = hex_to_rgba(font_style.body_color)
        accent_color = hex_to_rgba(font_style.accent_color)
        index_color = hex_to_rgba(font_style.body_color, 220)
    else:
        title_color = theme.title_color
        body_color = theme.text_color
        accent_color = theme.accent_color
        index_color = theme.index_color

    def _text(
        d: ImageDraw.ImageDraw,
        xy: tuple[int, int],
        s: str,
        fill: tuple[int, int, int, int],
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ) -> None:
        """Draw text with the active style's stroke/shadow decoration."""
        if shadow_off:
            d.text((xy[0] + shadow_off, xy[1] + shadow_off), s, fill=(0, 0, 0, 200), font=font)
        d.text(xy, s, fill=fill, font=font, stroke_width=stroke_w, stroke_fill=stroke_fill)

    card_w = int(fmt.width * 0.85) * ss
    padding = int(card_w * 0.06)

    if font_style:
        # Scale the user's pixel sizes from reel-width (1080) to this format.
        scale = fmt.width / 1080.0
        title_size = max(12, int(font_style.title_size * scale)) * ss
        detail_size = max(10, int(font_style.body_size * scale)) * ss
        index_size = max(10, int(font_style.body_size * 0.72 * scale)) * ss
        title_font = load_font_file(font_style.font_path, title_size, theme.title_fonts)
        detail_font = load_font_file(font_style.font_path, detail_size, theme.body_fonts)
        index_font = load_font_file(font_style.font_path, index_size, theme.body_fonts)
    else:
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

    # Horizontal text alignment within the card (driven by font_style.text_align).
    align = font_style.text_align if font_style else "left"

    def _ax(text_w: int) -> int:
        """Compute x for text of width ``text_w`` based on alignment."""
        if align == "center":
            return padding + (text_area_w - text_w) // 2
        if align == "right":
            return card_w - padding - text_w
        return padding  # left (default)

    # Event number
    idx_text = f"{index}/{total}"
    idx_bbox = draw.textbbox((0, 0), idx_text, font=index_font)
    _text(draw, (_ax(idx_bbox[2] - idx_bbox[0]), y), idx_text, index_color, index_font)
    y += (idx_bbox[3] - idx_bbox[1]) + int(padding * 0.4)

    # Title (wrapped)
    title_text = event.title.upper() if uppercase else event.title
    title_lines = _wrap_text(title_text, title_font, text_area_w, draw)
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        _text(draw, (_ax(bbox[2] - bbox[0]), y), line, title_color, title_font)
        y += (bbox[3] - bbox[1]) + 4
    y += int(padding * 0.5)

    # Date/time
    when = _format_datetime(event.start)
    bbox = draw.textbbox((0, 0), when, font=detail_font)
    _text(draw, (_ax(bbox[2] - bbox[0]), y), when, body_color, detail_font)
    y += (bbox[3] - bbox[1]) + 6

    # Venue
    if event.venue:
        venue_lines = _wrap_text(event.venue, detail_font, text_area_w, draw)
        for line in venue_lines:
            bbox = draw.textbbox((0, 0), line, font=detail_font)
            _text(draw, (_ax(bbox[2] - bbox[0]), y), line, body_color, detail_font)
            y += (bbox[3] - bbox[1]) + 4
        y += 4

    # Price
    if event.price_min is not None:
        price = _format_price(event)
        bbox = draw.textbbox((0, 0), price, font=detail_font)
        _text(draw, (_ax(bbox[2] - bbox[0]), y), price, accent_color, detail_font)
        y += (bbox[3] - bbox[1]) + 4

    y += padding
    card_h = y

    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    # The opaque scrim panel only appears in "panel" style; outline/shadow keep the
    # background fully visible and rely on per-glyph decoration for legibility.
    if eff_style == "panel":
        card_draw = ImageDraw.Draw(card)
        radius = int(card_w * theme.card_radius_frac)
        if font_style:
            opacity = max(0, min(255, round(font_style.panel_opacity * 255)))
        else:
            opacity = theme.scaled_opacity(intensity)
        scrim_fill = (*theme.card_color, opacity)
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
