"""Public video hosting helper (M6.3).

Instagram Reel publishing is a two-step flow that requires a **publicly
reachable URL** to the mp4 (the Graph API fetches the video itself). This
module turns a local rendered file into such a URL.

The default strategy is ``public_base_url``: you copy/serve rendered files under
a directory exposed at ``EG_PUBLIC_VIDEO_BASE_URL`` (an S3 bucket, a static host,
or an ngrok/cloudflared tunnel pointing at ``data/output``). Given a local path
we derive ``<base_url>/<draft_id>/<file>``.

If no base URL is configured, hosting is *unavailable* and the Instagram
publisher degrades to dry-run/failure with a clear message rather than guessing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..settings import Settings, get_settings

logger = logging.getLogger(__name__)


class HostingError(Exception):
    """Raised when a local video cannot be exposed at a public URL."""


class VideoHost:
    """Maps a locally-rendered mp4 to a public URL for Instagram to fetch."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def is_configured(self) -> bool:
        return bool(self.settings.public_video_base_url)

    def public_url(self, local_path: str | Path) -> str:
        """Return the public URL for ``local_path``.

        Assumes files under ``data/output/`` are served at
        ``EG_PUBLIC_VIDEO_BASE_URL`` with the same relative layout.
        """
        base = self.settings.public_video_base_url
        if not base:
            raise HostingError(
                "no public video host configured; set EG_PUBLIC_VIDEO_BASE_URL "
                "(required for Instagram publishing)"
            )
        path = Path(local_path)
        output_dir = self.settings.output_dir
        try:
            rel = path.resolve().relative_to(output_dir.resolve())
        except ValueError:
            # Not under output_dir — fall back to just the filename.
            rel = Path(path.name)
        return f"{base.rstrip('/')}/{rel.as_posix()}"
