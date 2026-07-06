"""Tests for settings loading and derived paths."""

from __future__ import annotations

from pathlib import Path

from events_gen.settings import REPO_ROOT, Settings


def test_defaults_do_not_require_keys() -> None:
    # Constructing with no env should succeed; credentials default to None.
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.image_provider == "mock"
    assert s.anthropic_api_key is None
    assert s.ticketmaster_api_key is None


def test_derived_paths_under_data_dir(tmp_path: Path) -> None:
    s = Settings(_env_file=None, EG_DATA_DIR=str(tmp_path))  # type: ignore[call-arg]
    assert s.cache_dir == tmp_path / "cache"
    assert s.output_dir == tmp_path / "output"
    assert s.db_path == tmp_path / "events_gen.db"


def test_config_files_resolve_to_repo() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.cities_file == REPO_ROOT / "config" / "cities.yaml"
    assert s.event_types_file == REPO_ROOT / "config" / "event_types.yaml"
    assert s.cities_file.exists()
    assert s.event_types_file.exists()


def test_ensure_dirs_creates(tmp_path: Path) -> None:
    s = Settings(_env_file=None, EG_DATA_DIR=str(tmp_path / "d"))  # type: ignore[call-arg]
    s.ensure_dirs()
    assert s.cache_dir.exists()
    assert s.output_dir.exists()
