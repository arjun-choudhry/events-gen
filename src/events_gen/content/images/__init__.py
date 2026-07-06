"""Image provider selection and background resolution.

``get_provider`` picks a provider from settings (``EG_IMAGE_PROVIDER``), falling
back to the mock provider when the configured one isn't usable — so the pipeline
always yields an image. ``resolve_background`` implements the user-override rule
from the requirements (R5): use an uploaded image if given, else a city default
asset if present, else generate one.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from ...models import City
from ...settings import Settings, get_settings
from .ai_provider import AIImageProvider
from .base import ImageProvider
from .mock_provider import MockProvider

logger = logging.getLogger(__name__)

__all__ = ["ImageProvider", "MockProvider", "AIImageProvider", "get_provider", "resolve_background"]


def get_provider(settings: Settings | None = None) -> ImageProvider:
    """Return the configured image provider, falling back to mock if unusable."""
    settings = settings or get_settings()
    if settings.image_provider == "ai":
        ai = AIImageProvider(settings=settings)
        if ai.is_configured():
            return ai
        logger.info("EG_IMAGE_PROVIDER=ai but no key configured; using mock provider")
    return MockProvider()


def _prepare_upload(upload_path: Path, out_path: Path, size: tuple[int, int]) -> Path:
    """Validate + resize a user-provided image to the target size (cover-fit)."""
    with Image.open(upload_path) as img:
        img = img.convert("RGB")
        target_w, target_h = size
        # Cover-fit: scale to fill, then center-crop.
        scale = max(target_w / img.width, target_h / img.height)
        resized = img.resize((round(img.width * scale), round(img.height * scale)))
        left = (resized.width - target_w) // 2
        top = (resized.height - target_h) // 2
        cropped = resized.crop((left, top, left + target_w, top + target_h))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(out_path)
    return out_path


def resolve_background(
    city: City,
    out_path: Path,
    size: tuple[int, int],
    *,
    upload_path: Path | None = None,
    settings: Settings | None = None,
) -> Path:
    """Resolve the background image for a post following the R5 override rule.

    Priority: user upload → city default asset → generated image.
    Always returns a path to an image sized to ``size``.
    """
    settings = settings or get_settings()

    if upload_path is not None:
        if not upload_path.exists():
            raise FileNotFoundError(f"uploaded image not found: {upload_path}")
        logger.info("using uploaded background %s", upload_path)
        return _prepare_upload(upload_path, out_path, size)

    if city.default_image:
        asset = settings.assets_dir / city.default_image
        if asset.exists():
            logger.info("using city default background %s", asset)
            return _prepare_upload(asset, out_path, size)

    provider = get_provider(settings)
    prompt = f"{city.name}, {city.country} skyline, vibrant, cinematic"
    try:
        return provider.generate(prompt, out_path, size)
    except NotImplementedError:
        logger.info("provider %s not implemented; using mock provider", provider.name)
        return MockProvider().generate(prompt, out_path, size)
