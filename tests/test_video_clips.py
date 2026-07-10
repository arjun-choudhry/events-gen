"""Tests for stock clip URL selection — always pick the highest-resolution file."""

from __future__ import annotations

import httpx
import pytest

from events_gen.content import video_clips
from events_gen.content.video_clips import (
    ClipLinkError,
    _coverr_clip_urls,
    _pexels_clip_urls,
    _pixabay_clip_urls,
    _search_queries,
    provider_available,
    provider_from_url,
    resolve_clip_url,
)
from events_gen.models import Event
from events_gen.settings import Settings


@pytest.fixture()
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        PEXELS_API_KEY="pk",
        PIXABAY_API_KEY="xk",
    )


def _client(payload: dict) -> httpx.Client:
    """An httpx client whose every GET returns ``payload`` as JSON."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestPexelsResolution:
    def test_picks_highest_resolution_file(self, settings: Settings) -> None:
        payload = {
            "videos": [
                {
                    "video_files": [
                        {"link": "sd.mp4", "width": 640, "height": 360},
                        {"link": "uhd.mp4", "width": 3840, "height": 2160},
                        {"link": "hd.mp4", "width": 1280, "height": 720},
                    ]
                }
            ]
        }
        urls = _pexels_clip_urls(_client(payload), "concert", settings)
        assert urls == ["uhd.mp4"]  # 4K beats 720p/360p, not just "first ≥720p"

    def test_no_key_returns_empty(self) -> None:
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert _pexels_clip_urls(_client({}), "x", s) == []

    def test_handles_empty_files(self, settings: Settings) -> None:
        assert _pexels_clip_urls(_client({"videos": [{"video_files": []}]}), "x", settings) == []


class TestPixabayResolution:
    def test_picks_largest_rendition(self, settings: Settings) -> None:
        payload = {
            "hits": [
                {
                    "videos": {
                        "medium": {"url": "med.mp4", "width": 1920, "height": 1080},
                        "small": {"url": "small.mp4", "width": 960, "height": 540},
                        "large": {"url": "large.mp4", "width": 3840, "height": 2160},
                    }
                }
            ]
        }
        urls = _pixabay_clip_urls(_client(payload), "concert", settings)
        assert urls == ["large.mp4"]  # not "medium" first as before

    def test_skips_entries_without_url(self, settings: Settings) -> None:
        payload = {
            "hits": [
                {
                    "videos": {
                        "large": {"width": 3840, "height": 2160},  # no url
                        "medium": {"url": "med.mp4", "width": 1920, "height": 1080},
                    }
                }
            ]
        }
        urls = _pixabay_clip_urls(_client(payload), "x", settings)
        assert urls == ["med.mp4"]

    def test_no_key_returns_empty(self) -> None:
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert _pixabay_clip_urls(_client({}), "x", s) == []


class TestCoverr:
    def test_returns_download_urls(self) -> None:
        s = Settings(_env_file=None, COVERR_API_KEY="ck")  # type: ignore[call-arg]
        payload = {
            "hits": [
                {"urls": {"mp4_download": "dl.mp4", "mp4_preview": "prev.mp4"}},
                {"urls": {"mp4": "plain.mp4"}},
            ]
        }
        assert _coverr_clip_urls(_client(payload), "concert", s) == ["dl.mp4", "plain.mp4"]

    def test_no_key_returns_empty(self) -> None:
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert _coverr_clip_urls(_client({"hits": [{"urls": {"mp4": "x.mp4"}}]}), "x", s) == []

    def test_null_urls_is_skipped(self) -> None:
        # Coverr returns ``urls: null`` per hit unless urls=true is requested; the
        # parser must not crash on that (regression: switching to Coverr did nothing).
        s = Settings(_env_file=None, COVERR_API_KEY="ck")  # type: ignore[call-arg]
        payload = {"hits": [{"urls": None}, {"urls": {"mp4": "ok.mp4"}}]}
        assert _coverr_clip_urls(_client(payload), "x", s) == ["ok.mp4"]

    def test_requests_urls_flag(self) -> None:
        # The urls=true query param is what makes Coverr populate the mp4 links.
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(dict(request.url.params))
            return httpx.Response(200, json={"hits": []})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        s = Settings(_env_file=None, COVERR_API_KEY="ck")  # type: ignore[call-arg]
        _coverr_clip_urls(client, "concert", s)
        assert seen.get("urls") == "true"


class TestSearchQueries:
    def _event(self, event_type: str | None) -> Event:
        from datetime import UTC, datetime

        return Event(
            source="mock",
            title="Show",
            start=datetime(2026, 7, 8, 20, tzinfo=UTC),
            city_slug="nyc",
            event_type=event_type,
        )

    def test_type_specific_terms_present(self) -> None:
        qs = _search_queries(self._event("music"), "New York")
        assert any("concert" in q or "festival" in q or "stage" in q for q in qs)

    def test_expanded_query_pool(self) -> None:
        # The music vibe list is now much larger than the original 3 terms.
        assert len(video_clips._TYPE_QUERIES["music"]) >= 6

    def test_unknown_type_uses_generic(self) -> None:
        qs = _search_queries(self._event(None), "Paris")
        assert qs  # never empty
        assert all(isinstance(q, str) for q in qs)


class TestProviderHelpers:
    def test_provider_from_url(self) -> None:
        assert provider_from_url("https://videos.pexels.com/x.mp4") == "pexels"
        assert provider_from_url("https://cdn.pixabay.com/x.mp4") == "pixabay"
        assert provider_from_url("https://coverr.co/x.mp4") == "coverr"
        assert provider_from_url("https://example.com/x.mp4") == "stock"

    def test_provider_available_keyless_wikimedia(self) -> None:
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert provider_available("wikimedia", s) is True

    def test_provider_available_reflects_keys(self) -> None:
        s = Settings(_env_file=None, PEXELS_API_KEY="pk")  # type: ignore[call-arg]
        assert provider_available("pexels", s) is True
        assert provider_available("pixabay", s) is False
        assert provider_available("coverr", s) is False

    def test_provider_available_unknown(self) -> None:
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert provider_available("bogus", s) is False


class TestStockProviderFilter:
    def _event(self) -> Event:
        from datetime import UTC, datetime

        return Event(
            source="mock",
            title="Show",
            start=datetime(2026, 7, 8, 20, tzinfo=UTC),
            city_slug="nyc",
            event_type="music",
        )

    def test_providers_restricts_which_apis_are_called(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pathlib import Path

        called: list[str] = []
        monkeypatch.setattr(
            video_clips, "_pexels_clip_urls", lambda *a, **k: called.append("pexels") or []
        )
        monkeypatch.setattr(
            video_clips, "_pixabay_clip_urls", lambda *a, **k: called.append("pixabay") or []
        )
        monkeypatch.setattr(
            video_clips, "_coverr_clip_urls", lambda *a, **k: called.append("coverr") or []
        )
        s = Settings(_env_file=None, PEXELS_API_KEY="pk", PIXABAY_API_KEY="xk")  # type: ignore[call-arg]
        video_clips.fetch_stock_only(
            self._event(), "NYC", Path(str(tmp_path)), 4.0, providers=["pixabay"], settings=s
        )
        # Only the requested provider is queried (across all shuffled queries).
        assert set(called) == {"pixabay"}


class TestResolveClipLink:
    def _keyed(self) -> Settings:
        return Settings(  # type: ignore[call-arg]
            _env_file=None, PEXELS_API_KEY="pk", PIXABAY_API_KEY="xk", COVERR_API_KEY="ck"
        )

    def test_direct_mp4_passthrough(self) -> None:
        url = "https://cdn.example.com/clip.mp4"
        assert resolve_clip_url(url, _client({}), self._keyed()) == url

    def test_direct_url_with_query_string(self) -> None:
        url = "https://cdn.coverr.co/x/1080p.mp4?download=true"
        assert resolve_clip_url(url, _client({}), self._keyed()) == url

    def test_youtube_rejected(self) -> None:
        with pytest.raises(ClipLinkError, match="copyrighted"):
            resolve_clip_url("https://youtube.com/shorts/abc", _client({}), self._keyed())

    def test_tiktok_rejected(self) -> None:
        with pytest.raises(ClipLinkError, match="copyrighted"):
            resolve_clip_url("https://www.tiktok.com/@u/video/123", _client({}), self._keyed())

    def test_coverr_page_rejected_with_hint(self) -> None:
        with pytest.raises(ClipLinkError, match="Download button"):
            resolve_clip_url("https://coverr.co/videos/some-slug-abc", _client({}), self._keyed())

    def test_unrecognized_link_rejected(self) -> None:
        with pytest.raises(ClipLinkError, match="unrecognized"):
            resolve_clip_url("https://example.com/page", _client({}), self._keyed())

    def test_pexels_page_resolved_to_best_file(self) -> None:
        payload = {
            "video_files": [
                {"link": "sd.mp4", "width": 640, "height": 360},
                {"link": "uhd.mp4", "width": 3840, "height": 2160},
            ]
        }
        url = resolve_clip_url(
            "https://www.pexels.com/video/crowd-3571264/", _client(payload), self._keyed()
        )
        assert url == "uhd.mp4"

    def test_pexels_page_without_key(self) -> None:
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        with pytest.raises(ClipLinkError, match="PEXELS_API_KEY"):
            resolve_clip_url("https://www.pexels.com/video/x-123/", _client({}), s)

    def test_pixabay_page_resolved(self) -> None:
        payload = {"hits": [{"videos": {"large": {"url": "big.mp4", "width": 3840, "height": 2160}}}]}
        url = resolve_clip_url(
            "https://pixabay.com/videos/concert-125/", _client(payload), self._keyed()
        )
        assert url == "big.mp4"

    def test_empty_link_rejected(self) -> None:
        with pytest.raises(ClipLinkError, match="empty"):
            resolve_clip_url("   ", _client({}), self._keyed())
