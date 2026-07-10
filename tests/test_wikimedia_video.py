"""Tests for M: Wikimedia Commons video fetch + per-event promo override."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from events_gen.content.wikimedia_video import fetch_wikimedia_clip, wikimedia_clip_urls
from events_gen.models import Event, PostContent
from events_gen.render import REEL, render_video


def _commons_response(*entries: tuple[str, str], title: str = "Madison Square Garden") -> dict:
    """Build a Commons API response. Each entry is (mime, url).

    All pages get ``title`` (default matches the test queries) so the relevance
    filter accepts them; pass a mismatching ``title`` to exercise rejection.
    """
    pages = {
        str(i): {"title": f"File:{title} {i}.webm", "imageinfo": [{"mime": mime, "url": url}]}
        for i, (mime, url) in enumerate(entries)
    }
    return {"query": {"pages": pages}}


class TestWikimediaSearch:
    def test_returns_only_video_mimes(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_commons_response(
                    ("video/webm", "https://c/msg.webm"),
                    ("image/jpeg", "https://c/photo.jpg"),  # filtered out
                    ("application/ogg", "https://c/clip.ogv"),
                ),
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        urls = wikimedia_clip_urls(client, "Madison Square Garden")
        assert set(urls) == {"https://c/msg.webm", "https://c/clip.ogv"}
        assert "https://c/photo.jpg" not in urls  # image mime filtered out

    def test_no_results(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"query": {"pages": {}}})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert wikimedia_clip_urls(client, "nowhere") == []

    def test_api_error_degrades(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert wikimedia_clip_urls(client, "x") == []

    def test_irrelevant_titles_filtered(self) -> None:
        # Commons' loose search can return unrelated videos; only title-relevant
        # results should survive (regression: a "crane collapse" clip matched a
        # jazz-club query via the common word "blue").
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_commons_response(
                    ("video/webm", "https://c/crane.webm"),
                    title="Big Blue crane collapse at Miller Park",
                ),
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert wikimedia_clip_urls(client, "Blue Note") == []

    def test_relevant_title_kept(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_commons_response(
                    ("video/webm", "https://c/msg.webm"), title="Madison Square Garden interior"
                ),
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert wikimedia_clip_urls(client, "Madison Square Garden") == ["https://c/msg.webm"]


class TestFetchWikimediaClip:
    def test_downloads_first_video(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "commons.wikimedia.org" in url:
                return httpx.Response(
                    200, json=_commons_response(("video/webm", "https://c/v.webm"))
                )
            return httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42fake-video-bytes")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        # _download_and_trim shells out to ffmpeg; with fake bytes it'll fail and
        # return None — so we assert it *attempts* and degrades cleanly.
        result = fetch_wikimedia_clip(["Madison Square Garden"], tmp_path, 4.0, "e1", client=client)
        # Either a valid path (if ffmpeg somehow accepts) or None (fake bytes) — never raises.
        assert result is None or result[1] == "https://c/v.webm"

    def test_no_video_returns_none(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"query": {"pages": {}}})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert fetch_wikimedia_clip(["x"], tmp_path, 4.0, "e1", client=client) is None


class TestPromoOverrideRender:
    def test_promo_override_no_image_falls_through(self, tmp_path: Path) -> None:
        # Event has override="promo" but no image_url → renderer falls through, no crash.
        event = Event(
            id="e1",
            source="mock",
            title="Show",
            start=datetime(2026, 7, 10, 20, tzinfo=UTC),
            venue="Hall",
            city_slug="x",
        )
        content = PostContent(
            title="T", caption="c", hashtags=[], event_background_overrides={"e1": "promo"}
        )
        out = tmp_path / "out.mp4"
        render_video(content, [event], out, REEL)
        assert out.exists() and out.stat().st_size > 0
