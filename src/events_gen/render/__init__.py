"""Video rendering pipeline — cards + slideshow + music.

Public API:
    render_video(content, events, out_path, fmt) -> Path
"""

from .animations import ANIMATIONS, DEFAULT_ANIMATION, AnimationPreset, get_animation
from .formats import FORMATS, LANDSCAPE, REEL, VideoFormat, get_format
from .themes import DEFAULT_THEME, THEMES, Theme, get_theme
from .video import render_video

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
]
