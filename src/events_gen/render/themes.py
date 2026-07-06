"""Visual themes for rendered videos.

A :class:`Theme` bundles the look of a video independently of its *format*
(aspect ratio / pacing, see ``formats.py``):

- **fonts** — title and body font candidate lists (first that loads wins, else
  Pillow's default), so themes look distinct where the fonts exist and degrade
  gracefully where they don't;
- **palette** — title / text / accent / index colors (RGBA);
- **scrim** — the panel drawn behind text, and its *intensity* (opacity). This is
  "the intensity of the background on which the fonts are added" — higher =
  more opaque/readable, lower = more of the background image shows through;
- **background dim** — how much the background image is darkened for contrast.

Fonts are resolved from bundled ``assets/fonts/`` first, then common system font
directories, by trying each candidate filename in order.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from ..settings import REPO_ROOT

RGBA = tuple[int, int, int, int]
RGB = tuple[int, int, int]

# Directories searched for a theme's candidate font files, in priority order.
_FONT_DIRS: tuple[Path, ...] = (
    REPO_ROOT / "assets" / "fonts",  # project-bundled fonts win
    Path("/System/Library/Fonts/Supplemental"),  # macOS
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
    Path("/usr/share/fonts/truetype/dejavu"),  # Linux
    Path("/usr/share/fonts"),
    Path("C:/Windows/Fonts"),  # Windows
)


@dataclass(frozen=True, slots=True)
class Theme:
    """A named visual style for a rendered video."""

    name: str
    description: str
    # Font candidate filenames, tried in order (falls back to Pillow default).
    title_fonts: tuple[str, ...]
    body_fonts: tuple[str, ...]
    # Colors (RGBA).
    title_color: RGBA = (255, 255, 255, 255)
    text_color: RGBA = (235, 235, 235, 245)
    accent_color: RGBA = (180, 220, 180, 235)  # price / highlights
    index_color: RGBA = (200, 200, 200, 220)
    # Scrim panel behind text.
    card_color: RGB = (20, 20, 30)
    #: Panel opacity 0–255 — the "intensity of the background on which fonts sit".
    card_opacity: int = 200
    card_radius_frac: float = 0.03
    # Whole-background darkening for contrast: 0.0 = none, 1.0 = black.
    background_dim: float = 0.15
    # Solid color used when no background image is available.
    solid_background: RGB = (30, 30, 40)
    # Uppercase the title/index text (stylistic).
    uppercase_titles: bool = False

    def scaled_opacity(self, intensity: float | None) -> int:
        """Return the scrim opacity, optionally overridden by ``intensity`` (0..1)."""
        if intensity is None:
            return self.card_opacity
        return max(0, min(255, round(255 * intensity)))


# Cross-platform font candidate groups (filenames vary by OS; we try them all).
_SANS = ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc", "Verdana.ttf")
_SANS_BOLD = ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial-Bold.ttf", "Verdana Bold.ttf")
_SERIF = ("Georgia.ttf", "Times New Roman.ttf", "DejaVuSerif.ttf", "TimesNewRoman.ttf")
_SERIF_BOLD = ("Georgia Bold.ttf", "Times New Roman Bold.ttf", "DejaVuSerif-Bold.ttf")
_MONO = ("Courier New.ttf", "DejaVuSansMono.ttf", "Menlo.ttc", "Consolas.ttf")
_DISPLAY = ("Impact.ttf", "Futura.ttc", "DejaVuSans-Bold.ttf", "Arial Bold.ttf")
_ROUNDED = ("Trebuchet MS.ttf", "Comic Sans MS.ttf", "DejaVuSans.ttf")
_CONDENSED = ("Arial Narrow.ttf", "Oswald.ttf", "DejaVuSansCondensed.ttf", "Impact.ttf")


THEMES: dict[str, Theme] = {
    "classic": Theme(
        name="classic",
        description="Clean sans-serif on a dark panel — the default look.",
        title_fonts=_SANS_BOLD,
        body_fonts=_SANS,
    ),
    "midnight": Theme(
        name="midnight",
        description="Deep navy scrim, cool cyan accents, heavy dim.",
        title_fonts=_SANS_BOLD,
        body_fonts=_SANS,
        accent_color=(120, 210, 255, 245),
        card_color=(10, 14, 34),
        card_opacity=225,
        background_dim=0.35,
        solid_background=(8, 10, 26),
    ),
    "sunset": Theme(
        name="sunset",
        description="Warm orange accents on a soft translucent panel.",
        title_fonts=_SERIF_BOLD,
        body_fonts=_SERIF,
        title_color=(255, 244, 235, 255),
        accent_color=(255, 170, 90, 245),
        card_color=(60, 24, 20),
        card_opacity=170,
        background_dim=0.1,
        solid_background=(48, 24, 30),
    ),
    "neon": Theme(
        name="neon",
        description="Bold display font, magenta accents, high-contrast scrim.",
        title_fonts=_DISPLAY,
        body_fonts=_SANS,
        title_color=(255, 255, 255, 255),
        accent_color=(255, 80, 200, 255),
        index_color=(120, 255, 220, 235),
        card_color=(18, 6, 26),
        card_opacity=210,
        background_dim=0.4,
        solid_background=(14, 4, 22),
        uppercase_titles=True,
    ),
    "minimal": Theme(
        name="minimal",
        description="Barely-there scrim — lets the background image dominate.",
        title_fonts=_SANS,
        body_fonts=_SANS,
        card_color=(0, 0, 0),
        card_opacity=90,
        card_radius_frac=0.0,
        background_dim=0.05,
    ),
    "editorial": Theme(
        name="editorial",
        description="Elegant serif, cream text, magazine feel.",
        title_fonts=_SERIF_BOLD,
        body_fonts=_SERIF,
        title_color=(250, 245, 235, 255),
        text_color=(235, 228, 214, 245),
        accent_color=(210, 180, 130, 245),
        card_color=(28, 22, 18),
        card_opacity=185,
        background_dim=0.2,
        solid_background=(32, 26, 22),
    ),
    "mono": Theme(
        name="mono",
        description="Monospace, terminal-style, square panel.",
        title_fonts=_MONO,
        body_fonts=_MONO,
        title_color=(180, 255, 180, 255),
        text_color=(210, 235, 210, 245),
        accent_color=(120, 220, 120, 245),
        card_color=(6, 16, 6),
        card_opacity=205,
        card_radius_frac=0.0,
        background_dim=0.3,
        solid_background=(6, 14, 6),
    ),
    "bold": Theme(
        name="bold",
        description="Condensed heavy type, punchy red accent, opaque bar.",
        title_fonts=_CONDENSED,
        body_fonts=_SANS_BOLD,
        accent_color=(255, 90, 80, 255),
        card_color=(15, 15, 15),
        card_opacity=235,
        card_radius_frac=0.01,
        background_dim=0.25,
        uppercase_titles=True,
    ),
    "pastel": Theme(
        name="pastel",
        description="Soft rounded font, light panel, gentle dim.",
        title_fonts=_ROUNDED,
        body_fonts=_ROUNDED,
        title_color=(60, 50, 70, 255),
        text_color=(70, 60, 80, 245),
        accent_color=(150, 90, 160, 245),
        card_color=(240, 232, 245),
        card_opacity=205,
        background_dim=0.0,
        solid_background=(230, 220, 240),
    ),
}

DEFAULT_THEME = "classic"


def get_theme(name: str | None) -> Theme:
    """Return the theme by name, falling back to the default for unknown/None."""
    if not name:
        return THEMES[DEFAULT_THEME]
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def _find_font_file(candidates: tuple[str, ...]) -> Path | None:
    """Return the first candidate font file that exists in a known font dir."""
    for filename in candidates:
        for directory in _FONT_DIRS:
            path = directory / filename
            if path.exists():
                return path
    return None


@lru_cache(maxsize=256)
def _cached_font(
    candidates: tuple[str, ...], size: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _find_font_file(candidates)
    if path is not None:
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            pass
    # Fall back to Pillow's bundled default (still respects size on Pillow ≥10).
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10
        return ImageFont.load_default()


def load_font(
    candidates: tuple[str, ...], size: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load the first available font from ``candidates`` at ``size`` (cached)."""
    return _cached_font(candidates, size)
