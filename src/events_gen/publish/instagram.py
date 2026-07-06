"""Instagram publisher — Instagram Graph API (M6.4/M6.5).

Publishing a Reel is a two-step flow:

1. **Create a media container** referencing a public ``video_url`` (see
   :mod:`.hosting`) — the Graph API downloads and transcodes asynchronously.
2. **Poll** the container's ``status_code`` until ``FINISHED``.
3. **Publish** the container to the account's feed.

Requires an Instagram Business/Creator account linked to a Facebook Page, a Meta
app with the Instagram Graph API, and a long-lived access token
(``INSTAGRAM_ACCESS_TOKEN`` + ``INSTAGRAM_BUSINESS_ACCOUNT_ID``).

``poll_interval``/``max_polls`` are injectable so tests don't sleep.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx

from ..models import Platform, PostDraft, PublishResult
from ..settings import Settings, get_settings
from .base import Publisher, PublishError, _validate_publishable, build_description
from .hosting import VideoHost

logger = logging.getLogger(__name__)

_GRAPH = "https://graph.facebook.com/v21.0"
_PERMALINK = "https://www.instagram.com/reel/{id}/"


class InstagramPublisher(Publisher):
    """Publishes a draft's video to Instagram as a Reel."""

    platform = Platform.INSTAGRAM

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        host: VideoHost | None = None,
        client: httpx.Client | None = None,
        poll_interval: float = 5.0,
        max_polls: int = 60,
    ) -> None:
        self.settings = settings or get_settings()
        self.host = host or VideoHost(self.settings)
        self._client = client
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    def is_configured(self) -> bool:
        return bool(
            self.settings.instagram_access_token and self.settings.instagram_business_account_id
        )

    def publish(self, draft: PostDraft, *, dry_run: bool = False) -> PublishResult:
        video_path = _validate_publishable(draft)

        if dry_run:
            logger.info("[dry-run] would publish %s to Instagram as a Reel", video_path)
            return PublishResult(
                platform=self.platform,
                success=True,
                external_id="dry-run-media-id",
                url=_PERMALINK.format(id="dry-run-media-id"),
                published_at=datetime.now(UTC),
            )

        if not self.is_configured():
            raise PublishError(
                "Instagram not configured; set INSTAGRAM_ACCESS_TOKEN and "
                "INSTAGRAM_BUSINESS_ACCOUNT_ID"
            )
        if not self.host.is_configured():
            raise PublishError("Instagram needs a public video URL; set EG_PUBLIC_VIDEO_BASE_URL")

        video_url = self.host.public_url(video_path)
        caption = build_description(draft)

        client = self._client or httpx.Client(timeout=30.0)
        try:
            container_id = self._create_container(client, video_url, caption)
            self._await_container(client, container_id)
            media_id = self._publish_container(client, container_id)
        finally:
            if self._client is None:
                client.close()

        return PublishResult(
            platform=self.platform,
            success=True,
            external_id=media_id,
            url=_PERMALINK.format(id=media_id),
            published_at=datetime.now(UTC),
        )

    # ── internals ──

    @property
    def _account(self) -> str:
        return self.settings.instagram_business_account_id or ""

    @property
    def _token(self) -> str:
        return self.settings.instagram_access_token or ""

    def _create_container(self, client: httpx.Client, video_url: str, caption: str) -> str:
        resp = client.post(
            f"{_GRAPH}/{self._account}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "access_token": self._token,
            },
        )
        resp.raise_for_status()
        container_id: str = resp.json()["id"]
        logger.info("created IG media container %s", container_id)
        return container_id

    def _await_container(self, client: httpx.Client, container_id: str) -> None:
        """Poll the container until it's FINISHED; raise on error/timeout."""
        for _ in range(self.max_polls):
            resp = client.get(
                f"{_GRAPH}/{container_id}",
                params={"fields": "status_code", "access_token": self._token},
            )
            resp.raise_for_status()
            status = resp.json().get("status_code")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise PublishError("Instagram failed to process the video container")
            time.sleep(self.poll_interval)
        raise PublishError("Instagram container did not finish in time")

    def _publish_container(self, client: httpx.Client, container_id: str) -> str:
        resp = client.post(
            f"{_GRAPH}/{self._account}/media_publish",
            data={"creation_id": container_id, "access_token": self._token},
        )
        resp.raise_for_status()
        media_id: str = resp.json()["id"]
        logger.info("published IG media %s", media_id)
        return media_id
