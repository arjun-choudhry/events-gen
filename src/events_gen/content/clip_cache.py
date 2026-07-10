"""Disk-backed per-(draft, event, source) clip cache.

Clips are multi-MB files that must survive Streamlit reruns, so the cache lives
on disk under the draft's output dir rather than in session state. Re-rendering
an event with the same source reuses the cached clip instead of re-downloading.
The cache is cleared for a draft when it's published.

Layout: ``data/output/<draft_id>/clip_cache/<event_id>/<source>.mp4``
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..settings import Settings

logger = logging.getLogger(__name__)


def _cache_dir(settings: Settings, draft_id: str) -> Path:
    return settings.output_dir / draft_id / "clip_cache"


def cache_path(settings: Settings, draft_id: str, event_id: str, source: str) -> Path:
    """Return the canonical cache path for one (event, source) clip."""
    return _cache_dir(settings, draft_id) / event_id / f"{source}.mp4"


def get_cached(settings: Settings, draft_id: str, event_id: str, source: str) -> Path | None:
    """Return the cached clip path if it exists and is non-empty, else None."""
    path = cache_path(settings, draft_id, event_id, source)
    if path.exists() and path.stat().st_size > 0:
        return path
    return None


def store_clip(
    settings: Settings, draft_id: str, event_id: str, source: str, src_path: Path
) -> Path:
    """Copy ``src_path`` into the cache slot for (event, source) and return it."""
    dest = cache_path(settings, draft_id, event_id, source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_path, dest)
    return dest


def clear_draft_cache(settings: Settings, draft_id: str) -> None:
    """Remove all cached clips for a draft (called after publish)."""
    shutil.rmtree(_cache_dir(settings, draft_id), ignore_errors=True)
    logger.info("cleared clip cache for draft %s", draft_id)
