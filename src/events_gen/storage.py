"""SQLite persistence for drafts, jobs, publish history, and schedules.

Each model is stored with a few indexed columns for querying plus a ``payload``
column holding the full pydantic JSON. This keeps the schema stable while the
models evolve, and round-trips validate through pydantic on read.

Timestamps (``created_at`` / ``updated_at``) are managed here so callers don't
have to. All times are stored as ISO-8601 UTC strings.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import CityPreset, Destination, Job, PostDraft, Schedule

_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id          TEXT PRIMARY KEY,
    city_slug   TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drafts_city   ON drafts(city_slug);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    draft_id    TEXT,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_draft  ON jobs(draft_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS schedules (
    id          TEXT PRIMARY KEY,
    city_slug   TEXT NOT NULL,
    enabled     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedules_city ON schedules(city_slug);

CREATE TABLE IF NOT EXISTS presets (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    city_slug   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_presets_city ON presets(city_slug);

CREATE TABLE IF NOT EXISTS favorites (
    city_slug   TEXT PRIMARY KEY,
    position    INTEGER NOT NULL DEFAULT 0,
    added_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS destinations (
    id          TEXT PRIMARY KEY,
    city_slug   TEXT NOT NULL,
    platform    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_destinations_city ON destinations(city_slug);
"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class Storage:
    """Thin SQLite-backed repository for the app's persistent state."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── connection plumbing ──
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── drafts ──
    def save_draft(self, draft: PostDraft) -> PostDraft:
        """Insert or update a draft, managing timestamps."""
        now = _utcnow()
        if draft.created_at is None:
            draft.created_at = now
        draft.updated_at = now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO drafts (id, city_slug, status, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    city_slug=excluded.city_slug,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (
                    draft.id,
                    draft.city_slug,
                    draft.status.value,
                    _iso(draft.created_at),
                    _iso(draft.updated_at),
                    draft.model_dump_json(),
                ),
            )
        return draft

    def get_draft(self, draft_id: str) -> PostDraft | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        return PostDraft.model_validate_json(row["payload"]) if row else None

    def list_drafts(
        self, *, city_slug: str | None = None, status: str | None = None, limit: int = 100
    ) -> list[PostDraft]:
        query = "SELECT payload FROM drafts"
        clauses: list[str] = []
        params: list[object] = []
        if city_slug is not None:
            clauses.append("city_slug = ?")
            params.append(city_slug)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [PostDraft.model_validate_json(r["payload"]) for r in rows]

    def delete_draft(self, draft_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
            return cur.rowcount > 0

    def recent_music_track_ids(self, limit: int = 5) -> list[str]:
        """Return the auto-selected music track ids from the most recent drafts.

        Used for music anti-repetition — the caller excludes these when picking a
        new auto-selected track.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM drafts ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        ids: list[str] = []
        for row in rows:
            draft = PostDraft.model_validate_json(row["payload"])
            if draft.content and draft.content.music_track_id:
                ids.append(draft.content.music_track_id)
        return ids

    # ── jobs ──
    def save_job(self, job: Job) -> Job:
        now = _utcnow()
        if job.created_at is None:
            job.created_at = now
        job.updated_at = now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, kind, draft_id, status, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind,
                    draft_id=excluded.draft_id,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (
                    job.id,
                    job.kind,
                    job.draft_id,
                    job.status.value,
                    _iso(job.created_at),
                    _iso(job.updated_at),
                    job.model_dump_json(),
                ),
            )
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return Job.model_validate_json(row["payload"]) if row else None

    def list_jobs(
        self, *, draft_id: str | None = None, status: str | None = None, limit: int = 100
    ) -> list[Job]:
        query = "SELECT payload FROM jobs"
        clauses: list[str] = []
        params: list[object] = []
        if draft_id is not None:
            clauses.append("draft_id = ?")
            params.append(draft_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [Job.model_validate_json(r["payload"]) for r in rows]

    # ── schedules ──
    def save_schedule(self, schedule: Schedule) -> Schedule:
        now = _utcnow()
        if schedule.created_at is None:
            schedule.created_at = now
        schedule.updated_at = now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO schedules (id, city_slug, enabled, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    city_slug=excluded.city_slug,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (
                    schedule.id,
                    schedule.city_slug,
                    int(schedule.enabled),
                    _iso(schedule.created_at),
                    _iso(schedule.updated_at),
                    schedule.model_dump_json(),
                ),
            )
        return schedule

    def get_schedule(self, schedule_id: str) -> Schedule | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM schedules WHERE id = ?", (schedule_id,)
            ).fetchone()
        return Schedule.model_validate_json(row["payload"]) if row else None

    def list_schedules(self, *, enabled_only: bool = False) -> list[Schedule]:
        query = "SELECT payload FROM schedules"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [Schedule.model_validate_json(r["payload"]) for r in rows]

    def delete_schedule(self, schedule_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
            return cur.rowcount > 0

    # ── city presets (R10) ──
    def save_preset(self, preset: CityPreset) -> CityPreset:
        now = _utcnow()
        if preset.created_at is None:
            preset.created_at = now
        preset.updated_at = now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO presets (id, name, city_slug, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    city_slug=excluded.city_slug,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (
                    preset.id,
                    preset.name,
                    preset.city_slug,
                    _iso(preset.created_at),
                    _iso(preset.updated_at),
                    preset.model_dump_json(),
                ),
            )
        return preset

    def get_preset(self, preset_id: str) -> CityPreset | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM presets WHERE id = ?", (preset_id,)).fetchone()
        return CityPreset.model_validate_json(row["payload"]) if row else None

    def list_presets(self, *, city_slug: str | None = None) -> list[CityPreset]:
        query = "SELECT payload FROM presets"
        params: list[object] = []
        if city_slug is not None:
            query += " WHERE city_slug = ?"
            params.append(city_slug)
        query += " ORDER BY name ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [CityPreset.model_validate_json(r["payload"]) for r in rows]

    def delete_preset(self, preset_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
            return cur.rowcount > 0

    # ── favorites (M11) ──
    def save_favorite(self, city_slug: str) -> None:
        """Add a city to favorites (idempotent — re-adding is a no-op)."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO favorites (city_slug, position, added_at)
                VALUES (?, (SELECT COALESCE(MAX(position), 0) + 1 FROM favorites), ?)
                ON CONFLICT(city_slug) DO NOTHING
                """,
                (city_slug, _iso(_utcnow())),
            )

    def remove_favorite(self, city_slug: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM favorites WHERE city_slug = ?", (city_slug,))

    def list_favorites(self) -> list[str]:
        """Return favorite city slugs in position order."""
        with self._connect() as conn:
            rows = conn.execute("SELECT city_slug FROM favorites ORDER BY position ASC").fetchall()
        return [r["city_slug"] for r in rows]

    # ── destinations (M13) ──
    def save_destination(self, dest: Destination) -> Destination:
        now = _utcnow()
        if dest.created_at is None:
            dest.created_at = now
        dest.updated_at = now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO destinations (id, city_slug, platform, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    city_slug=excluded.city_slug,
                    platform=excluded.platform,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (
                    dest.id,
                    dest.city_slug,
                    dest.platform.value,
                    _iso(dest.created_at),
                    _iso(dest.updated_at),
                    dest.model_dump_json(),
                ),
            )
        return dest

    def get_destination(self, dest_id: str) -> Destination | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM destinations WHERE id = ?", (dest_id,)
            ).fetchone()
        return Destination.model_validate_json(row["payload"]) if row else None

    def list_destinations(self, *, city_slug: str | None = None) -> list[Destination]:
        query = "SELECT payload FROM destinations"
        params: list[object] = []
        if city_slug is not None:
            query += " WHERE city_slug = ?"
            params.append(city_slug)
        query += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [Destination.model_validate_json(r["payload"]) for r in rows]

    def delete_destination(self, dest_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM destinations WHERE id = ?", (dest_id,))
            return cur.rowcount > 0
