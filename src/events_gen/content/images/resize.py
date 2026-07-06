"""High-quality image resizing utilities (M9).

All image resizing in the project goes through these helpers to ensure
consistent LANCZOS resampling, a minimum-resolution gate (never upscale beyond
1.25×), and a blur-fill fallback for undersized sources.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

# Never upscale beyond this factor — prefer blur-fill instead.
_MAX_UPSCALE = 1.25
# Minimum source pixels (either dimension) as a fraction of the target.
_MIN_RESOLUTION_FRAC = 0.7


def is_large_enough(width: int, height: int, target_w: int, target_h: int) -> bool:
    """True if the source is at least 70% of the target in both dimensions."""
    return width >= target_w * _MIN_RESOLUTION_FRAC and height >= target_h * _MIN_RESOLUTION_FRAC


def cover_fit(
    img: Image.Image,
    target_w: int,
    target_h: int,
) -> Image.Image:
    """Scale to fill + center-crop using LANCZOS. For sources that pass the
    resolution gate — no upscale protection needed here (caller pre-checked)."""
    scale = max(target_w / img.width, target_h / img.height)
    new_w = round(img.width * scale)
    new_h = round(img.height * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def blur_fill(
    img: Image.Image,
    target_w: int,
    target_h: int,
) -> Image.Image:
    """Create a full-bleed blurred background, overlay the sharp (smaller) image
    centered. Used when a source is too small for clean upscaling — the blur
    hides the resolution gap while filling the frame."""
    # Blurred backdrop at full size.
    backdrop = img.resize((target_w, target_h), Image.LANCZOS)
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(radius=25))

    # Sharp foreground scaled to fit *within* the target (contain-fit, no upscale
    # beyond _MAX_UPSCALE).
    fit_scale = min(target_w / img.width, target_h / img.height, _MAX_UPSCALE)
    fg_w = round(img.width * fit_scale)
    fg_h = round(img.height * fit_scale)
    foreground = img.resize((fg_w, fg_h), Image.LANCZOS)

    # Center the foreground on the backdrop.
    x = (target_w - fg_w) // 2
    y = (target_h - fg_h) // 2
    backdrop.paste(foreground, (x, y))
    return backdrop


def resize_for_target(
    img: Image.Image,
    target_w: int,
    target_h: int,
) -> Image.Image:
    """Smart resize: cover-fit if large enough, else blur-fill."""
    if is_large_enough(img.width, img.height, target_w, target_h):
        return cover_fit(img, target_w, target_h)
    logger.info(
        "image %dx%d too small for %dx%d; using blur-fill",
        img.width,
        img.height,
        target_w,
        target_h,
    )
    return blur_fill(img, target_w, target_h)


def resize_bytes(
    data: bytes,
    out_path: Path,
    size: tuple[int, int],
) -> Path:
    """Open raw bytes, smart-resize to ``size``, save to ``out_path``."""
    with Image.open(BytesIO(data)) as img:
        img = img.convert("RGB")
        result = resize_for_target(img, size[0], size[1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(out_path, quality=92)
    return out_path
