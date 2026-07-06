"""Automation & scheduling (M7) — optional, off by default.

Two layers:

- :func:`run_schedule` — the *work*: run the pipeline for a :class:`Schedule`,
  optionally auto-publish, and record a history :class:`Job`. It's plain and
  synchronous so it can be unit-tested and triggered on demand without a running
  scheduler.
- :class:`SchedulerService` — a thin APScheduler wrapper that fires
  ``run_schedule`` on a weekly/monthly cron trigger per city. Enabled schedules
  are persisted in the ``schedules`` table (M6/M5 storage), so on ``start`` the
  service **reconstructs its jobs from storage** and thus survives restarts
  (M7.2) — we don't rely on APScheduler's own jobstore serialization.

Guardrails (M7.5): a run that finds no events is *skipped* (recorded, not
failed); any exception is caught, logged, and recorded as a failed job so one
bad run never kills the scheduler thread.
"""

from __future__ import annotations

import logging

from .models import Job, JobStatus, Schedule, ScheduleCadence
from .settings import Settings, get_settings
from .storage import Storage

logger = logging.getLogger(__name__)

# Default local time-of-day for scheduled runs.
_RUN_HOUR = 9


def run_schedule(
    schedule: Schedule,
    *,
    storage: Storage | None = None,
    settings: Settings | None = None,
) -> Job:
    """Execute one scheduled run: generate a draft, optionally publish.

    Returns the recorded history :class:`Job`. Never raises — guardrails convert
    "no events" into a skipped job and any error into a failed job.
    """
    from . import pipeline, publish

    settings = settings or get_settings()
    storage = storage or Storage(settings.db_path)

    logger.info("scheduled run for %s (cadence=%s)", schedule.city_slug, schedule.cadence.value)
    try:
        draft = pipeline.run(
            city_slug=schedule.city_slug,
            window=schedule.window,
            event_types=schedule.event_types,
            count=schedule.event_count,
            targets=schedule.targets,
            storage=storage,
            settings=settings,
        )
    except pipeline.PipelineError as exc:
        # Guardrail: no events → skip, don't fail.
        logger.info("scheduled run skipped: %s", exc)
        return storage.save_job(
            Job(
                kind="scheduled_run",
                status=JobStatus.SUCCEEDED,
                detail=f"skipped: {exc}",
            )
        )
    except Exception as exc:  # guardrail: isolate + notify via recorded job
        logger.exception("scheduled run failed for %s", schedule.city_slug)
        return storage.save_job(Job(kind="scheduled_run", status=JobStatus.FAILED, error=str(exc)))

    if not schedule.auto_publish:
        return storage.save_job(
            Job(
                kind="scheduled_run",
                draft_id=draft.id,
                status=JobStatus.SUCCEEDED,
                detail=f"draft generated (review required); {len(draft.events)} events",
            )
        )

    # Auto-publish path.
    try:
        results = publish.publish_draft(
            draft, targets=schedule.targets, storage=storage, settings=settings
        )
    except publish.PublishError as exc:
        return storage.save_job(
            Job(
                kind="scheduled_run",
                draft_id=draft.id,
                status=JobStatus.FAILED,
                error=f"publish error: {exc}",
            )
        )
    ok = all(r.success for r in results)
    detail = ", ".join(f"{r.platform.value}={'ok' if r.success else 'fail'}" for r in results)
    return storage.save_job(
        Job(
            kind="scheduled_run",
            draft_id=draft.id,
            status=JobStatus.SUCCEEDED if ok else JobStatus.FAILED,
            detail=f"auto-published: {detail}",
            error=None if ok else "one or more destinations failed",
        )
    )


def _trigger_for(schedule: Schedule, tz_name: str):  # type: ignore[no-untyped-def]
    """Build an APScheduler cron trigger for the schedule's cadence."""
    from apscheduler.triggers.cron import CronTrigger

    if schedule.cadence is ScheduleCadence.WEEKLY:
        return CronTrigger(day_of_week="mon", hour=_RUN_HOUR, minute=0, timezone=tz_name)
    return CronTrigger(day=1, hour=_RUN_HOUR, minute=0, timezone=tz_name)


class SchedulerService:
    """Runs enabled :class:`Schedule`s on cron triggers via APScheduler.

    The service is a long-lived object owned by whatever process wants
    automation (the Streamlit app, or a standalone runner). It's created stopped;
    call :meth:`start` to reconstruct jobs from storage and begin firing.
    """

    def __init__(self, *, storage: Storage | None = None, settings: Settings | None = None) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        self.settings = settings or get_settings()
        self.storage = storage or Storage(self.settings.db_path)
        self._scheduler = BackgroundScheduler()

    def start(self) -> None:
        """Reconstruct jobs from enabled schedules and start firing (idempotent)."""
        if not self._scheduler.running:
            self._scheduler.start()
        self.reload()

    def reload(self) -> None:
        """Sync APScheduler jobs to the set of enabled schedules in storage."""
        self._scheduler.remove_all_jobs()
        for schedule in self.storage.list_schedules(enabled_only=True):
            self._add_job(schedule)

    def _add_job(self, schedule: Schedule) -> None:
        from .registry import RegistryError, get_city

        try:
            tz_name = get_city(schedule.city_slug, self.settings).timezone
        except RegistryError:
            tz_name = "UTC"
        self._scheduler.add_job(
            run_schedule,
            trigger=_trigger_for(schedule, tz_name),
            args=[schedule],
            kwargs={"storage": self.storage, "settings": self.settings},
            id=schedule.id,
            replace_existing=True,
            misfire_grace_time=3600,
        )

    def job_ids(self) -> list[str]:
        """Currently-scheduled job ids (one per enabled schedule)."""
        return [job.id for job in self._scheduler.get_jobs()]

    def trigger_now(self, schedule: Schedule) -> Job:
        """Run a schedule immediately (used by the UI 'Run now' button)."""
        return run_schedule(schedule, storage=self.storage, settings=self.settings)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
