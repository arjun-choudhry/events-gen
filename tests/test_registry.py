"""Tests for the city / event-type registry."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from events_gen.registry import (
    RegistryError,
    add_city,
    get_city,
    get_event_type,
    load_cities,
    load_event_types,
    slugify,
)
from events_gen.settings import REPO_ROOT, Settings


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Settings with config + assets pointed at isolated temp copies.

    The real ``config/*.yaml`` are copied in so loaders see realistic data, but
    mutations (add_city) never touch the repo's files.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("cities.yaml", "event_types.yaml"):
        shutil.copy(REPO_ROOT / "config" / name, config_dir / name)
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        EG_CONFIG_DIR=str(config_dir),
        EG_ASSETS_DIR=str(tmp_path / "assets"),
        EG_DATA_DIR=str(tmp_path / "data"),
    )


# ── slugify ──


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("New York", "new-york"),
        ("São Paulo", "sao-paulo"),
        ("  Los Angeles  ", "los-angeles"),
        ("Zürich", "zurich"),
        ("Washington, D.C.", "washington-d-c"),
    ],
)
def test_slugify(value: str, expected: str) -> None:
    assert slugify(value) == expected


# ── loaders ──


def test_load_cities(settings: Settings) -> None:
    cities = load_cities(settings)
    slugs = {c.slug for c in cities}
    assert {"new-york", "london", "tokyo", "berlin", "mumbai"} <= slugs
    tokyo = next(c for c in cities if c.slug == "tokyo")
    assert tokyo.timezone == "Asia/Tokyo"
    assert tokyo.country_code == "JP"


def test_load_event_types(settings: Settings) -> None:
    types = load_event_types(settings)
    slugs = {t.slug for t in types}
    assert {"music", "sports", "arts", "food", "tech"} <= slugs
    music = next(t for t in types if t.slug == "music")
    assert "ticketmaster" in music.source_categories


def test_load_cities_rejects_duplicate_slug(settings: Settings) -> None:
    path = settings.cities_file
    data = yaml.safe_load(path.read_text())
    data["cities"].append(dict(data["cities"][0]))  # duplicate
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(RegistryError, match="duplicate city slug"):
        load_cities(settings)


def test_load_cities_rejects_bad_slug(settings: Settings) -> None:
    path = settings.cities_file
    data = yaml.safe_load(path.read_text())
    data["cities"][0]["slug"] = "Not A Slug"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(RegistryError, match="invalid city slug"):
        load_cities(settings)


# ── lookups ──


def test_get_city_and_event_type(settings: Settings) -> None:
    assert get_city("london", settings).name == "London"
    assert get_event_type("music", settings).name == "Music & Concerts"


def test_get_city_unknown_raises(settings: Settings) -> None:
    with pytest.raises(RegistryError, match="unknown city slug"):
        get_city("atlantis", settings)


# ── add_city ──


def test_add_city_appends_and_creates_dirs(settings: Settings) -> None:
    before = len(load_cities(settings))
    city = add_city(
        name="Helsinki",
        country="Finland",
        country_code="FI",
        timezone="Europe/Helsinki",
        latitude=60.1699,
        longitude=24.9384,
        settings=settings,
    )
    assert city.slug == "helsinki"
    assert city.default_image == "images/helsinki/default.jpg"

    after = load_cities(settings)
    assert len(after) == before + 1
    assert get_city("helsinki", settings).country == "Finland"
    assert (settings.assets_dir / "images" / "helsinki").is_dir()


def test_add_city_duplicate_raises(settings: Settings) -> None:
    with pytest.raises(RegistryError, match="already exists"):
        add_city(
            name="London",
            country="United Kingdom",
            country_code="GB",
            timezone="Europe/London",
            latitude=51.5,
            longitude=-0.12,
            settings=settings,
        )


def test_add_city_preserves_existing_entries(settings: Settings) -> None:
    add_city(
        name="Oslo",
        country="Norway",
        country_code="NO",
        timezone="Europe/Oslo",
        latitude=59.91,
        longitude=10.75,
        settings=settings,
    )
    # Existing cities still load and parse correctly after the write.
    slugs = {c.slug for c in load_cities(settings)}
    assert {"new-york", "tokyo", "oslo"} <= slugs
