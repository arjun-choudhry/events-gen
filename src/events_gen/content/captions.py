"""Caption generation with Anthropic Claude (template fallback when no key).

Given a city and its selected events, produce a post ``title``, ``caption``, and
``hashtags``. When ``ANTHROPIC_API_KEY`` is configured we ask Claude for catchy,
on-brand copy; otherwise a deterministic template fallback keeps the pipeline
runnable with no credentials (matching the keyless-first design of M2).
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


def generate_captions(
    city: City,
    events: list[Event],
    window: str,
    *,
    settings: Settings | None = None,
) -> CaptionResult:
    """Generate captions for ``events``; falls back to a template with no API key."""
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        logger.info("no ANTHROPIC_API_KEY; using template captions")
        return _template_captions(city, events, window)

    try:
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
    except Exception:  # noqa: BLE001 - degrade to template on any LLM failure
        logger.exception("caption generation via Claude failed; using template fallback")
        return _template_captions(city, events, window)
