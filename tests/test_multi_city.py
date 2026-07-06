"""Tests for M11: geocoding, favorites, and multi-city roundup."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from events_gen import pipeline
from events_gen.settings import Settings
from events_gen.storage import Storage
from events_gen.ui.geocoding import geocode_city

CITIES_YAML = {
    "cities": [
        {
            "slug": "tokyo",
            "name": "Tokyo",
            "country": "Japan",
            "country_code": "JP",
            "timezone": "Asia/Tokyo",
            "latitude": 35.68,
            "longitude": 139.65,
        },
        {
            "slug": "london",
            "name": "London",
            "country": "United Kingdom",
            "country_code": "GB",
            "timezone": "Europe/London",
            "latitude": 51.50,
            "longitude": -0.12,
        },
    ]
}
EVENT_TYPES_YAML = {"event_types": [{"slug": "music", "name": "Music"}]}


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cities.yaml").write_text(yaml.safe_dump(CITIES_YAML))
    (config_dir / "event_types.yaml").write_text(yaml.safe_dump(EVENT_TYPES_YAML))
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        EG_DATA_DIR=str(tmp_path / "data"),
        EG_CONFIG_DIR=str(config_dir),
        EG_ASSETS_DIR=str(tmp_path / "assets"),
    )


# ── Geocoding ──


class TestGeocode:
    def test_returns_city_for_known_name(self) -> None:
        city = geocode_city("Tokyo")
        assert city is not None
        assert city.country_code == "JP"
        assert city.timezone == "Asia/Tokyo"
        assert abs(city.latitude - 35.68) < 1.0

    def test_returns_none_for_garbage(self) -> None:
        assert geocode_city("xyznonexistent99999") is None

    def test_slug_is_kebab_case(self) -> None:
        city = geocode_city("New York")
        assert city is not None
        assert " " not in city.slug
        assert city.slug.islower()


# ── Favorites storage ──


class TestFavorites:
    def test_add_and_list(self, tmp_path: Path) -> None:
        storage = Storage(tmp_path / "db.sqlite")
        storage.save_favorite("tokyo")
        storage.save_favorite("london")
        assert storage.list_favorites() == ["tokyo", "london"]

    def test_add_is_idempotent(self, tmp_path: Path) -> None:
        storage = Storage(tmp_path / "db.sqlite")
        storage.save_favorite("tokyo")
        storage.save_favorite("tokyo")
        assert storage.list_favorites() == ["tokyo"]

    def test_remove(self, tmp_path: Path) -> None:
        storage = Storage(tmp_path / "db.sqlite")
        storage.save_favorite("tokyo")
        storage.save_favorite("london")
        storage.remove_favorite("tokyo")
        assert storage.list_favorites() == ["london"]

    def test_empty_initially(self, tmp_path: Path) -> None:
        storage = Storage(tmp_path / "db.sqlite")
        assert storage.list_favorites() == []


# ── Roundup pipeline ──


class TestRunRoundup:
    def test_produces_combined_draft(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        draft = pipeline.run_roundup(
            city_slugs=["tokyo", "london"],
            events_per_city=1,
            storage=storage,
            settings=settings,
        )
        assert draft.video_path is not None
        assert Path(draft.video_path).exists()
        assert draft.content is not None
        assert "Tokyo" in draft.content.title or "London" in draft.content.title
        assert len(draft.events) >= 1

    def test_empty_cities_raises(self, settings: Settings) -> None:
        with pytest.raises(pipeline.PipelineError):
            pipeline.run_roundup(
                city_slugs=[],
                storage=Storage(settings.db_path),
                settings=settings,
            )
