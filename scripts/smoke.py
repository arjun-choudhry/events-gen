#!/usr/bin/env python
"""M0 smoke check: exercise settings + models + SQLite storage end-to-end.

Run with:  python scripts/smoke.py
Creates a throwaway draft in a temp DB (does not touch your real data dir),
round-trips it through storage, and prints the result. Exits non-zero on failure.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from events_gen.models import DraftStatus, PostDraft, TimeWindow
from events_gen.settings import get_settings
from events_gen.storage import Storage


def main() -> int:
    settings = get_settings()
    print(f"config dir : {settings.config_dir}")
    print(f"cities file: {settings.cities_file}  (exists={settings.cities_file.exists()})")
    print(f"types file : {settings.event_types_file}  (exists={settings.event_types_file.exists()})")
    print(f"image provider: {settings.image_provider}")

    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp) / "smoke.db")
        draft = storage.save_draft(
            PostDraft(
                city_slug="london",
                window=TimeWindow.WEEK,
                event_types=["music", "arts"],
                event_count=5,
            )
        )
        print(f"\ncreated draft {draft.id} (status={draft.status})")

        fetched = storage.get_draft(draft.id)
        assert fetched is not None, "draft not found after save"

        fetched.status = DraftStatus.READY
        storage.save_draft(fetched)

        reread = storage.get_draft(draft.id)
        assert reread is not None and reread.status is DraftStatus.READY, "update did not persist"
        print(f"updated draft status -> {reread.status}")
        print(f"drafts in db: {len(storage.list_drafts())}")

    print("\nM0 smoke check passed ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
