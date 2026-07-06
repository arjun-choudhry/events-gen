"""Tests for automation & scheduling (M7)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from events_gen.models import JobStatus, Platform, Schedule, ScheduleCadence, TimeWindow
from events_gen.scheduler import SchedulerService, _trigger_for, run_schedule
from events_gen.settings import Settings
from events_gen.storage import Storage

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
        }
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


def _schedule(**overrides: object) -> Schedule:
    base: dict[str, object] = {
        "city_slug": "tokyo",
        "cadence": ScheduleCadence.WEEKLY,
        "window": TimeWindow.WEEK,
        "event_count": 3,
    }
    base.update(overrides)
    return Schedule(**base)  # type: ignore[arg-type]


class TestRunSchedule:
    def test_generate_only_draft(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        job = run_schedule(_schedule(auto_publish=False), storage=storage, settings=settings)
        assert job.kind == "scheduled_run"
        assert job.status is JobStatus.SUCCEEDED
        assert job.draft_id is not None
        # A draft exists but nothing was published.
        draft = storage.get_draft(job.draft_id)
        assert draft is not None
        assert not draft.results

    def test_auto_publish_records_result(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        job = run_schedule(
            _schedule(auto_publish=True, targets=[Platform.YOUTUBE]),
            storage=storage,
            settings=settings,
        )
        # Scheduler publishes for real (no dry-run); YouTube is unconfigured here,
        # so the publish is isolated to a failed result and the job is FAILED —
        # but a draft was still generated and the failure is recorded, not raised.
        assert job.status is JobStatus.FAILED
        assert "auto-published" in (job.detail or "")
        assert job.draft_id is not None
        draft = storage.get_draft(job.draft_id)
        assert draft is not None
        assert draft.results and draft.results[0].success is False

    def test_no_events_is_skipped_not_failed(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        # count=0 → aggregator returns nothing → pipeline raises → guardrail skips.
        job = run_schedule(_schedule(event_count=0), storage=storage, settings=settings)
        assert job.status is JobStatus.SUCCEEDED
        assert "skipped" in (job.detail or "")
        assert job.draft_id is None

    def test_unknown_city_recorded_as_failed(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        job = run_schedule(_schedule(city_slug="atlantis"), storage=storage, settings=settings)
        assert job.status is JobStatus.FAILED
        assert job.error

    def test_job_persisted_and_listable(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        run_schedule(_schedule(), storage=storage, settings=settings)
        jobs = storage.list_jobs()
        assert any(j.kind == "scheduled_run" for j in jobs)


class TestTriggers:
    def test_weekly_trigger(self) -> None:
        trig = _trigger_for(_schedule(cadence=ScheduleCadence.WEEKLY), "Asia/Tokyo")
        assert "mon" in str(trig)

    def test_monthly_trigger(self) -> None:
        trig = _trigger_for(_schedule(cadence=ScheduleCadence.MONTHLY), "Asia/Tokyo")
        # Monthly fires on day 1
        assert "day='1'" in str(trig) or "day=1" in str(trig)


class TestSchedulerService:
    def test_reload_reconstructs_from_storage(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        s1 = storage.save_schedule(_schedule(enabled=True))
        storage.save_schedule(_schedule(enabled=False))  # disabled → not scheduled

        svc = SchedulerService(storage=storage, settings=settings)
        svc.reload()
        try:
            assert svc.job_ids() == [s1.id]
        finally:
            svc.shutdown()

    def test_survives_restart_via_storage(self, settings: Settings) -> None:
        # A fresh service (new "process") rebuilds jobs from the same DB.
        storage = Storage(settings.db_path)
        s1 = storage.save_schedule(_schedule(enabled=True))

        svc = SchedulerService(storage=Storage(settings.db_path), settings=settings)
        svc.reload()
        try:
            assert s1.id in svc.job_ids()
        finally:
            svc.shutdown()

    def test_trigger_now(self, settings: Settings) -> None:
        storage = Storage(settings.db_path)
        svc = SchedulerService(storage=storage, settings=settings)
        try:
            job = svc.trigger_now(_schedule(auto_publish=False))
            assert job.status is JobStatus.SUCCEEDED
        finally:
            svc.shutdown()
