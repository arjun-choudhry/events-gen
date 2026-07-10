"""Tests for the keyless Openverse audio music source."""

from __future__ import annotations

from pathlib import Path

import httpx

from events_gen.content import openverse_audio
from events_gen.content.openverse_audio import _queries, fetch_track
from events_gen.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, EG_DATA_DIR=str(tmp_path / "data"))  # type: ignore[call-arg]


def _audio_response(*ids: str, duration: int = 120_000) -> dict[str, object]:
    return {
        "results": [
            {"id": tid, "title": f"Track {tid}", "url": f"https://audio/{tid}.mp3",
             "duration": duration}
            for tid in ids
        ]
    }


def test_mood_queries_differ_by_type() -> None:
    assert _queries("music") != _queries("arts")
    assert _queries(None) == _queries("unknown-slug")  # both fall back to default


def test_fetches_a_track(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "api.openverse.org" in str(request.url):
            return httpx.Response(200, json=_audio_response("a1", "a2"))
        return httpx.Response(200, content=b"ID3fake")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    track = fetch_track(tmp_path, event_type="music", client=client, settings=_settings(tmp_path))
    assert track is not None
    assert track.track_id in {"a1", "a2"}
    assert track.path.exists()


def test_skips_short_clips(tmp_path: Path) -> None:
    # A 5s result is an SFX/loop, not a music bed → skipped, yielding None.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_audio_response("short", duration=5_000))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_track(tmp_path, client=client, settings=_settings(tmp_path)) is None


def test_excludes_recent_prefixed_ids(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "api.openverse.org" in str(request.url):
            return httpx.Response(200, json=_audio_response("only"))
        return httpx.Response(200, content=b"ID3fake")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch_track(
        tmp_path, exclude_ids=["openverse:only"], client=client, settings=_settings(tmp_path)
    )
    assert result is None


def test_api_failure_degrades_to_none(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_track(tmp_path, client=client, settings=_settings(tmp_path)) is None


def test_module_constants_sane() -> None:
    # Every mapped type offers multiple vibe queries.
    assert all(len(v) >= 2 for v in openverse_audio._MOOD_QUERIES.values())
