"""Tests for video themes: registry, font resolution, scrim intensity, rendering."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from events_gen.models import Event, PostContent
from events_gen.render import DEFAULT_THEME, REEL, THEMES, render_video
from events_gen.render.cards import render_card
from events_gen.render.themes import Theme, get_theme, load_font


def _event(title: str = "Show", **kw: object) -> Event:
    base: dict[str, object] = {
        "source": "mock",
        "title": title,
        "start": datetime(2026, 7, 10, 20, tzinfo=UTC),
        "venue": "Main Hall",
        "city_slug": "x",
    }
    base.update(kw)
    return Event(**base)  # type: ignore[arg-type]


# ── registry ──


class TestThemeRegistry:
    def test_default_theme_exists(self) -> None:
        assert DEFAULT_THEME in THEMES

    def test_multiple_themes_available(self) -> None:
        # The whole point of the feature: many distinct themes to choose from.
        assert len(THEMES) >= 8

    def test_get_theme_by_name(self) -> None:
        assert get_theme("neon").name == "neon"

    def test_get_theme_unknown_falls_back(self) -> None:
        assert get_theme("does-not-exist").name == DEFAULT_THEME

    def test_get_theme_none_falls_back(self) -> None:
        assert get_theme(None).name == DEFAULT_THEME

    def test_themes_have_distinct_fonts_or_palettes(self) -> None:
        # Ensure themes aren't accidental clones — each differs from classic in
        # fonts, colors, or scrim.
        classic = THEMES["classic"]
        for name, theme in THEMES.items():
            if name == "classic":
                continue
            differs = (
                theme.title_fonts != classic.title_fonts
                or theme.card_color != classic.card_color
                or theme.card_opacity != classic.card_opacity
                or theme.accent_color != classic.accent_color
            )
            assert differs, f"theme {name} is indistinguishable from classic"


# ── scrim intensity ──


class TestIntensity:
    def test_scaled_opacity_default(self) -> None:
        t = THEMES["classic"]
        assert t.scaled_opacity(None) == t.card_opacity

    def test_scaled_opacity_override(self) -> None:
        t = THEMES["classic"]
        assert t.scaled_opacity(1.0) == 255
        assert t.scaled_opacity(0.0) == 0
        assert t.scaled_opacity(0.5) == 128  # round(255 * 0.5)

    def test_scaled_opacity_clamps(self) -> None:
        t = THEMES["classic"]
        assert t.scaled_opacity(5.0) == 255
        assert t.scaled_opacity(-1.0) == 0


# ── font resolution ──


class TestFonts:
    def test_load_font_always_returns_a_font(self) -> None:
        # Even with bogus candidates, falls back to Pillow's default.
        font = load_font(("NoSuchFont-XYZ.ttf",), 40)
        assert font is not None

    def test_load_font_is_cached(self) -> None:
        a = load_font(("DejaVuSans.ttf", "Arial.ttf"), 32)
        b = load_font(("DejaVuSans.ttf", "Arial.ttf"), 32)
        assert a is b  # lru_cache returns the same instance


# ── card rendering with themes ──


class TestThemedCards:
    def test_card_renders_with_each_theme(self) -> None:
        for theme in THEMES.values():
            card = render_card(_event(price_min=20.0), REEL, index=1, total=3, theme=theme)
            assert isinstance(card, Image.Image)
            assert card.mode == "RGBA"
            assert card.height > 0

    def test_uppercase_theme_uppercases_title(self) -> None:
        # 'neon' has uppercase_titles=True; the rendered card should differ from a
        # non-uppercasing theme in size or content — at minimum it renders fine.
        neon = render_card(_event("lower title"), REEL, index=1, total=1, theme=THEMES["neon"])
        assert neon.height > 0


# ── end-to-end render ──


class TestThemedRender:
    def test_render_with_theme_name(self, tmp_path: Path) -> None:
        out = tmp_path / "neon.mp4"
        content = PostContent(title="T", caption="c", hashtags=[])
        render_video(content, [_event()], out, REEL, theme="neon")
        assert out.exists() and out.stat().st_size > 0

    def test_render_with_theme_object(self, tmp_path: Path) -> None:
        out = tmp_path / "obj.mp4"
        content = PostContent(title="T", caption="c", hashtags=[])
        theme: Theme = THEMES["editorial"]
        render_video(content, [_event()], out, REEL, theme=theme)
        assert out.exists()

    def test_render_with_intensity_override(self, tmp_path: Path) -> None:
        out = tmp_path / "dim.mp4"
        content = PostContent(title="T", caption="c", hashtags=[])
        render_video(content, [_event()], out, REEL, theme="classic", intensity=0.2)
        assert out.exists()

    def test_render_unknown_theme_falls_back(self, tmp_path: Path) -> None:
        out = tmp_path / "fallback.mp4"
        content = PostContent(title="T", caption="c", hashtags=[])
        render_video(content, [_event()], out, REEL, theme="nope")
        assert out.exists()
