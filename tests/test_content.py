"""Tests for content generation: captions, images, music, and the builder."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from events_gen.content.builder import build_content
from events_gen.content.captions import generate_captions
from events_gen.content.images import get_provider, resolve_background
from events_gen.content.images.ai_provider import AIImageProvider
from events_gen.content.images.mock_provider import MockProvider
from events_gen.content.music import resolve_music
from events_gen.models import City, Event, EventType
from events_gen.settings import Settings

CITY = City(
    slug="tokyo",
    name="Tokyo",
    country="Japan",
    country_code="JP",
    timezone="Asia/Tokyo",
    latitude=35.68,
    longitude=139.65,
)
MUSIC = EventType(slug="music", name="Music", default_music="music/music/default.mp3")
ARTS = EventType(slug="arts", name="Arts", default_music="music/arts/default.mp3")


def _event(title: str, event_type: str | None = None, venue: str | None = "Hall") -> Event:
    return Event(
        source="mock",
        title=title,
        event_type=event_type,
        start=datetime(2026, 7, 8, 20, 0, tzinfo=UTC),
        venue=venue,
        city_slug="tokyo",
    )


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        EG_DATA_DIR=str(tmp_path / "data"),
        EG_ASSETS_DIR=str(tmp_path / "assets"),
    )


# ── captions (template fallback) ──


def test_template_captions_without_key(settings: Settings) -> None:
    events = [_event("Big Show", "music"), _event("Art Fair", "arts")]
    result = generate_captions(CITY, events, "week", settings=settings)
    assert "Tokyo" in result.title
    assert "Big Show" in result.caption
    assert all(h.startswith("#") for h in result.hashtags)
    # Event-type tags are included.
    assert "#music" in result.hashtags and "#arts" in result.hashtags


def test_template_captions_are_deterministic(settings: Settings) -> None:
    events = [_event("Show", "music")]
    a = generate_captions(CITY, events, "month", settings=settings)
    b = generate_captions(CITY, events, "month", settings=settings)
    assert a == b


# ── caption provider selection ──


def _settings_with(**overrides: str) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_select_provider_auto_prefers_gemini() -> None:
    from events_gen.content.captions import _select_provider

    s = _settings_with(GEMINI_API_KEY="g", ANTHROPIC_API_KEY="a")
    assert _select_provider(s) == "gemini"


def test_select_provider_auto_falls_back_to_anthropic() -> None:
    from events_gen.content.captions import _select_provider

    s = _settings_with(ANTHROPIC_API_KEY="a")
    assert _select_provider(s) == "anthropic"


def test_select_provider_auto_template_without_keys(settings: Settings) -> None:
    from events_gen.content.captions import _select_provider

    assert _select_provider(settings) == "template"


def test_select_provider_explicit_gemini_without_key_is_template() -> None:
    from events_gen.content.captions import _select_provider

    # Explicitly requesting gemini but no key → template (not anthropic).
    s = _settings_with(EG_CAPTION_PROVIDER="gemini", ANTHROPIC_API_KEY="a")
    assert _select_provider(s) == "template"


def test_select_provider_explicit_anthropic() -> None:
    from events_gen.content.captions import _select_provider

    s = _settings_with(EG_CAPTION_PROVIDER="anthropic", GEMINI_API_KEY="g", ANTHROPIC_API_KEY="a")
    assert _select_provider(s) == "anthropic"


def test_gemini_failure_falls_back_to_template(monkeypatch: pytest.MonkeyPatch) -> None:
    # A configured-but-broken Gemini call must degrade to the template, not raise.
    import events_gen.content.captions as captions_mod

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("api down")

    monkeypatch.setattr(captions_mod, "_gemini_captions", boom)
    s = _settings_with(GEMINI_API_KEY="g")
    result = generate_captions(CITY, [_event("Big Show", "music")], "week", settings=s)
    assert "Big Show" in result.caption  # template output


# ── image providers ──


def test_mock_provider_generates_sized_image(tmp_path: Path) -> None:
    out = tmp_path / "bg.jpg"
    MockProvider().generate("Tokyo skyline", out, (640, 480))
    assert out.exists()
    with Image.open(out) as img:
        assert img.size == (640, 480)


def test_mock_provider_is_deterministic(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    MockProvider().generate("Tokyo", a, (100, 100))
    MockProvider().generate("Tokyo", b, (100, 100))
    assert a.read_bytes() == b.read_bytes()


def test_get_provider_defaults_to_mock(settings: Settings) -> None:
    assert isinstance(get_provider(settings), MockProvider)


def test_get_provider_ai_falls_back_without_key(tmp_path: Path) -> None:
    s = Settings(_env_file=None, EG_IMAGE_PROVIDER="ai", EG_DATA_DIR=str(tmp_path))  # type: ignore[call-arg]
    # ai selected but no key -> mock
    assert isinstance(get_provider(s), MockProvider)


def test_ai_provider_not_configured_without_key() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert AIImageProvider(settings=s).is_configured() is False


# ── background resolution (R5 override rule) ──


def test_resolve_background_generates_when_no_upload_or_default(settings: Settings) -> None:
    out = settings.output_dir / "bg.jpg"
    result = resolve_background(CITY, out, (320, 568), settings=settings)
    assert result.exists()
    with Image.open(result) as img:
        assert img.size == (320, 568)


def test_resolve_background_uses_upload(settings: Settings, tmp_path: Path) -> None:
    upload = tmp_path / "mine.png"
    Image.new("RGB", (800, 800), (10, 20, 30)).save(upload)
    out = settings.output_dir / "bg.jpg"
    result = resolve_background(CITY, out, (320, 568), upload_path=upload, settings=settings)
    with Image.open(result) as img:
        assert img.size == (320, 568)  # resized to target


def test_resolve_background_missing_upload_raises(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_background(
            CITY,
            settings.output_dir / "bg.jpg",
            (100, 100),
            upload_path=tmp_path / "nope.png",
            settings=settings,
        )


def test_resolve_background_prefers_city_default(settings: Settings) -> None:
    # Create the city's default asset; it should be used over generation.
    asset = settings.assets_dir / "images" / "tokyo" / "default.jpg"
    asset.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (500, 500), (1, 2, 3)).save(asset)
    city = CITY.model_copy(update={"default_image": "images/tokyo/default.jpg"})
    out = settings.output_dir / "bg.jpg"
    result = resolve_background(city, out, (320, 568), settings=settings)
    with Image.open(result) as img:
        assert img.size == (320, 568)


# ── music resolution (R6 override rule) ──


def test_resolve_music_uses_upload(settings: Settings, tmp_path: Path) -> None:
    upload = tmp_path / "song.mp3"
    upload.write_bytes(b"fake")
    result = resolve_music(
        CITY, [_event("s", "music")], [MUSIC], upload_path=upload, settings=settings
    )
    assert result == upload


def test_resolve_music_missing_upload_raises(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_music(CITY, [], [], upload_path=tmp_path / "nope.mp3", settings=settings)


def test_resolve_music_uses_dominant_type_default(settings: Settings) -> None:
    track = settings.assets_dir / "music" / "music" / "default.mp3"
    track.parent.mkdir(parents=True, exist_ok=True)
    track.write_bytes(b"fake")
    events = [_event("a", "music"), _event("b", "music"), _event("c", "arts")]
    result = resolve_music(CITY, events, [MUSIC, ARTS], settings=settings)
    assert result == track


def test_resolve_music_returns_none_when_nothing_available(settings: Settings) -> None:
    events = [_event("a", "music")]
    assert resolve_music(CITY, events, [MUSIC], settings=settings) is None


def test_resolve_music_use_defaults_false_skips_defaults(settings: Settings) -> None:
    # Smart music off: even with a default track on disk, nothing is chosen.
    track = settings.assets_dir / "music" / "music" / "default.mp3"
    track.parent.mkdir(parents=True, exist_ok=True)
    track.write_bytes(b"fake")
    events = [_event("a", "music")]
    assert resolve_music(CITY, events, [MUSIC], use_defaults=False, settings=settings) is None
    # But an explicit upload is still honored.


def test_resolve_music_use_defaults_false_still_honors_upload(
    settings: Settings, tmp_path: Path
) -> None:
    upload = tmp_path / "song.mp3"
    upload.write_bytes(b"fake")
    result = resolve_music(
        CITY,
        [_event("a", "music")],
        [MUSIC],
        upload_path=upload,
        use_defaults=False,
        settings=settings,
    )
    assert result == upload


# ── builder ──


def test_build_content_assembles_bundle(settings: Settings) -> None:
    events = [_event("Show", "music"), _event("Fair", "arts")]
    content = build_content(
        CITY, events, [MUSIC, ARTS], "week", draft_id="d1", settings=settings, size=(320, 568)
    )
    assert content.title
    assert content.caption
    assert content.hashtags
    assert content.background_image_path is not None
    assert Path(content.background_image_path).exists()
    assert content.music_path is None  # no assets present
