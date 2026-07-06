"""The :class:`ImageProvider` interface for producing background images.

A provider turns a text prompt (typically describing a city) into an image file
on disk at a requested size, returning its path. Concrete providers: a keyless
:class:`MockProvider` (Pillow-generated placeholder) for dev, and an
:class:`AIImageProvider` that calls a configured image-generation API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ImageProvider(ABC):
    """Abstract background-image source."""

    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the provider can produce images (e.g. has an API key)."""

    @abstractmethod
    def generate(self, prompt: str, out_path: Path, size: tuple[int, int]) -> Path:
        """Generate an image for ``prompt`` at ``size`` (w, h), write it to ``out_path``.

        Returns the path written (``out_path``). May raise; callers decide whether
        to fall back to another provider.
        """
