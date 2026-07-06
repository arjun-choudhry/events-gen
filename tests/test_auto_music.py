"""Tests for auto-selected, non-repetitive Jamendo music."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from events_gen.content.builder import build_content
from events_gen.content.jamendo import fetch_track
from events_gen.models import City, Event, EventType, PostContent, PostDraft, TimeWindow
from events_gen.settings import Settings
from events_gen.storage import Storage

CITY = City(
    slug="tokyo",
    name="Tokyo",
    country="Japan",
    country_code="JP",
    timezone="Asia/Tokyo",
    latitude=35.68,
    longitude=139.65,
)
MUSIC = EventType(slug="music", name="Music")


def _event(title: str = "Show") -> Event:
    return Event(
        source="mock", title=title, start=datetime(2026, 7, 8, 20, tzinfo=UTC), city_slug="tokyo"
    )


def _settings(tmp_path: Path, **extra: str) -> Settings:
    return Settings(_env_file=None, EG_DATA_DIR=str(tmp_path / "data"), **extra)  # type: ignore[arg-type]


def _tracks_response(*ids: str) -> dict[str, object]:
    return {
        "results": [
            {"id": tid, "name": f"Track {tid}", "audio": f"https://audio/{tid}.mp3"} for tid in ids
        ]
    }


# ── fetch_track ──


def test_returns_none_without_client_id(tmp_path: Path) -> None:
    s = _settings(tmp_path)  # no JAMENDO_CLIENT_ID
    assert fetch_track(tmp_path, settings=s) is None


def test_fetches_top_track(tmp_path: Path) -> None:
    s = _settings(tmp_path, JAMENDO_CLIENT_ID="cid")

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.jamendo.com" in str(request.url):
            return httpx.Response(200, json=_tracks_response("111", "222"))
        return httpx.Response(200, content=b"ID3fake-mp3")  # audio download

    client = httpx.Client(transport=httpx.MockTransport(handler))
    track = fetch_track(tmp_path, client=client, settings=s)
    assert track is not None
    assert track.track_id == "111"  # top-ranked
    assert track.path.exists()


def test_excludes_recent_tracks(tmp_path: Path) -> None:
    s = _settings(tmp_path, JAMENDO_CLIENT_ID="cid")

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.jamendo.com" in str(request.url):
            return httpx.Response(200, json=_tracks_response("111", "222", "333"))
        return httpx.Response(200, content=b"ID3fake-mp3")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    # 111 and 222 used recently → should pick 333.
    track = fetch_track(tmp_path, exclude_ids=["111", "222"], client=client, settings=s)
    assert track is not None
    assert track.track_id == "333"


def test_none_when_all_excluded(tmp_path: Path) -> None:
    s = _settings(tmp_path, JAMENDO_CLIENT_ID="cid")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_tracks_response("111"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_track(tmp_path, exclude_ids=["111"], client=client, settings=s) is None


def test_api_failure_degrades_to_none(tmp_path: Path) -> None:
    s = _settings(tmp_path, JAMENDO_CLIENT_ID="cid")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_track(tmp_path, client=client, settings=s) is None  # never raises


# ── storage anti-repetition history ──


def test_recent_music_track_ids(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    for tid in ("jamendo:1", "jamendo:2", None, "jamendo:3"):
        content = PostContent(title="t", caption="c", music_track_id=tid)
        storage.save_draft(
            PostDraft(city_slug="tokyo", window=TimeWindow.WEEK, event_count=1, content=content)
        )
    ids = storage.recent_music_track_ids(limit=10)
    # None entry skipped; most-recent first.
    assert ids == ["jamendo:3", "jamendo:2", "jamendo:1"]


def test_recent_music_track_ids_respects_limit(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    for i in range(5):
        content = PostContent(title="t", caption="c", music_track_id=f"jamendo:{i}")
        storage.save_draft(
            PostDraft(city_slug="tokyo", window=TimeWindow.WEEK, event_count=1, content=content)
        )
    assert len(storage.recent_music_track_ids(limit=2)) == 2


# ── builder integration ──


def test_builder_auto_music_off_by_default(tmp_path: Path) -> None:
    s = _settings(tmp_path, EG_ASSETS_DIR=str(tmp_path / "assets"))
    content = build_content(
        CITY, [_event()], [MUSIC], "week", draft_id="d1", settings=s, size=(320, 568)
    )
    assert content.music_track_id is None  # auto_music defaults off


def test_builder_upload_beats_auto_music(tmp_path: Path) -> None:
    s = _settings(tmp_path, JAMENDO_CLIENT_ID="cid", EG_ASSETS_DIR=str(tmp_path / "assets"))
    upload = tmp_path / "mine.mp3"
    upload.write_bytes(b"ID3mine")
    content = build_content(
        CITY,
        [_event()],
        [MUSIC],
        "week",
        draft_id="d1",
        music_upload=upload,
        auto_music=True,
        settings=s,
        size=(320, 568),
    )
    # Upload wins; no Jamendo call, no track id.
    assert content.music_path == str(upload)
    assert content.music_track_id is None
