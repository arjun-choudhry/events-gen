"""Tests for M8 hardening: HTTP retry helper + demo command + IG retry integration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from events_gen.cli import main
from events_gen.models import Event, PostContent, PostDraft
from events_gen.publish._http import request_with_retry
from events_gen.publish.hosting import VideoHost
from events_gen.publish.instagram import InstagramPublisher
from events_gen.settings import Settings

# ── request_with_retry ──


class TestRetryHelper:
    def test_returns_on_success(self) -> None:
        calls = {"n": 0}

        def call() -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, request=httpx.Request("GET", "https://x"), json={"ok": True})

        resp = request_with_retry(call)
        assert resp.json() == {"ok": True}
        assert calls["n"] == 1

    def test_retries_on_500_then_succeeds(self) -> None:
        calls = {"n": 0}

        def call() -> httpx.Response:
            calls["n"] += 1
            request = httpx.Request("GET", "https://x")
            if calls["n"] < 3:
                return httpx.Response(500, request=request)
            return httpx.Response(200, request=request, json={"ok": True})

        resp = request_with_retry(call)
        assert resp.status_code == 200
        assert calls["n"] == 3

    def test_retries_on_429(self) -> None:
        calls = {"n": 0}

        def call() -> httpx.Response:
            calls["n"] += 1
            request = httpx.Request("GET", "https://x")
            if calls["n"] < 2:
                return httpx.Response(429, request=request)
            return httpx.Response(200, request=request, json={})

        request_with_retry(call)
        assert calls["n"] == 2

    def test_does_not_retry_on_400(self) -> None:
        calls = {"n": 0}

        def call() -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(400, request=httpx.Request("GET", "https://x"))

        with pytest.raises(httpx.HTTPStatusError):
            request_with_retry(call)
        assert calls["n"] == 1  # 4xx (except 429) is not retried

    def test_retries_transport_error(self) -> None:
        calls = {"n": 0}

        def call() -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 2:
                raise httpx.ConnectError("boom")
            return httpx.Response(200, request=httpx.Request("GET", "https://x"), json={})

        request_with_retry(call)
        assert calls["n"] == 2


# ── Instagram integration: transient failure is retried through the flow ──


def _rendered_draft(tmp_path: Path) -> PostDraft:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    return PostDraft(
        city_slug="tokyo",
        window="week",  # type: ignore[arg-type]
        event_count=1,
        events=[
            Event(
                source="mock", title="X", start=datetime(2026, 7, 8, tzinfo=UTC), city_slug="tokyo"
            )
        ],
        content=PostContent(title="T", caption="c", hashtags=[]),
        video_path=str(video),
    )


def test_instagram_retries_transient_5xx(tmp_path: Path) -> None:
    s = Settings(  # type: ignore[call-arg]
        _env_file=None,
        EG_DATA_DIR=str(tmp_path / "data"),
        INSTAGRAM_ACCESS_TOKEN="tok",
        INSTAGRAM_BUSINESS_ACCOUNT_ID="acct",
        EG_PUBLIC_VIDEO_BASE_URL="https://cdn.example.com",
    )
    s.ensure_dirs()
    draft = _rendered_draft(tmp_path)

    state = {"container_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/media"):
            state["container_calls"] += 1
            if state["container_calls"] == 1:
                return httpx.Response(503, request=request)  # transient → retried
            return httpx.Response(200, json={"id": "c1"})
        if "media_publish" in url:
            return httpx.Response(200, json={"id": "m1"})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pub = InstagramPublisher(settings=s, host=VideoHost(settings=s), client=client, poll_interval=0)
    result = pub.publish(draft, dry_run=False)
    assert result.success
    assert result.external_id == "m1"
    assert state["container_calls"] == 2  # first 503, then success


def test_instagram_gives_up_on_bad_token_400(tmp_path: Path) -> None:
    s = Settings(  # type: ignore[call-arg]
        _env_file=None,
        EG_DATA_DIR=str(tmp_path / "data"),
        INSTAGRAM_ACCESS_TOKEN="bad",
        INSTAGRAM_BUSINESS_ACCOUNT_ID="acct",
        EG_PUBLIC_VIDEO_BASE_URL="https://cdn.example.com",
    )
    s.ensure_dirs()
    draft = _rendered_draft(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, request=request, json={"error": "bad token"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pub = InstagramPublisher(settings=s, client=client, poll_interval=0)
    with pytest.raises(httpx.HTTPStatusError):
        pub.publish(draft, dry_run=False)


# ── demo command (end-to-end, keyless) ──


def test_demo_command_runs_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EG_DATA_DIR", str(tmp_path / "data"))
    # get_settings is cached; clear it so the env override takes effect.
    from events_gen import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    try:
        rc = main(["demo", "new-york", "--count", "3"])
    finally:
        settings_mod.get_settings.cache_clear()
    assert rc == 0
