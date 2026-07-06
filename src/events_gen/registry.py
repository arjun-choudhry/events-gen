"""Catalog of cities and event types the app operates on.

Loads ``config/cities.yaml`` and ``config/event_types.yaml`` into typed models
with lookup helpers, and provides an ``add_city`` helper that appends a new city
to the YAML and creates its asset folders. Used by the pipeline and the UI so a
newly added city becomes selectable everywhere without code changes.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import City, EventType
from .settings import Settings, get_settings

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class RegistryError(Exception):
    """Raised for invalid or duplicate registry entries."""


def slugify(value: str) -> str:
    """Convert a display name to a kebab-case slug (e.g. 'São Paulo' -> 'sao-paulo')."""
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug


# ── loaders ──────────────────────────────────────────────────────────────


def _load_yaml(path: Path) -> dict[str, object]:
    if not path.exists():
        raise RegistryError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise RegistryError(f"expected a mapping at the top of {path}")
    return data


def load_cities(settings: Settings | None = None) -> list[City]:
    """Load and validate all cities from ``config/cities.yaml``."""
    settings = settings or get_settings()
    data = _load_yaml(settings.cities_file)
    raw = data.get("cities", [])
    if not isinstance(raw, list):
        raise RegistryError("'cities' must be a list in cities.yaml")
    cities = [City.model_validate(entry) for entry in raw]

    seen: set[str] = set()
    for city in cities:
        if not _SLUG_RE.match(city.slug):
            raise RegistryError(f"invalid city slug: {city.slug!r} (must be kebab-case)")
        if city.slug in seen:
            raise RegistryError(f"duplicate city slug: {city.slug!r}")
        seen.add(city.slug)
    return cities


def load_event_types(settings: Settings | None = None) -> list[EventType]:
    """Load and validate all event types from ``config/event_types.yaml``."""
    settings = settings or get_settings()
    data = _load_yaml(settings.event_types_file)
    raw = data.get("event_types", [])
    if not isinstance(raw, list):
        raise RegistryError("'event_types' must be a list in event_types.yaml")
    types = [EventType.model_validate(entry) for entry in raw]

    seen: set[str] = set()
    for et in types:
        if not _SLUG_RE.match(et.slug):
            raise RegistryError(f"invalid event-type slug: {et.slug!r} (must be kebab-case)")
        if et.slug in seen:
            raise RegistryError(f"duplicate event-type slug: {et.slug!r}")
        seen.add(et.slug)
    return types


# ── lookups ──────────────────────────────────────────────────────────────


def get_city(slug: str, settings: Settings | None = None) -> City:
    """Return the city with ``slug`` or raise ``RegistryError``."""
    for city in load_cities(settings):
        if city.slug == slug:
            return city
    raise RegistryError(f"unknown city slug: {slug!r}")


def get_event_type(slug: str, settings: Settings | None = None) -> EventType:
    """Return the event type with ``slug`` or raise ``RegistryError``."""
    for et in load_event_types(settings):
        if et.slug == slug:
            return et
    raise RegistryError(f"unknown event-type slug: {slug!r}")


# ── mutation: add a city ─────────────────────────────────────────────────


def add_city(
    *,
    name: str,
    country: str,
    country_code: str,
    timezone: str,
    latitude: float,
    longitude: float,
    slug: str | None = None,
    default_image: str | None = None,
    default_music: str | None = None,
    settings: Settings | None = None,
    create_asset_dirs: bool = True,
) -> City:
    """Add a new city to ``cities.yaml`` and (optionally) create its asset folders.

    The slug is derived from ``name`` when not given. Raises ``RegistryError``
    if the slug already exists. Returns the created :class:`City`.
    """
    settings = settings or get_settings()
    resolved_slug = slug or slugify(name)
    if not _SLUG_RE.match(resolved_slug):
        raise RegistryError(f"invalid slug derived/provided: {resolved_slug!r}")

    existing = load_cities(settings)
    if any(c.slug == resolved_slug for c in existing):
        raise RegistryError(f"city already exists: {resolved_slug!r}")

    city = City(
        slug=resolved_slug,
        name=name,
        country=country,
        country_code=country_code,
        timezone=timezone,
        latitude=latitude,
        longitude=longitude,
        default_image=default_image or f"images/{resolved_slug}/default.jpg",
        default_music=default_music,
    )

    # Append to the YAML, preserving existing content structure.
    data = _load_yaml(settings.cities_file)
    raw = data.get("cities", [])
    cities_raw = list(raw) if isinstance(raw, list) else []
    cities_raw.append(city.model_dump())
    data["cities"] = cities_raw
    with settings.cities_file.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)

    if create_asset_dirs:
        (settings.assets_dir / "images" / resolved_slug).mkdir(parents=True, exist_ok=True)

    return city
