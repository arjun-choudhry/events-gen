"""AI image-generation provider (provider-agnostic).

This is the seam for plugging in a real image-generation API (M3 open item —
the specific provider is chosen at config time). It reads ``EG_IMAGE_API_KEY``
and, when a concrete client is wired in, calls it and writes the returned image
to disk. Until then ``generate`` raises ``NotImplementedError`` so the factory's
fallback to the mock provider keeps the pipeline working.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...settings import Settings, get_settings
from .base import ImageProvider

logger = logging.getLogger(__name__)


class AIImageProvider(ImageProvider):
    """Background images from a configured AI image-generation API."""

    name = "ai"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def is_configured(self) -> bool:
        return bool(self._settings.image_api_key)

    def generate(self, prompt: str, out_path: Path, size: tuple[int, int]) -> Path:
        # Wire a concrete image API here (request → bytes → write to out_path).
        # Left unimplemented until a provider is chosen (see PLAN §9); the
        # factory falls back to MockProvider so dev/CI is unaffected.
        raise NotImplementedError(
            "AI image provider not yet wired to a concrete API; "
            "set EG_IMAGE_PROVIDER=mock or implement AIImageProvider.generate"
        )
