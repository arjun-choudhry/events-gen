"""YouTube publisher — YouTube Data API v3 (M6.2).

Uploads a rendered mp4 as a video (or Short, when the render is 9:16) via a
resumable upload. Auth is OAuth 2.0 installed-app flow: a client-secrets JSON
(from a Google Cloud project with the YouTube Data API enabled) plus a cached
token file that's refreshed automatically.

The heavy Google client libraries are imported lazily inside methods so the
package imports cleanly without the optional ``publish`` extra installed, and so
dry-run needs no credentials at all.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ..models import Platform, PostDraft, PublishResult
from ..settings import Settings, get_settings
from .base import Publisher, PublishError, _validate_publishable, build_description

logger = logging.getLogger(__name__)

# OAuth scope for uploading videos.
_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
_WATCH_URL = "https://www.youtube.com/watch?v={id}"


class YouTubePublisher(Publisher):
    """Publishes a draft's video to YouTube."""

    platform = Platform.YOUTUBE

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        privacy_status: str = "private",
    ) -> None:
        self.settings = settings or get_settings()
        self.privacy_status = privacy_status

    def is_configured(self) -> bool:
        secrets = self.settings.youtube_client_secrets_file
        return bool(secrets and secrets.exists())

    def publish(self, draft: PostDraft, *, dry_run: bool = False) -> PublishResult:
        video_path = _validate_publishable(draft)
        content = draft.content
        assert content is not None  # guaranteed by _validate_publishable

        if dry_run:
            logger.info("[dry-run] would upload %s to YouTube", video_path)
            return PublishResult(
                platform=self.platform,
                success=True,
                external_id="dry-run-video-id",
                url=_WATCH_URL.format(id="dry-run-video-id"),
                published_at=datetime.now(UTC),
            )

        if not self.is_configured():
            raise PublishError(
                "YouTube not configured; set YOUTUBE_CLIENT_SECRETS_FILE "
                "(and authorize on first run)"
            )

        service = self._build_service()
        body = {
            "snippet": {
                "title": content.title[:100],  # YouTube title cap
                "description": build_description(draft),
                "tags": [t.lstrip("#") for t in content.hashtags][:15],
                "categoryId": "24",  # Entertainment
            },
            "status": {"privacyStatus": self.privacy_status},
        }
        try:
            video_id = self._resumable_upload(service, video_path, body)
        except Exception as exc:  # map API failures to actionable messages (M8.3)
            raise self._friendly_error(exc) from exc
        return PublishResult(
            platform=self.platform,
            success=True,
            external_id=video_id,
            url=_WATCH_URL.format(id=video_id),
            published_at=datetime.now(UTC),
        )

    # ── internals ──

    def _build_service(self) -> Any:
        """Build an authorized YouTube API client, refreshing/creating the token."""
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        token_file = self.settings.youtube_token_file
        creds: Credentials | None = None
        if token_file and token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), _SCOPES)

        try:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            elif not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.settings.youtube_client_secrets_file), _SCOPES
                )
                creds = flow.run_local_server(port=0)
                if token_file:
                    token_file.parent.mkdir(parents=True, exist_ok=True)
                    token_file.write_text(creds.to_json())
        except RefreshError as exc:
            raise PublishError(
                "YouTube token expired and could not be refreshed; delete "
                f"{token_file} and re-run to re-authorize your channel"
            ) from exc

        return build("youtube", "v3", credentials=creds)

    @staticmethod
    def _friendly_error(exc: Exception) -> PublishError:
        """Map a Google API error to an actionable :class:`PublishError` (M8.3)."""
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status == 403:
            return PublishError(
                "YouTube upload rejected (403): daily quota exceeded or the "
                "channel lacks upload permission. Check your API quota in Google "
                "Cloud Console, or try again tomorrow."
            )
        if status in (401, 400):
            return PublishError(
                "YouTube rejected the credentials (re-auth needed): delete the "
                "token file and re-run to authorize."
            )
        return PublishError(f"YouTube upload failed: {exc}")

    def _resumable_upload(self, service: Any, video_path: str, body: dict[str, Any]) -> str:
        """Upload the video with a resumable request; return the new video id."""
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        request = service.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _status, response = request.next_chunk()
        video_id: str = response["id"]
        logger.info("uploaded YouTube video %s", video_id)
        return video_id
