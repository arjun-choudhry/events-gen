"""Tests for the background job runner that decouples work from Streamlit reruns."""

from __future__ import annotations

import threading
import time

from events_gen.ui import jobs


def _wait_until(pred, timeout: float = 2.0) -> bool:
    """Poll ``pred`` until true or timeout (jobs run in a daemon thread)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return False


class TestBackgroundJobs:
    def test_job_runs_and_returns_result(self) -> None:
        key = "test_ok"
        jobs.clear_job(key)
        started = jobs.start_job(key, lambda progress: "draft-123")
        assert started is True
        assert _wait_until(lambda: not jobs.is_running(key))
        state = jobs.get_job(key)
        assert state is not None
        assert state.status == jobs.JobPhase.DONE
        assert state.result == "draft-123"
        jobs.clear_job(key)

    def test_progress_updates_message(self) -> None:
        key = "test_progress"
        jobs.clear_job(key)
        release = threading.Event()

        def work(progress):
            progress("halfway")
            release.wait(1.0)
            return "done"

        jobs.start_job(key, work)
        assert _wait_until(lambda: (s := jobs.get_job(key)) and s.message == "halfway")
        release.set()
        assert _wait_until(lambda: not jobs.is_running(key))
        jobs.clear_job(key)

    def test_error_is_captured(self) -> None:
        key = "test_err"
        jobs.clear_job(key)

        def work(progress):
            raise ValueError("boom")

        jobs.start_job(key, work)
        assert _wait_until(lambda: not jobs.is_running(key))
        state = jobs.get_job(key)
        assert state is not None
        assert state.status == jobs.JobPhase.ERROR
        assert "boom" in (state.error or "")
        jobs.clear_job(key)

    def test_duplicate_start_is_rejected_while_running(self) -> None:
        key = "test_dup"
        jobs.clear_job(key)
        release = threading.Event()
        jobs.start_job(key, lambda progress: release.wait(1.0))
        assert _wait_until(lambda: jobs.is_running(key))
        # A second start while the first is running must be a no-op.
        assert jobs.start_job(key, lambda progress: "second") is False
        release.set()
        assert _wait_until(lambda: not jobs.is_running(key))
        jobs.clear_job(key)

    def test_clear_forgets_the_job(self) -> None:
        key = "test_clear"
        jobs.start_job(key, lambda progress: "x")
        assert _wait_until(lambda: not jobs.is_running(key))
        jobs.clear_job(key)
        assert jobs.get_job(key) is None
