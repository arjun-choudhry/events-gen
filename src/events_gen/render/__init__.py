"""Video rendering pipeline — cards + slideshow + music.

Public API:
    render_video(content, events, out_path, fmt) -> Path
"""

from .formats import FORMATS, LANDSCAPE, REEL, VideoFormat, get_format
from .video import render_video

__all__ = [
    "FORMATS",
    "LANDSCAPE",
    "REEL",
    "VideoFormat",
    "get_format",
    "render_video",
]
