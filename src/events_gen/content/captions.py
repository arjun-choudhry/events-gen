"""Caption generation via a pluggable LLM (template fallback when no key).

Given a city and its selected events, produce a post ``title``, ``caption``, and
``hashtags``. Two LLM providers are supported, both with structured output:

- **Gemini** (``GEMINI_API_KEY``) — free tier, no credit card; the default when
  its key is present.
- **Anthropic Claude** (``ANTHROPIC_API_KEY``) — paid.

``EG_CAPTION_PROVIDER`` selects one explicitly (``gemini`` / ``anthropic``);
``auto`` (default) picks whichever key is configured, preferring the free Gemini.
With no key — or on any LLM error — a deterministic template fallback keeps the
pipeline runnable (matching the keyless-first design of M2).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from ..models import City, Event
from ..settings import Settings, get_settings

logger = logging.getLogger(__name__)


class CaptionResult(BaseModel):
    """Structured caption copy for a post."""

    title: str = Field(description="Short, punchy post title (max ~60 chars)")
    caption: str = Field(description="Engaging caption for the post body")
    hashtags: list[str] = Field(description="Relevant hashtags, each starting with #")


def _window_label(window: str) -> str:
    return {"week": "this week", "month": "this month"}.get(window, window)


def _template_captions(city: City, events: list[Event], window: str) -> CaptionResult:
    """Deterministic fallback copy used when no LLM key is configured."""
    when = _window_label(window)
    title = f"{len(events)} things to do in {city.name} {when}"
    lines = [f"🎉 Your guide to {city.name} {when}:", ""]
    for e in events:
        day = e.start.strftime("%a %d %b")
        venue = f" @ {e.venue}" if e.venue else ""
        lines.append(f"• {e.title} — {day}{venue}")
    lines.append("")
    lines.append(f"Save this and see you around {city.name}! 📍")
    caption = "\n".join(lines)

    tags = ["#events", f"#{city.slug.replace('-', '')}", f"#{city.name.replace(' ', '')}"]
    seen_types = {e.event_type for e in events if e.event_type}
    tags.extend(f"#{t}" for t in sorted(seen_types))
    tags.append("#thingstodo")
    return CaptionResult(title=title, caption=caption, hashtags=tags)


def _build_prompt(city: City, events: list[Event], window: str) -> str:
    when = _window_label(window)
    lines = [
        f"You are writing a social media post promoting upcoming events in {city.name}, "
        f"{city.country} for {when}.",
        "",
        "Events:",
    ]
    for e in events:
        day = e.start.strftime("%A %d %B, %H:%M")
        venue = f" at {e.venue}" if e.venue else ""
        lines.append(f"- {e.title} ({day}{venue})")
    lines.extend(
        [
            "",
            "Write a catchy, upbeat post that makes people want to attend. Keep the caption "
            "concise (under 500 characters) and include relevant, popular hashtags for the "
            "city and event types. Do not invent events beyond those listed.",
        ]
    )
    return "\n".join(lines)


def _select_provider(settings: Settings) -> str:
    """Resolve the effective caption provider from config + available keys."""
    choice = (settings.caption_provider or "auto").lower()
    if choice == "gemini":
        return "gemini" if settings.gemini_api_key else "template"
    if choice == "anthropic":
        return "anthropic" if settings.anthropic_api_key else "template"
    # auto: prefer the free provider, then paid, then template.
    if settings.gemini_api_key:
        return "gemini"
    if settings.anthropic_api_key:
        return "anthropic"
    return "template"


def _gemini_captions(
    city: City, events: list[Event], window: str, settings: Settings
) -> CaptionResult:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=_build_prompt(city, events, window),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CaptionResult,
        ),
    )
    result = response.parsed
    if not isinstance(result, CaptionResult):
        raise ValueError("no parsed output from Gemini")
    return result


def _anthropic_captions(
    city: City, events: list[Event], window: str, settings: Settings
) -> CaptionResult:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.parse(
        model=settings.claude_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": _build_prompt(city, events, window)}],
        output_format=CaptionResult,
    )
    result = response.parsed_output
    if result is None:
        raise ValueError("no parsed output from Claude")
    return result


def generate_captions(
    city: City,
    events: list[Event],
    window: str,
    *,
    settings: Settings | None = None,
) -> CaptionResult:
    """Generate captions for ``events``; falls back to a template with no API key."""
    settings = settings or get_settings()
    provider = _select_provider(settings)
    if provider == "template":
        logger.info("no caption LLM key configured; using template captions")
        return _template_captions(city, events, window)

    try:
        if provider == "gemini":
            return _gemini_captions(city, events, window, settings)
        return _anthropic_captions(city, events, window, settings)
    except Exception:  # noqa: BLE001 - degrade to template on any LLM failure
        logger.exception("caption generation via %s failed; using template fallback", provider)
        return _template_captions(city, events, window)
