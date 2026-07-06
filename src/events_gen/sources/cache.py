"""A small TTL file cache for API responses.

Sources cache raw JSON payloads keyed by a request signature (source name +
params) so repeated queries during development don't burn rate limits. Entries
are plain JSON files under ``data/cache/`` with an embedded expiry timestamp;
expired or missing entries return ``None``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ResponseCache:
    """Filesystem-backed TTL cache for JSON-serializable payloads."""

    def __init__(self, cache_dir: Path, *, default_ttl: int = 3600) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl

    @staticmethod
    def _signature(source: str, params: dict[str, Any]) -> str:
        # Sort keys so equivalent param dicts map to the same file.
        blob = json.dumps({"source": source, "params": params}, sort_keys=True, default=str)
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
        return f"{source}_{digest}"

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, source: str, params: dict[str, Any]) -> Any | None:
        """Return the cached payload if present and unexpired, else ``None``."""
        path = self._path(self._signature(source, params))
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("corrupt cache entry %s; ignoring", path.name)
            return None
        if entry.get("expires_at", 0) < time.time():
            return None
        return entry.get("payload")

    def set(
        self,
        source: str,
        params: dict[str, Any],
        payload: Any,
        *,
        ttl: int | None = None,
    ) -> None:
        """Store ``payload`` under the request signature with a TTL."""
        path = self._path(self._signature(source, params))
        entry = {
            "expires_at": time.time() + (ttl if ttl is not None else self.default_ttl),
            "payload": payload,
        }
        try:
            path.write_text(json.dumps(entry, default=str), encoding="utf-8")
        except OSError:
            logger.warning("failed to write cache entry %s", path.name)

    def clear(self) -> int:
        """Delete all cache entries; return the count removed."""
        count = 0
        for file in self.cache_dir.glob("*.json"):
            file.unlink(missing_ok=True)
            count += 1
        return count
