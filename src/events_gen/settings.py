"""Application configuration.

Loads settings from environment variables (and a local ``.env`` file) with
sensible defaults so the app runs end-to-end in development without any paid
API keys. Missing credentials degrade gracefully: image generation falls back
to the mock provider and event sources without keys are simply skipped.

The ``config/`` directory (YAML data files) is located relative to the repo
root, discovered by walking up from this file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_root() -> Path:
    """Return the repository root (the dir containing ``config/`` and ``pyproject.toml``)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    # Fallback: three levels up (src/events_gen/settings.py -> repo root)
    return here.parents[2]


REPO_ROOT = _repo_root()


class Settings(BaseSettings):
    """Typed application settings, populated from env / ``.env``."""

    model_config = SettingsConfigDict(
        # Absolute path so ``.env`` loads regardless of the working directory the
        # app is launched from (Streamlit, CLI, tests). A relative ".env" would
        # only be found when the cwd happens to be the repo root.
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── General ──
    data_dir: Path = Field(default=REPO_ROOT / "data", alias="EG_DATA_DIR")
    config_dir: Path = Field(default=REPO_ROOT / "config", alias="EG_CONFIG_DIR")
    assets_dir: Path = Field(default=REPO_ROOT / "assets", alias="EG_ASSETS_DIR")
    log_level: str = Field(default="INFO", alias="EG_LOG_LEVEL")

    # ── LLM (captions) ──
    # Provider selection: "auto" (default) uses whichever key is present —
    # Gemini first (free), then Anthropic; falls back to a template with neither.
    caption_provider: str = Field(default="auto", alias="EG_CAPTION_PROVIDER")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    claude_model: str = Field(default="claude-sonnet-5", alias="EG_CLAUDE_MODEL")
    # Google Gemini — free API key from aistudio.google.com (no credit card).
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="EG_GEMINI_MODEL")

    # ── Image generation ──
    image_provider: str = Field(default="mock", alias="EG_IMAGE_PROVIDER")
    image_api_key: str | None = Field(default=None, alias="EG_IMAGE_API_KEY")
    # Unsplash — free API key from https://unsplash.com/developers (no card).
    # Used for per-event venue/place backgrounds ("smart backgrounds").
    unsplash_access_key: str | None = Field(default=None, alias="UNSPLASH_ACCESS_KEY")

    # ── Render quality ──
    render_crf: int = Field(default=18, alias="EG_RENDER_CRF")

    # ── Music (auto-selection) ──
    # Jamendo — free client id from https://devportal.jamendo.com (no card).
    # Auto-picks popularity-ranked, royalty-free INSTRUMENTAL tracks. NOTE: this
    # is the legal analog to "top charts" — Billboard/commercial audio is not used
    # (it would trigger YouTube/Instagram copyright takedowns).
    jamendo_client_id: str | None = Field(default=None, alias="JAMENDO_CLIENT_ID")
    # Avoid reusing tracks from the last N drafts (anti-repetition window).
    music_history_size: int = Field(default=5, alias="EG_MUSIC_HISTORY_SIZE")

    # ── Event sources ──
    ticketmaster_api_key: str | None = Field(default=None, alias="TICKETMASTER_API_KEY")
    eventbrite_api_token: str | None = Field(default=None, alias="EVENTBRITE_API_TOKEN")
    predicthq_api_token: str | None = Field(default=None, alias="PREDICTHQ_API_TOKEN")
    seatgeek_client_id: str | None = Field(default=None, alias="SEATGEEK_CLIENT_ID")
    seatgeek_client_secret: str | None = Field(default=None, alias="SEATGEEK_CLIENT_SECRET")
    meetup_api_key: str | None = Field(default=None, alias="MEETUP_API_KEY")

    # ── YouTube ──
    youtube_client_secrets_file: Path | None = Field(
        default=None, alias="YOUTUBE_CLIENT_SECRETS_FILE"
    )
    youtube_token_file: Path | None = Field(default=None, alias="YOUTUBE_TOKEN_FILE")
    youtube_privacy: str = Field(default="unlisted", alias="EG_YOUTUBE_PRIVACY")

    # ── Instagram ──
    instagram_access_token: str | None = Field(default=None, alias="INSTAGRAM_ACCESS_TOKEN")
    instagram_business_account_id: str | None = Field(
        default=None, alias="INSTAGRAM_BUSINESS_ACCOUNT_ID"
    )

    # ── Video hosting ──
    public_video_base_url: str | None = Field(default=None, alias="EG_PUBLIC_VIDEO_BASE_URL")

    # ── Derived paths (not from env) ──
    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "events_gen.db"

    @property
    def cities_file(self) -> Path:
        return self.config_dir / "cities.yaml"

    @property
    def event_types_file(self) -> Path:
        return self.config_dir / "event_types.yaml"

    def ensure_dirs(self) -> None:
        """Create the runtime directories if they don't already exist."""
        for path in (self.data_dir, self.cache_dir, self.output_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
