"""Publisher interface + shared helpers for publishing drafts.

Every destination (YouTube, Instagram) implements :class:`Publisher`. The
interface is intentionally small: report whether it's configured, then publish
a :class:`PostDraft`, returning a :class:`PublishResult`.

Two cross-cutting concerns live here so implementations stay focused:

- **dry-run** — when ``dry_run=True`` a publisher performs no network calls and
  returns a simulated success. This lets the full flow (and the UI buttons) be
  exercised end-to-end without real credentials, and powers the "try M6" steps.
- **failure isolation** — :meth:`Publisher.safe_publish` never raises; it maps
  any error to a failed :class:`PublishResult` so one destination failing does
  not abort the others (mirrors ``sources.base.safe_fetch``).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..models import Platform, PostDraft, PublishResult

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """Raised by a publisher when a draft cannot be published."""


class Publisher(ABC):
    """Publishes a rendered draft to one platform."""

    platform: Platform

    @abstractmethod
    def is_configured(self) -> bool:
        """True if credentials/config needed to publish are present."""

    @abstractmethod
    def publish(self, draft: PostDraft, *, dry_run: bool = False) -> PublishResult:
        """Publish ``draft`` and return the outcome. May raise ``PublishError``."""

    def safe_publish(self, draft: PostDraft, *, dry_run: bool = False) -> PublishResult:
        """Publish, converting any error into a failed :class:`PublishResult`."""
        try:
            return self.publish(draft, dry_run=dry_run)
        except Exception as exc:  # isolate: one platform's failure is not fatal
            logger.warning("publish to %s failed: %s", self.platform.value, exc)
            return PublishResult(platform=self.platform, success=False, error=str(exc))


def _validate_publishable(draft: PostDraft) -> str:
    """Return the draft's video path, raising ``PublishError`` if not renderable."""
    from pathlib import Path

    if draft.content is None:
        raise PublishError("draft has no content (caption); render it first")
    if not draft.video_path:
        raise PublishError("draft has no rendered video; render it first")
    if not Path(draft.video_path).exists():
        raise PublishError(f"rendered video missing on disk: {draft.video_path}")
    return draft.video_path


def build_description(draft: PostDraft) -> str:
    """Compose a caption/description body from the draft's content."""
    content = draft.content
    if content is None:  # pragma: no cover - guarded by _validate_publishable
        return ""
    parts = [content.caption]
    if content.hashtags:
        parts.append(" ".join(content.hashtags))
    return "\n\n".join(p for p in parts if p)
