"""A keyless placeholder image provider for development.

Generates a deterministic gradient background with the prompt text overlaid,
using Pillow. No network, no API key — so the full content/render pipeline runs
in dev. The gradient colors are derived from the prompt hash so different cities
get visually distinct (but stable) backgrounds.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .base import ImageProvider


def _color_from(text: str, offset: int = 0) -> tuple[int, int, int]:
    digest = hashlib.sha256(f"{text}:{offset}".encode()).digest()
    # Keep tones mid-range so overlaid white text stays readable.
    return (60 + digest[0] % 140, 60 + digest[1] % 140, 60 + digest[2] % 140)


class MockProvider(ImageProvider):
    """Generates a local gradient placeholder image (no API key needed)."""

    name = "mock"

    def is_configured(self) -> bool:
        return True

    def generate(self, prompt: str, out_path: Path, size: tuple[int, int]) -> Path:
        width, height = size
        top = _color_from(prompt, 0)
        bottom = _color_from(prompt, 1)

        img = Image.new("RGB", (width, height))
        px = img.load()
        assert px is not None
        for y in range(height):
            t = y / max(height - 1, 1)
            row = (
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
            )
            for x in range(width):
                px[x, y] = row

        draw = ImageDraw.Draw(img)
        label = prompt if len(prompt) <= 40 else prompt[:37] + "..."
        try:
            font = ImageFont.load_default(size=48)
        except TypeError:  # Pillow < 10 signature
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((width - tw) / 2, (height - th) / 2),
            label,
            fill=(255, 255, 255),
            font=font,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
        return out_path
