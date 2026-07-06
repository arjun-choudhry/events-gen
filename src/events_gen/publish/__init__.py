"""Publishing: push a rendered draft to YouTube and/or Instagram.

Public API:
    get_publisher(platform)          -> Publisher for one platform
    publish_draft(draft, targets, …) -> list[PublishResult], persisted on the draft

``publish_draft`` is the single entry point the UI and scheduler call. It
publishes to each requested target with failure isolation (one platform failing
does not abort the others), records the results on the draft, updates the draft
status, and persists everything (M6.6).
"""

from __future__ import annotations

import logging

from ..models import DraftStatus, Job, JobStatus, Platform, PostDraft, PublishResult
from ..settings import Settings, get_settings
from ..storage import Storage
from .base import Publisher, PublishError
from .hosting import HostingError, VideoHost
from .instagram import InstagramPublisher
from .youtube import YouTubePublisher

logger = logging.getLogger(__name__)

__all__ = [
    "Publisher",
    "PublishError",
    "HostingError",
    "VideoHost",
    "YouTubePublisher",
    "InstagramPublisher",
    "get_publisher",
    "publish_draft",
]


def get_publisher(platform: Platform, *, settings: Settings | None = None) -> Publisher:
    """Return the publisher for ``platform``."""
    settings = settings or get_settings()
    if platform is Platform.YOUTUBE:
        return YouTubePublisher(settings=settings)
    if platform is Platform.INSTAGRAM:
        return InstagramPublisher(settings=settings)
    raise ValueError(f"no publisher for platform: {platform!r}")  # pragma: no cover


def publish_draft(
    draft: PostDraft,
    targets: list[Platform] | None = None,
    *,
    dry_run: bool = False,
    storage: Storage | None = None,
    settings: Settings | None = None,
) -> list[PublishResult]:
    """Publish ``draft`` to each target, persisting results and status.

    ``targets`` defaults to the draft's own ``targets``. Uses ``safe_publish`` so
    a single platform failure is captured as a failed result rather than raising.
    """
    settings = settings or get_settings()
    storage = storage or Storage(settings.db_path)
    to_publish = targets if targets is not None else draft.targets
    if not to_publish:
        raise PublishError("no publish targets specified")

    draft.status = DraftStatus.PUBLISHING
    storage.save_draft(draft)

    results: list[PublishResult] = []
    for platform in to_publish:
        publisher = get_publisher(platform, settings=settings)
        result = publisher.safe_publish(draft, dry_run=dry_run)
        results.append(result)
        logger.info(
            "published draft %s to %s: %s",
            draft.id,
            platform.value,
            "ok" if result.success else "FAILED",
        )

    # Merge results (replace any prior result for the same platform).
    by_platform = {r.platform: r for r in draft.results}
    for r in results:
        by_platform[r.platform] = r
    draft.results = list(by_platform.values())

    all_ok = all(r.success for r in results)
    draft.status = DraftStatus.PUBLISHED if all_ok else DraftStatus.FAILED
    storage.save_draft(draft)

    # Record a history job (M6.6).
    detail = ", ".join(f"{r.platform.value}={'ok' if r.success else 'fail'}" for r in results)
    storage.save_job(
        Job(
            kind="publish",
            draft_id=draft.id,
            status=JobStatus.SUCCEEDED if all_ok else JobStatus.FAILED,
            detail=f"{'[dry-run] ' if dry_run else ''}{detail}",
            error=None if all_ok else "; ".join(r.error or "" for r in results if not r.success),
        )
    )
    return results
