"""Video rendering pipeline — cards + slideshow + music.

Public API:
    render_video(content, events, out_path, fmt) -> Path
    render_event_still(content, event, index, total, ...) -> Image  # instant preview
"""

from .animations import ANIMATIONS, DEFAULT_ANIMATION, AnimationPreset, get_animation
from .formats import FORMATS, LANDSCAPE, REEL, VideoFormat, get_format
from .preview import render_event_still, render_thumbnail, render_thumbnail_variants
from .themes import DEFAULT_THEME, THEMES, Theme, available_fonts, get_theme
from .video import render_event_segment, render_video

__all__ = [
    "ANIMATIONS",
    "DEFAULT_ANIMATION",
    "AnimationPreset",
    "get_animation",
    "FORMATS",
    "LANDSCAPE",
    "REEL",
    "VideoFormat",
    "get_format",
    "THEMES",
    "DEFAULT_THEME",
    "Theme",
    "get_theme",
    "render_video",
    "render_event_still",
    "render_event_segment",
    "render_thumbnail",
    "render_thumbnail_variants",
    "available_fonts",
]
