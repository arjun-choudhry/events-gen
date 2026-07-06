"""Time-window computation for event discovery.

Given a :class:`~events_gen.models.TimeWindow` and a city timezone, compute the
``[start, end)`` datetime range (timezone-aware, UTC) that event sources query
and the aggregator filters against.

- ``WEEK``  → from *now* through the end of the current ISO week (Sun 23:59:59).
- ``MONTH`` → from *now* through the end of the current calendar month.
- ``CUSTOM``→ caller supplies explicit ``start`` / ``end``.

Anchoring to "now" (not the start of the period) means we never surface events
that have already happened earlier this week/month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import TimeWindow


@dataclass(frozen=True)
class DateRange:
    """A timezone-aware ``[start, end)`` range, normalized to UTC."""

    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        """True if ``moment`` falls in ``[start, end)`` (naive treated as UTC)."""
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return self.start <= moment < self.end


def _end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=0)


def _last_day_of_month(dt: datetime) -> int:
    if dt.month == 12:
        nxt = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        nxt = dt.replace(month=dt.month + 1, day=1)
    return (nxt - timedelta(days=1)).day


def compute_window(
    window: TimeWindow,
    tz_name: str,
    *,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> DateRange:
    """Compute the discovery :class:`DateRange` for ``window`` in ``tz_name``.

    ``now`` is injectable for deterministic tests. For ``CUSTOM`` both ``start``
    and ``end`` are required (interpreted in the city timezone if naive).
    """
    tz = ZoneInfo(tz_name)

    if window is TimeWindow.CUSTOM:
        if start is None or end is None:
            raise ValueError("CUSTOM window requires both start and end")
        start_local = start if start.tzinfo else start.replace(tzinfo=tz)
        end_local = end if end.tzinfo else end.replace(tzinfo=tz)
        if end_local <= start_local:
            raise ValueError("CUSTOM window end must be after start")
        return DateRange(
            start=start_local.astimezone(UTC),
            end=end_local.astimezone(UTC),
        )

    # Anchor to "now" in the city's local time.
    local_now = now.astimezone(tz) if now else datetime.now(tz)

    if window is TimeWindow.WEEK:
        # ISO weekday: Mon=1 .. Sun=7 → days remaining until end of Sunday.
        days_until_sunday = 7 - local_now.isoweekday()
        end_local = _end_of_day(local_now + timedelta(days=days_until_sunday))
    elif window is TimeWindow.MONTH:
        end_local = _end_of_day(local_now.replace(day=_last_day_of_month(local_now)))
    else:  # pragma: no cover - exhaustive
        raise ValueError(f"unsupported window: {window!r}")

    return DateRange(
        start=local_now.astimezone(UTC),
        end=end_local.astimezone(UTC),
    )
