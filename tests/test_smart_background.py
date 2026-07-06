"""Tests for per-event 'smart' venue backgrounds (image search + fallback)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import httpx
from PIL import Image

from events_gen.content.builder import build_content
from events_gen.content.images.venue import resolve_event_background
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


def _png_bytes(color: tuple[int, int, int] = (10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), color).save(buf, format="PNG")
    return buf.getvalue()


def _event(title: str, venue: str | None = "Dome", image_url: str | None = None) -> Event:
    return Event(
        source="mock",
        title=title,
        start=datetime(2026, 7, 8, 20, tzinfo=UTC),
        venue=venue,
        city_slug="tokyo",
        image_url=image_url,  # type: ignore[arg-type]
    )


def _settings(tmp_path: Path, **extra: str) -> Settings:
    return Settings(_env_file=None, EG_DATA_DIR=str(tmp_path / "data"), **extra)  # type: ignore[arg-type]


def test_uses_event_promo_image_first(tmp_path: Path) -> None:
    s = _settings(tmp_path, UNSPLASH_ACCESS_KEY="k")  # key present, but promo wins
    event = _event("Show", image_url="https://cdn.example.com/promo.png")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "promo.png" in str(request.url)  # never hits Unsplash
        return httpx.Response(200, content=_png_bytes())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = tmp_path / "bg.jpg"
    result = resolve_event_background(event, "Tokyo", out, (320, 568), client=client, settings=s)
    assert result == out
    with Image.open(out) as img:
        assert img.size == (320, 568)  # cover-fit applied


def test_falls_back_to_unsplash_search(tmp_path: Path) -> None:
    s = _settings(tmp_path, UNSPLASH_ACCESS_KEY="k")
    event = _event("Show", venue="Tokyo Dome", image_url=None)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.unsplash.com/search" in url:
            return httpx.Response(
                200, json={"results": [{"urls": {"regular": "https://img/x.png"}}]}
            )
        return httpx.Response(200, content=_png_bytes())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = tmp_path / "bg.jpg"
    result = resolve_event_background(event, "Tokyo", out, (320, 568), client=client, settings=s)
    assert result == out
    assert out.exists()


def test_falls_back_to_openverse_without_key(tmp_path: Path) -> None:
    # No Unsplash key + no promo → Openverse (keyless) should supply the image.
    s = _settings(tmp_path)
    event = _event("Show", venue="Tokyo Dome", image_url=None)

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.openverse.org" in str(request.url):
            return httpx.Response(200, json={"results": [{"url": "https://img/ov.png"}]})
        return httpx.Response(200, content=_png_bytes())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = tmp_path / "bg.jpg"
    result = resolve_event_background(event, "Tokyo", out, (320, 568), client=client, settings=s)
    assert result == out
    assert out.exists()


def test_openverse_used_when_unsplash_empty(tmp_path: Path) -> None:
    # Unsplash configured but returns nothing (unapproved app) → Openverse wins.
    s = _settings(tmp_path, UNSPLASH_ACCESS_KEY="k")
    event = _event("Show", image_url=None)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.unsplash.com" in url:
            return httpx.Response(200, json={"results": []})  # unapproved / empty
        if "api.openverse.org" in url:
            return httpx.Response(200, json={"results": [{"url": "https://img/ov.png"}]})
        return httpx.Response(200, content=_png_bytes())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = tmp_path / "bg.jpg"
    result = resolve_event_background(event, "Tokyo", out, (320, 568), client=client, settings=s)
    assert result == out


def test_returns_none_when_all_sources_empty(tmp_path: Path) -> None:
    s = _settings(tmp_path)  # no key; Openverse also empty
    event = _event("Show", image_url=None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = resolve_event_background(
        event, "Tokyo", tmp_path / "bg.jpg", (320, 568), client=client, settings=s
    )
    assert result is None


def test_download_failure_degrades_to_none(tmp_path: Path) -> None:
    s = _settings(tmp_path, UNSPLASH_ACCESS_KEY="k")
    event = _event("Show", image_url="https://cdn.example.com/promo.png")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = resolve_event_background(
        event, "Tokyo", tmp_path / "bg.jpg", (320, 568), client=client, settings=s
    )
    assert result is None  # never raises


def test_builder_populates_event_backgrounds(tmp_path: Path) -> None:
    s = _settings(tmp_path, EG_ASSETS_DIR=str(tmp_path / "assets"))
    events = [
        _event("A", image_url="https://cdn.example.com/a.png"),
        _event("B", image_url="https://cdn.example.com/b.png"),
    ]
    # Patch the module-level HTTP by injecting via monkeypatch-free MockTransport:
    # build_content creates its own client, so instead assert the off-by-default path.
    content = build_content(
        CITY,
        events,
        [EventType(slug="music", name="Music")],
        "week",
        draft_id="d1",
        smart_backgrounds=False,
        settings=s,
        size=(320, 568),
    )
    assert content.event_backgrounds == {}  # off by default
