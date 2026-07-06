"""Streamlit operator console (M5).

The UI wires every user-facing control (R1–R8, R10) to the generation
pipeline and persists results as drafts. Run it with::

    ./scripts/run.sh          # or: streamlit run src/events_gen/ui/app.py

Pages:
- **Create**  — pick city/window/types/count + assets → generate → preview
- **Drafts**  — saved drafts: re-open, preview, delete
- **History** — publish/generation jobs (placeholder until M6)
- **Settings**— show resolved config + credential presence

Everything runs keyless by default (mock sources + template captions + Pillow
placeholder background), so the console works end-to-end with no API keys.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from events_gen import pipeline
from events_gen.models import (
    City,
    CityPreset,
    DraftStatus,
    EventType,
    Platform,
    PostDraft,
    TimeWindow,
)
from events_gen.registry import load_cities, load_event_types
from events_gen.render import FORMATS
from events_gen.settings import get_settings
from events_gen.storage import Storage


@st.cache_resource
def _storage() -> Storage:
    return Storage(get_settings().db_path)


@st.cache_data
def _cities() -> list[City]:
    return load_cities()


@st.cache_data
def _event_types() -> list[EventType]:
    return load_event_types()


def _save_upload(uploaded: object, suffix: str) -> Path | None:
    """Persist a Streamlit UploadedFile to a temp path; return it (or None)."""
    if uploaded is None:
        return None
    tmp = Path(tempfile.gettempdir()) / f"events_gen_upload_{uploaded.name}"  # type: ignore[attr-defined]
    tmp.write_bytes(uploaded.getbuffer())  # type: ignore[attr-defined]
    return tmp


# ── Create page ──────────────────────────────────────────────────────────


def page_create() -> None:
    st.header("Create a post")
    cities = _cities()
    types = _event_types()
    storage = _storage()

    if not cities:
        st.error("No cities configured. Add one via `events-gen add-city`.")
        return

    # Preset load (R10)
    city_by_slug = {c.slug: c for c in cities}
    presets = storage.list_presets()
    preset_names = {p.name: p for p in presets}
    with st.expander("Presets (R10)", expanded=False):
        col_a, col_b = st.columns([3, 1])
        chosen_preset = col_a.selectbox(
            "Load a saved preset", ["—", *preset_names.keys()], key="preset_select"
        )
        if col_b.button("Apply", disabled=chosen_preset == "—"):
            _apply_preset(preset_names[chosen_preset])
            st.rerun()

    defaults = st.session_state.get("preset_defaults", {})

    # R1: city
    city_slugs = [c.slug for c in cities]
    default_city = defaults.get("city_slug", city_slugs[0])
    city_idx = city_slugs.index(default_city) if default_city in city_slugs else 0
    city_slug = st.selectbox(
        "City (R1)", city_slugs, index=city_idx, format_func=lambda s: city_by_slug[s].name
    )

    # R2: window
    window_val = st.radio(
        "Time window (R2)",
        [TimeWindow.WEEK, TimeWindow.MONTH],
        format_func=lambda w: w.value.capitalize(),
        index=0 if defaults.get("window", "week") == "week" else 1,
        horizontal=True,
    )

    # R3: event types
    type_slugs = [t.slug for t in types]
    type_by_slug = {t.slug: t for t in types}
    selected_types = st.multiselect(
        "Event types (R3) — leave empty for all",
        type_slugs,
        default=defaults.get("event_types", []),
        format_func=lambda s: type_by_slug[s].name,
    )

    # R4: count
    count = st.slider("Number of events (R4)", 3, 15, defaults.get("event_count", 5))

    # Render format
    fmt = st.selectbox(
        "Video format",
        list(FORMATS.keys()),
        index=list(FORMATS.keys()).index(defaults.get("render_format", "reel")),
        format_func=lambda f: f"{f} ({FORMATS[f].width}×{FORMATS[f].height})",
    )

    # R5/R6: asset overrides
    col1, col2 = st.columns(2)
    image_upload = col1.file_uploader(
        "Background image (R5) — optional", type=["jpg", "jpeg", "png"]
    )
    music_upload = col2.file_uploader("Music track (R6) — optional", type=["mp3", "wav", "m4a"])

    # R8: destinations
    targets = st.multiselect(
        "Destinations (R8)",
        [Platform.YOUTUBE, Platform.INSTAGRAM],
        default=defaults.get("targets", []),
        format_func=lambda p: p.value.capitalize(),
    )

    col_gen, col_save = st.columns([1, 1])
    generate = col_gen.button("Generate", type="primary")
    with col_save.popover("Save as preset"):
        preset_name = st.text_input("Preset name")
        if st.button("Save preset", disabled=not preset_name):
            storage.save_preset(
                CityPreset(
                    name=preset_name,
                    city_slug=city_slug,
                    window=window_val,
                    event_types=selected_types,
                    event_count=count,
                    render_format=fmt,
                    targets=targets,
                )
            )
            st.success(f"Saved preset '{preset_name}'.")

    if generate:
        _run_generation(
            city_slug=city_slug,
            window=window_val,
            event_types=selected_types,
            count=count,
            render_format=fmt,
            image_upload=_save_upload(image_upload, ".jpg"),
            music_upload=_save_upload(music_upload, ".mp3"),
            targets=targets,
        )

    # Show the just-generated draft's preview inline.
    draft_id = st.session_state.get("last_draft_id")
    if draft_id:
        draft = storage.get_draft(draft_id)
        if draft:
            st.divider()
            _render_preview(draft)


def _apply_preset(preset: CityPreset) -> None:
    st.session_state["preset_defaults"] = {
        "city_slug": preset.city_slug,
        "window": preset.window.value,
        "event_types": preset.event_types,
        "event_count": preset.event_count,
        "render_format": preset.render_format,
        "targets": preset.targets,
    }


def _run_generation(**kwargs: object) -> None:
    status = st.status("Generating…", expanded=True)

    def progress(msg: str) -> None:
        status.write(msg)

    try:
        draft = pipeline.run(progress=progress, **kwargs)  # type: ignore[arg-type]
        st.session_state["last_draft_id"] = draft.id
        status.update(label="Draft ready.", state="complete")
    except pipeline.PipelineError as exc:
        status.update(label="No events found.", state="error")
        st.warning(str(exc))
    except Exception as exc:  # surface unexpected failures in the UI
        status.update(label="Generation failed.", state="error")
        st.exception(exc)


def _render_preview(draft: PostDraft) -> None:
    """R7: video player + editable caption/hashtags."""
    st.subheader("Preview (R7)")
    if draft.video_path and Path(draft.video_path).exists():
        st.video(draft.video_path)
    else:
        st.info("No rendered video on this draft.")

    content = draft.content
    if content:
        new_title = st.text_input("Title", content.title, key=f"title_{draft.id}")
        new_caption = st.text_area(
            "Caption", content.caption, key=f"caption_{draft.id}", height=140
        )
        new_tags = st.text_input("Hashtags", " ".join(content.hashtags), key=f"tags_{draft.id}")
        if st.button("Save edits", key=f"save_{draft.id}"):
            content.title = new_title
            content.caption = new_caption
            content.hashtags = new_tags.split()
            draft.content = content
            _storage().save_draft(draft)
            st.success("Caption saved.")

    st.caption(f"Draft `{draft.id}` · {len(draft.events)} events · status: {draft.status.value}")


# ── Drafts page ──────────────────────────────────────────────────────────


def page_drafts() -> None:
    st.header("Drafts")
    storage = _storage()
    drafts = storage.list_drafts()
    if not drafts:
        st.info("No drafts yet. Head to **Create** to generate one.")
        return

    for draft in drafts:
        label = f"{draft.city_slug} · {draft.window.value} · {draft.status.value}"
        title = draft.content.title if draft.content else "(no content)"
        with st.expander(f"{title}  —  {label}"):
            _render_preview(draft)
            if st.button("Delete", key=f"del_{draft.id}"):
                storage.delete_draft(draft.id)
                if st.session_state.get("last_draft_id") == draft.id:
                    st.session_state.pop("last_draft_id", None)
                st.rerun()


# ── History page ─────────────────────────────────────────────────────────


def page_history() -> None:
    st.header("History")
    storage = _storage()
    published = storage.list_drafts(status=DraftStatus.PUBLISHED.value)
    jobs = storage.list_jobs()
    if not published and not jobs:
        st.info("No publish history yet — publishing lands in M6.")
        return
    for draft in published:
        st.write(f"**{draft.city_slug}** — {draft.content.title if draft.content else ''}")
        for result in draft.results:
            icon = "✅" if result.success else "❌"
            st.write(f"  {icon} {result.platform.value}: {result.url or result.error}")


# ── Settings page ────────────────────────────────────────────────────────


def page_settings() -> None:
    st.header("Settings")
    s = get_settings()
    st.subheader("Paths")
    st.json(
        {
            "data_dir": str(s.data_dir),
            "config_dir": str(s.config_dir),
            "assets_dir": str(s.assets_dir),
            "output_dir": str(s.output_dir),
            "db_path": str(s.db_path),
        }
    )
    st.subheader("Credentials (presence only)")
    st.json(
        {
            "anthropic_api_key": bool(s.anthropic_api_key),
            "image_provider": s.image_provider,
            "ticketmaster": bool(s.ticketmaster_api_key),
            "eventbrite": bool(s.eventbrite_api_token),
            "youtube": bool(s.youtube_client_secrets_file),
            "instagram": bool(s.instagram_access_token),
        }
    )
    st.caption("Keyless-first: mock sources + template captions run with no keys set.")


PAGES = {
    "Create": page_create,
    "Drafts": page_drafts,
    "History": page_history,
    "Settings": page_settings,
}


def main() -> None:
    st.set_page_config(page_title="Events-Gen", page_icon="🎬", layout="centered")
    st.sidebar.title("🎬 Events-Gen")
    choice = st.sidebar.radio("Navigate", list(PAGES.keys()))
    st.sidebar.caption("Discover city events → generate a video → publish.")
    PAGES[choice]()


if __name__ == "__main__":
    main()
