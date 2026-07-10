"""Pure helper functions for the interactive event picker (M10).

No Streamlit imports — these are testable without a running script context.
The UI layer in ``app.py`` calls these to sort, select, estimate, and detect
staleness; all state management stays in Streamlit session state.
"""

from __future__ import annotations

from events_gen.models import Event
from events_gen.render.formats import VideoFormat


def sort_candidates(events: list[Event], key: str) -> list[Event]:
    """Return ``events`` sorted by the given criterion (does not mutate input).

    Keys: ``"rank"`` (desc), ``"date"`` (asc), ``"price"`` (asc), ``"name"`` (asc).
    """
    if key == "rank":
        return sorted(events, key=lambda e: e.rank_score, reverse=True)
    if key == "date":
        return sorted(events, key=lambda e: e.start)
    if key == "price":
        return sorted(events, key=lambda e: e.price_min or 0.0)
    if key == "name":
        return sorted(events, key=lambda e: e.title.lower())
    return list(events)


def select_top_n(events: list[Event], n: int) -> set[str]:
    """Return the IDs of the first ``n`` events (already sorted by caller)."""
    return {e.id for e in events[:n]}


def estimate_duration(n_events: int, fmt: VideoFormat) -> float:
    """Estimate video duration in seconds for ``n_events`` in ``fmt``.

    The video now opens straight on the first event (no title/outro cards), so the
    duration is just one card per event.
    """
    return n_events * fmt.seconds_per_card


def is_fetch_stale(
    fetch_params: dict[str, object] | None,
    current_params: dict[str, object],
) -> bool:
    """True if the controls have changed since the last fetch (candidates are stale)."""
    if fetch_params is None:
        return False
    return fetch_params != current_params
