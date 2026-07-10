"""Background job runner decoupled from Streamlit's script lifecycle.

Streamlit aborts the currently-running script whenever the user interacts with
the app (e.g. switches tabs). If a video render runs *inside* that script, the
switch kills it mid-flight and the video never finishes. To keep generation and
rendering running regardless of UI interaction, we run the work in a daemon
thread and track its state in a module-level registry the UI polls.

The worker MUST NOT touch any Streamlit API: it runs off the script thread where
there is no ScriptRunContext. It only mutates the shared :class:`JobState` (guarded
by a lock) and persists results through its own :class:`Storage`. The UI reads
:class:`JobState` on each rerun and, once the job is done, surfaces the result.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class JobPhase(StrEnum):
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class JobState:
    """Mutable state of a single background job, polled by the UI."""

    status: JobPhase = JobPhase.RUNNING
    message: str = "Starting…"
    # Whatever ``work`` returned (a draft id, a city→id map, or None). Consumed by
    # the UI's on-done callback on the main thread.
    result: Any = None
    error: str | None = None


# Job key → state. A job key is stable across reruns (e.g. "gen_tab_tokyo") so the
# poller can find its job again after any number of tab switches / reruns.
_JOBS: dict[str, JobState] = {}
_LOCK = threading.Lock()

# ``work`` receives a progress callback and returns any result the UI consumes.
WorkFn = Callable[[Callable[[str], None]], Any]


def get_job(key: str) -> JobState | None:
    """Return the current state of the job under ``key`` (or None if unknown)."""
    with _LOCK:
        return _JOBS.get(key)


def is_running(key: str) -> bool:
    """True if a job under ``key`` exists and is still running."""
    state = get_job(key)
    return state is not None and state.status == JobPhase.RUNNING


def clear_job(key: str) -> None:
    """Forget a job (called by the UI once it has consumed the result)."""
    with _LOCK:
        _JOBS.pop(key, None)


def start_job(key: str, work: WorkFn) -> bool:
    """Run ``work`` in a daemon thread under ``key``.

    ``work`` is given a progress callback (``str -> None``) and may return any
    result (stored on :attr:`JobState.result`). Returns True if a new job was
    started, or False if a job under ``key`` is already running (so a stray rerun
    can't launch a duplicate).
    """
    with _LOCK:
        existing = _JOBS.get(key)
        if existing is not None and existing.status == JobPhase.RUNNING:
            return False
        _JOBS[key] = JobState()

    def _progress(msg: str) -> None:
        with _LOCK:
            state = _JOBS.get(key)
            if state is not None:
                state.message = msg

    def _run() -> None:
        try:
            result = work(_progress)
            with _LOCK:
                state = _JOBS.get(key)
                if state is not None:
                    state.status = JobPhase.DONE
                    state.result = result
                    state.message = "Done."
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI via JobState
            logger.exception("background job %s failed", key)
            with _LOCK:
                state = _JOBS.get(key)
                if state is not None:
                    state.status = JobPhase.ERROR
                    state.error = str(exc)

    threading.Thread(target=_run, daemon=True, name=f"job-{key}").start()
    return True
