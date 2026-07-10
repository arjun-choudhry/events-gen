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
from collections.abc import Callable
from pathlib import Path
from typing import Any

import streamlit as st

from events_gen import pipeline
from events_gen.models import (
    City,
    CityPreset,
    DraftStatus,
    Event,
    EventType,
    FontStyle,
    Platform,
    PostContent,
    PostDraft,
    Schedule,
    ScheduleCadence,
    TimeWindow,
)
from events_gen.registry import load_cities, load_event_types
from events_gen.render import FORMATS
from events_gen.settings import get_settings
from events_gen.storage import Storage
from events_gen.ui import jobs


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


def _bg_storage() -> Storage:
    """A fresh Storage for background threads (SQLite connections aren't shareable)."""
    return Storage(get_settings().db_path)


# How often the UI re-checks a running background job (seconds).
_POLL_INTERVAL = 1.0


def _poll_job(key: str, *, on_done: Callable[[Any], None]) -> bool:
    """Render a live status box for background job ``key`` and drive it to completion.

    Returns True if a job exists (running or just-finished) and was handled here —
    the caller should stop rendering its "start" controls in that case. The status
    box auto-refreshes via an ``st.fragment(run_every=...)`` so the job keeps
    running and updating even if the user switches tabs (the whole point of moving
    work off the script thread). On completion ``on_done(result)`` runs on the main
    thread, the job is cleared, and the page reruns to show the result.
    """
    state = jobs.get_job(key)
    if state is None:
        return False

    @st.fragment(run_every=_POLL_INTERVAL if state.status == jobs.JobPhase.RUNNING else None)
    def _box() -> None:
        cur = jobs.get_job(key)
        if cur is None:
            return
        if cur.status == jobs.JobPhase.RUNNING:
            st.info(f"⏳ {cur.message}  \n_You can switch tabs — this keeps running._")
            return
        if cur.status == jobs.JobPhase.ERROR:
            st.error(f"Generation failed: {cur.error}")
            jobs.clear_job(key)
            return
        # DONE — hand the result to the caller on the main thread, then refresh.
        result = cur.result
        jobs.clear_job(key)
        on_done(result)
        st.rerun(scope="app")

    _box()
    return True


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

    # R1: city — multi-select with type-to-search, favorites, and add-city.
    def _city_label(slug: str) -> str:
        c = city_by_slug[slug]
        return f"{c.name}, {c.country}"

    city_slugs = [c.slug for c in cities]

    # Favorites quick-select
    favorites = storage.list_favorites()
    if favorites:
        valid_favs = [f for f in favorites if f in city_slugs]
        if valid_favs:
            st.caption("⭐ Favorites")
            fav_cols = st.columns(min(len(valid_favs), 6))
            for col, slug in zip(fav_cols, valid_favs[:6], strict=False):
                col.button(
                    _city_label(slug),
                    key=f"fav_{slug}",
                    use_container_width=True,
                    on_click=lambda s=slug: st.session_state.update({"m11_city_selection": [s]}),
                )

    # Multi-city select
    default_selection = st.session_state.get("m11_city_selection") or defaults.get(
        "city_slug", [city_slugs[0]] if city_slugs else []
    )
    if isinstance(default_selection, str):
        default_selection = [default_selection]
    default_selection = [s for s in default_selection if s in city_slugs]

    selected_cities: list[str] = st.multiselect(
        "Cities (R1) — select one or more",
        city_slugs,
        default=default_selection or [city_slugs[0]],
        format_func=_city_label,
        placeholder="Type to search a city…",
    )
    city_slug = selected_cities[0] if selected_cities else city_slugs[0]

    # Add city + manage favorites
    with st.expander("Add a city / Manage favorites", expanded=False):
        add_col, fav_col = st.columns(2)
        with add_col:
            new_city_name = st.text_input("Type any city name to add it", key="m11_add_city")
            if st.button("Add city", disabled=not new_city_name):
                from events_gen.ui.geocoding import geocode_city as _geocode

                resolved = _geocode(new_city_name)
                if resolved:
                    from events_gen.registry import RegistryError
                    from events_gen.registry import add_city as _add

                    try:
                        _add(
                            name=resolved.name,
                            country=resolved.country,
                            country_code=resolved.country_code,
                            timezone=resolved.timezone,
                            latitude=resolved.latitude,
                            longitude=resolved.longitude,
                        )
                        st.success(f"Added **{resolved.name}, {resolved.country}**")
                        _cities.clear()  # bust the cache
                        st.rerun()
                    except RegistryError as exc:
                        st.info(str(exc))
                else:
                    st.warning(f"Could not geocode '{new_city_name}'.")
        with fav_col:
            st.caption("Toggle favorites")
            for slug in selected_cities:
                is_fav = slug in favorites
                if st.checkbox(f"⭐ {_city_label(slug)}", value=is_fav, key=f"toggle_fav_{slug}"):
                    if not is_fav:
                        storage.save_favorite(slug)
                else:
                    if is_fav:
                        storage.remove_favorite(slug)

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

    # Render format. Note: the output resolution caps the final quality on
    # YouTube — pick a 4K format for 2160p output (needs proportionally longer
    # render time). 1080p formats can never upload as 4K, however sharp the clips.
    def _fmt_label(f: str) -> str:
        vf = FORMATS[f]
        tier = "4K" if max(vf.width, vf.height) >= 3840 else "1080p HD"
        return f"{f} — {vf.width}×{vf.height} ({tier})"

    fmt = st.selectbox(
        "Video format",
        list(FORMATS.keys()),
        index=list(FORMATS.keys()).index(defaults.get("render_format", "reel")),
        format_func=_fmt_label,
        help=(
            "The output resolution caps the final YouTube quality. Choose a **4K** "
            "format (reel_4k / landscape_4k) for 2160p; the 1080p formats upload as "
            "1080p no matter how high-res the source clips are."
        ),
    )

    # Typography (font family, sizes, colors, placement) is customized once at the
    # end, after the video is rendered — see the "Font & style" pane in the preview.
    st.caption(
        "🎨 Fonts, colors, sizes, and text placement are customized in one place "
        "**after** the video renders — look for the **Font & style** pane in the preview."
    )

    # R5/R6: asset overrides
    col1, col2 = st.columns(2)
    image_upload = col1.file_uploader(
        "Background image (R5) — optional", type=["jpg", "jpeg", "png"]
    )
    music_upload = col2.file_uploader("Music track (R6) — optional", type=["mp3", "wav", "m4a"])

    # LLM toggle
    use_llm = st.toggle(
        "🤖 Use AI captions (Gemini)",
        value=True,
        help="On = Gemini writes captions; Off = fast template captions (no API call, instant).",
    )

    # Smart features (per-event)
    smart_bg = st.toggle(
        "🖼️ Smart backgrounds — use each event's venue/place image",
        value=False,
        help=(
            "Per event: use the event's own photo, else search Unsplash for the "
            "venue/city (needs UNSPLASH_ACCESS_KEY), else the shared background. "
            "Ignored when you upload a background above."
        ),
        disabled=image_upload is not None,
    )
    smart_music = st.toggle(
        "🎵 Smart music — pick a track from the events' type",
        value=False,
        help=(
            "Chooses a default track based on the dominant event type "
            "(needs audio files under assets/music/). Ignored when you upload music."
        ),
        disabled=music_upload is not None,
    )
    auto_music = st.toggle(
        "🎧 Auto music — trending royalty-free instrumental (Jamendo), non-repetitive",
        value=False,
        help=(
            "Auto-picks a popularity-ranked, royalty-free instrumental from Jamendo "
            "(needs JAMENDO_CLIENT_ID), avoiding tracks used in your recent posts. "
            "Note: commercial/Billboard audio is intentionally NOT used — it would get "
            "your posts muted or struck for copyright. Ignored when you upload music."
        ),
        disabled=music_upload is not None,
    )

    # Video clip backgrounds (M16)
    use_video_clips = st.toggle(
        "🎬 Video backgrounds — stock video clips per event",
        value=False,
        help=(
            "Search Pexels/Pixabay for short video clips of each venue/city. "
            "Needs PEXELS_API_KEY and/or PIXABAY_API_KEY. Falls back to images if no clips found."
        ),
    )

    # R8: destinations
    targets = st.multiselect(
        "Destinations (R8)",
        [Platform.YOUTUBE, Platform.INSTAGRAM],
        default=defaults.get("targets", []),
        format_func=lambda p: p.value.capitalize(),
    )

    # Shared generation kwargs. Typography (theme/fonts/placement/style) is left at
    # sensible defaults here and customized post-render via the Font & style pane.
    gen_kwargs: dict[str, Any] = {
        "city_slug": city_slug,
        "window": window_val,
        "event_types": selected_types,
        "count": count,
        "render_format": fmt,
        "image_upload": _save_upload(image_upload, ".jpg"),
        "music_upload": _save_upload(music_upload, ".mp3"),
        "smart_backgrounds": smart_bg,
        "smart_music": smart_music,
        "auto_music": auto_music,
        "use_llm": use_llm,
        "use_video_clips": use_video_clips,
        "targets": targets,
    }

    # ── Multi-city tabs or single-city flow ──
    if len(selected_cities) > 1:
        # Tabbed multi-city workflow (no top-level Fetch/Generate — each tab has its own).
        st.divider()
        col_batch, col_preset = st.columns([2, 1])
        if col_batch.button(
            "Generate All (auto-pick)",
            type="primary",
            help="Batch-generate for all cities using the top events (no manual picking).",
            use_container_width=True,
        ):
            _batch_generate_all(selected_cities, gen_kwargs)
        _poll_job(_BATCH_JOB_KEY, on_done=_on_batch_done)
        with col_preset.popover("Save as preset", use_container_width=True):
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

        tabs = st.tabs([_city_label(s) for s in selected_cities])
        for tab, tab_city in zip(tabs, selected_cities, strict=False):
            with tab:
                city_gen_kwargs = {**gen_kwargs, "city_slug": tab_city}
                _render_city_tab(tab_city, window_val, selected_types, count, fmt, city_gen_kwargs)
    else:
        # Single-city flow: action buttons + M10 picker.
        col_fetch, col_quick, col_save = st.columns([1, 1, 1])
        fetch_clicked = col_fetch.button(
            "Fetch Events",
            type="primary",
            use_container_width=True,
            help="Fetch a pool of event candidates for the picker below.",
        )
        quick_gen = col_quick.button(
            "Quick Generate",
            use_container_width=True,
            help="Skip the picker — generate directly using the top events.",
        )
        with col_save.popover("Save as preset", use_container_width=True):
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

        if quick_gen:
            _run_generation(**gen_kwargs)

        if fetch_clicked:
            _do_fetch(city_slug, window_val, selected_types, count)

        _poll_job(_gen_job_key(""), on_done=lambda draft_id: _on_generation_done("", draft_id))

        current_params: dict[str, Any] = {
            "city": city_slug,
            "window": window_val,
            "types": selected_types,
        }
        _render_picker_section(count, fmt, gen_kwargs, current_params)

        draft_id = st.session_state.get("last_draft_id")
        if draft_id:
            draft = storage.get_draft(draft_id)
            if draft:
                st.divider()
                _render_preview(draft)


def _render_city_tab(
    city_slug: str,
    window_val: TimeWindow,
    selected_types: list[str],
    count: int,
    fmt: str,
    gen_kwargs: dict[str, Any],
) -> None:
    """Render one city's fetch → pick → generate → preview inside a tab."""
    storage = _storage()
    tab_key = f"tab_{city_slug}"

    col_f, col_q = st.columns(2)
    if col_f.button("Fetch Events", key=f"fetch_{tab_key}", use_container_width=True):
        _do_fetch(city_slug, window_val, selected_types, count, state_key=tab_key)
    if col_q.button("Quick Generate", key=f"quick_{tab_key}", use_container_width=True):
        _run_generation(**gen_kwargs, state_key=tab_key)

    # A generation started in this tab keeps running even after a tab switch; the
    # poller shows live status and records the finished draft for this tab.
    _poll_job(
        _gen_job_key(tab_key),
        on_done=lambda draft_id: _on_generation_done(tab_key, draft_id),
    )

    current_params: dict[str, Any] = {
        "city": city_slug,
        "window": window_val,
        "types": selected_types,
    }
    _render_picker_section(count, fmt, gen_kwargs, current_params, state_key=tab_key)

    draft_id = st.session_state.get(f"last_draft_id_{tab_key}")
    if draft_id:
        draft = storage.get_draft(draft_id)
        if draft:
            _render_preview(draft)


_BATCH_JOB_KEY = "batch_generate"


def _batch_generate_all(cities: list[str], gen_kwargs: dict[str, Any]) -> None:
    """Launch a background job that generates a video per city (auto-picked events).

    Runs off the script thread so it survives tab switches. Returns a city→draft-id
    map that the on-done handler stores under each tab's key.
    """

    def work(progress: Callable[[str], None]) -> dict[str, str]:
        storage = _bg_storage()
        result: dict[str, str] = {}
        for city_slug in cities:
            progress(f"Generating for {city_slug}…")
            try:
                city_kwargs = {**gen_kwargs, "city_slug": city_slug}
                draft = pipeline.run(storage=storage, **city_kwargs)
                result[city_slug] = draft.id
                progress(f"  ✅ {city_slug} done")
            except pipeline.PipelineError as exc:
                progress(f"  ⚠️ {city_slug}: {exc}")
            except Exception as exc:  # noqa: BLE001 - continue with the other cities
                progress(f"  ❌ {city_slug}: {exc}")
        return result

    if jobs.start_job(_BATCH_JOB_KEY, work):
        st.rerun()


def _on_batch_done(result: dict[str, str] | None) -> None:
    """Store each city's finished draft id under its tab key (main thread)."""
    for city_slug, draft_id in (result or {}).items():
        st.session_state[f"last_draft_id_tab_{city_slug}"] = draft_id


_CANDIDATE_POOL_SIZE = 30


def _do_fetch(
    city_slug: str,
    window_val: TimeWindow,
    selected_types: list[str],
    count: int,
    *,
    settings: object = None,
    state_key: str = "",
) -> None:
    """Fetch a candidate pool and store in session state (namespaced by state_key).

    Uses fetch_by_source() so results are available both merged ("All") and
    per-source for the tabbed picker UI.
    """
    from events_gen.registry import get_city, load_event_types
    from events_gen.settings import get_settings
    from events_gen.sources import aggregator
    from events_gen.timewindow import compute_window

    prefix = f"{state_key}_" if state_key else ""
    s = get_settings()
    city = get_city(city_slug, s)
    all_types = load_event_types(s)
    wanted = set(selected_types)
    types = [t for t in all_types if t.slug in wanted] if wanted else []
    date_range = compute_window(window_val, city.timezone)
    by_source = aggregator.fetch_by_source(
        city, date_range, types, count=_CANDIDATE_POOL_SIZE, settings=s
    )
    candidates = by_source.get("All", [])
    st.session_state[f"{prefix}m10_candidates"] = [e.model_dump(mode="json") for e in candidates]
    st.session_state[f"{prefix}m10_selected_ids"] = {e.id for e in candidates[:count]}
    st.session_state[f"{prefix}m10_sort_key"] = "rank"
    st.session_state[f"{prefix}m10_fetch_params"] = {
        "city": city_slug,
        "window": window_val,
        "types": selected_types,
    }
    # Store per-source results for tabbed display.
    st.session_state[f"{prefix}m10_by_source"] = {
        name: [e.model_dump(mode="json") for e in events]
        for name, events in by_source.items()
    }
    if not candidates:
        st.warning("No events found for these criteria.")
    st.rerun()


def _render_picker_section(
    count: int,
    fmt_name: str,
    gen_kwargs: dict[str, Any],
    current_params: dict[str, Any],
    state_key: str = "",
) -> None:
    """Render the interactive event picker + live preview + Generate button.

    Displays per-source tabs (one for each source that returned results) plus
    an "All" tab with the merged/deduped/ranked events. Selection state is
    shared across tabs (checking an event in one tab checks it everywhere).
    """
    from events_gen.models import Event as _Event
    from events_gen.render import get_format
    from events_gen.ui.picker import (
        estimate_duration,
        is_fetch_stale,
        select_top_n,
        sort_candidates,
    )

    prefix = f"{state_key}_" if state_key else ""
    raw = st.session_state.get(f"{prefix}m10_candidates")
    if not raw:
        return

    fetch_params = st.session_state.get(f"{prefix}m10_fetch_params")
    if is_fetch_stale(fetch_params, current_params):
        st.info("Controls changed since last fetch. Click **Fetch Events** to refresh.")

    st.divider()
    st.subheader("Event Picker")

    # Sort control
    sort_options = {"Popularity": "rank", "Date": "date", "Price": "price", "Name": "name"}
    sort_label = st.radio(
        "Sort by", list(sort_options.keys()), horizontal=True, key=f"{prefix}m10_sort_radio"
    )
    sort_key = sort_options[sort_label]

    # Per-source tabs — build tab list from stored by_source data.
    by_source_raw: dict[str, list[dict[str, Any]]] = st.session_state.get(
        f"{prefix}m10_by_source", {}
    )
    # Tab order: "All" first, then individual sources (alphabetical).
    source_names = sorted(k for k in by_source_raw if k != "All")
    tab_names = ["All", *source_names]
    # Only show tabs if we have more than just "All".
    show_tabs = len(tab_names) > 1

    # Shared selection state across tabs.
    selected_ids: set[str] = st.session_state.get(f"{prefix}m10_selected_ids", set())

    if show_tabs:
        # Capitalize source names for display.
        tab_labels = [n.capitalize() for n in tab_names]
        tabs: Any = st.tabs(tab_labels)
    else:
        tabs = [st.container()]
        tab_names = ["All"]

    for tab_widget, tab_name in zip(tabs, tab_names, strict=False):
        with tab_widget:
            # Resolve which events to show in this tab.
            tab_raw = raw if tab_name == "All" else by_source_raw.get(tab_name, [])

            if not tab_raw:
                st.caption("No events from this source.")
                continue

            candidates = sort_candidates([_Event.model_validate(e) for e in tab_raw], sort_key)

            # Action buttons (scoped to this tab's candidates for top-N/all/clear).
            col_top, col_all, col_clear = st.columns(3)
            if col_top.button(
                f"Select top {count}",
                key=f"{prefix}top_n_{tab_name}",
                use_container_width=True,
            ):
                new_ids = select_top_n(candidates, count)
                st.session_state[f"{prefix}m10_selected_ids"] = (
                    st.session_state.get(f"{prefix}m10_selected_ids", set()) | new_ids
                )
                st.rerun()
            if col_all.button(
                "Select all", key=f"{prefix}sel_all_{tab_name}", use_container_width=True
            ):
                new_ids = {e.id for e in candidates}
                st.session_state[f"{prefix}m10_selected_ids"] = (
                    st.session_state.get(f"{prefix}m10_selected_ids", set()) | new_ids
                )
                st.rerun()
            if col_clear.button(
                "Clear all", key=f"{prefix}clr_all_{tab_name}", use_container_width=True
            ):
                tab_ids = {e.id for e in candidates}
                st.session_state[f"{prefix}m10_selected_ids"] = (
                    st.session_state.get(f"{prefix}m10_selected_ids", set()) - tab_ids
                )
                st.rerun()

            # Picker grid — checkboxes reflect shared selection state.
            for ev in candidates:
                cols = st.columns([0.5, 4, 2, 2, 2])
                checked = cols[0].checkbox(
                    f"Select {ev.title}",
                    value=(ev.id in selected_ids),
                    key=f"{prefix}ev_{tab_name}_{ev.id}",
                    label_visibility="collapsed",
                )
                if checked:
                    selected_ids.add(ev.id)
                elif ev.id in selected_ids:
                    selected_ids.discard(ev.id)
                cols[1].markdown(
                    f"**{ev.title}**" + (f"  \n_{ev.event_type}_" if ev.event_type else "")
                )
                cols[2].caption(ev.start.strftime("%a %d %b %H:%M"))
                cols[3].caption(ev.venue or "---")
                price = ""
                if ev.price_min is not None:
                    cur = ev.currency or "$"
                    price = f"{cur}{ev.price_min:.0f}"
                    if ev.price_max and ev.price_max != ev.price_min:
                        price += f"--{cur}{ev.price_max:.0f}"
                cols[4].caption(price or "---")

    st.session_state[f"{prefix}m10_selected_ids"] = selected_ids

    # Live preview strip (uses ALL candidates for resolving selected events).
    all_candidates = sort_candidates([_Event.model_validate(e) for e in raw], sort_key)
    n = len(selected_ids)
    if n > 0:
        video_fmt = get_format(fmt_name)
        dur = estimate_duration(n, video_fmt)
        st.markdown(f"**{n} selected** — estimated video: ~{dur:.0f}s")
        selected_evs = [e for e in all_candidates if e.id in selected_ids]
        thumb_cols = st.columns(min(n, 10))
        for col, ev in zip(thumb_cols, selected_evs[:10], strict=False):
            with col:
                if ev.image_url:
                    st.image(str(ev.image_url), width=70)
                else:
                    st.caption(ev.title[:15])
    else:
        st.info("Select at least one event to generate a video.")

    # Prepare button (only when selection is non-empty). Preparing is fast — it
    # fetches content + per-event assets but skips the video encode, so each event
    # gets an instant still preview below. The single video encode happens later,
    # when the user clicks "Combine into video".
    if n > 0 and st.button(
        "Prepare previews", type="primary", key=f"{prefix}gen", use_container_width=True
    ):
        selected_events = [e for e in all_candidates if e.id in selected_ids]
        _prepare_previews(**gen_kwargs, events=selected_events, state_key=state_key)


def _apply_preset(preset: CityPreset) -> None:
    st.session_state["preset_defaults"] = {
        "city_slug": preset.city_slug,
        "window": preset.window.value,
        "event_types": preset.event_types,
        "event_count": preset.event_count,
        "render_format": preset.render_format,
        "targets": preset.targets,
    }


def _gen_job_key(state_key: str) -> str:
    """Stable background-job key for a (tab-scoped) generation run."""
    return f"gen_{state_key or 'single'}"


def _run_generation(*, state_key: str = "", **kwargs: Any) -> None:
    """Launch a full generate (prepare + encode) in the background (Quick Generate).

    Used by the "Quick Generate" shortcut that skips the picker/still-preview flow.
    The interactive flow instead calls :func:`_prepare_previews` (fast, no encode)
    then combines into a video on demand.
    """
    key = _gen_job_key(state_key)

    def work(progress: Callable[[str], None]) -> str:
        storage = _bg_storage()
        draft = pipeline.run(progress=progress, storage=storage, **kwargs)
        return draft.id

    if jobs.start_job(key, work):
        st.rerun()


def _prepare_previews(*, state_key: str = "", **kwargs: Any) -> None:
    """Prepare a draft (fetch + content, NO video encode) in the background.

    Fast path for the still-preview flow: once done, each event gets an instant
    still preview and its own editing tools; the expensive video encode is
    deferred to the "Combine into video" button.
    """
    key = _gen_job_key(state_key)

    def work(progress: Callable[[str], None]) -> str:
        storage = _bg_storage()
        draft = pipeline.prepare_draft(progress=progress, storage=storage, **kwargs)
        return draft.id

    if jobs.start_job(key, work):
        st.rerun()


def _on_generation_done(state_key: str, draft_id: str | None) -> None:
    """Main-thread completion handler: record the new draft id for this tab."""
    if not draft_id:
        return
    st.session_state["last_draft_id"] = draft_id
    if state_key:
        st.session_state[f"last_draft_id_{state_key}"] = draft_id


def _render_preview(draft: PostDraft) -> None:
    """R7: per-event still previews → combine into video → publish.

    The edit flow leads with an instant still per event (no encode), each with its
    own source tools; the single video encode happens only when the user clicks
    "Combine into video".
    """
    st.subheader("Preview (R7)")

    _render_event_grid(draft)
    _render_combined_video(draft)
    _render_font_style(draft)
    _render_thumbnail_pane(draft)

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

    _render_publish(draft)

    st.caption(f"Draft `{draft.id}` · {len(draft.events)} events · status: {draft.status.value}")


def _preview_sig(draft: PostDraft, event_id: str) -> str:
    """Short hash of everything that determines an event's rendered look.

    Includes the resolved background (clip path / promo override) and the text
    settings. Rendered stills/segments are filed under this signature, so
    switching source or text produces a *different* filename — prior renders stay
    on disk and are reused instantly when you switch back (no re-render, no manual
    cache invalidation).
    """
    import hashlib

    content = draft.content
    clip = content.event_video_clips.get(event_id, "") if content else ""
    override = content.event_background_overrides.get(event_id, "") if content else ""
    bg = content.event_backgrounds.get(event_id, "") if content else ""
    parts = [
        clip,
        override,
        bg,
        content.background_image_path or "" if content else "",
        str(draft.theme),
        str(draft.intensity),
        str(draft.text_position),
        str(draft.text_style),
        str(draft.render_format),
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _still_path(draft: PostDraft, event_id: str) -> Path:
    """Cached still preview path, keyed by the event's render signature."""
    sig = _preview_sig(draft, event_id)
    return get_settings().output_dir / draft.id / "stills" / f"{event_id}_{sig}.jpg"


def _build_still(draft: PostDraft, event: Event, index: int, total: int) -> Path | None:
    """Render (and cache) one event's still preview image; return its path or None."""
    from events_gen.render import get_format, render_event_still

    if draft.content is None:
        return None
    out = _still_path(draft, event.id)
    if out.exists() and out.stat().st_size > 0:
        return out  # already rendered for this exact source/text combo
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        img = render_event_still(
            draft.content,
            event,
            index,
            total,
            fmt=get_format(draft.render_format),
            theme=draft.theme,
            intensity=draft.intensity,
            text_position=draft.text_position,
            text_style=draft.text_style,
        )
        img.save(out, quality=88)
        return out
    except Exception:  # noqa: BLE001 - a broken still shouldn't crash the page
        return None


def _render_style_preview_still(draft: PostDraft, font_style: FontStyle) -> str | None:
    """Render an instant still of the first event with ``font_style`` applied.

    Cached on disk keyed by a hash of the font-style values, so dragging a slider
    or re-picking a color reuses a prior render instantly and only new combos
    incur a (sub-second, pure-Pillow) render. Returns the image path or None.
    """
    import hashlib
    import traceback as tb

    from events_gen.models import FontStyle as _FS
    from events_gen.render import get_format, render_event_still

    if draft.content is None or not draft.events:
        return None
    if not isinstance(font_style, _FS):
        return None
    event = draft.events[0]
    try:
        sig = hashlib.sha1(
            font_style.model_dump_json().encode() + _preview_sig(draft, event.id).encode()
        ).hexdigest()[:16]
        out = get_settings().output_dir / draft.id / "style_preview" / f"{sig}.jpg"
        if out.exists() and out.stat().st_size > 0:
            return str(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        img = render_event_still(
            draft.content,
            event,
            1,
            len(draft.events),
            fmt=get_format(draft.render_format),
            theme=draft.theme,
            font_style=font_style,
        )
        img.save(out, quality=90)
        return str(out)
    except Exception:  # noqa: BLE001 - preview must never crash the page
        __import__("logging").getLogger(__name__).warning(
            "style preview failed:\n%s", tb.format_exc()
        )
        return None


def _segment_path(draft: PostDraft, event_id: str) -> Path:
    """Cached preview-segment video path, keyed by the event's render signature."""
    sig = _preview_sig(draft, event_id)
    return get_settings().output_dir / draft.id / "segments" / f"{event_id}_{sig}.mp4"


def _render_event_grid(draft: PostDraft) -> None:
    """Horizontal grid of instant still previews — one column per event, each with
    its own background-source tools. Changing a source re-fetches just that event's
    clip; the still/segment are cache-keyed by source+text so switching back reuses
    the prior render instead of rebuilding it."""
    content = draft.content
    if content is None or not draft.events:
        return

    # A per-event source change re-fetches a clip in the background. No cache
    # invalidation needed: previews are keyed by _preview_sig, so the new source
    # renders to a new file and the old one is left intact for instant reuse. If the
    # requested source yielded no clip (e.g. Wikimedia has no footage for the event),
    # record a warning so the tile can tell the user instead of failing silently.
    def _on_sources_done(result: Any) -> None:
        if not isinstance(result, dict):
            return
        # Handle per-event warnings from the batch apply.
        for key, val in result.items():
            if key.startswith("warn_"):
                eid = key[5:]
                requested = val
                if requested == "link":
                    msg = (
                        "Couldn't use that link — check it's a direct video file or a "
                        "Pexels / Pixabay / Coverr page URL. Kept the previous background."
                    )
                else:
                    label_txt = _SOURCE_LABELS.get(requested, requested)
                    msg = (
                        f"No {label_txt} clip found for this event — kept the previous "
                        "background. Try another source."
                    )
                st.session_state[f"src_warn_{draft.id}_{eid}"] = msg

    handled = _poll_job(f"sources_{draft.id}", on_done=_on_sources_done)

    total = len(draft.events)
    st.markdown(f"**{total} event preview(s)** — play/edit each, then combine into one video.")
    cols = st.columns(total)
    for i, (col, event) in enumerate(zip(cols, draft.events, strict=False)):
        with col:
            _render_event_tile(draft, event, i + 1, total, disabled=handled)

    # Batch "Apply all sources" button — collects all per-event radio selections and
    # processes every changed source in a single background job.
    if not handled and content is not None:
        _render_batch_apply(draft)


def _render_batch_apply(draft: PostDraft) -> None:
    """Collect all per-event source selections and apply them in one job."""
    content = draft.content
    if content is None:
        return
    # Gather what changed across all events.
    all_choices: dict[str, str] = {}
    all_uploads: dict[str, Path] = {}
    all_links: dict[str, str] = {}
    for event in draft.events:
        choice = st.session_state.get(f"src_{draft.id}_{event.id}")
        if choice is None:
            continue
        current = _current_source(content, event.id)
        if choice == current:
            # Check upload/link widgets — they might be new even if radio unchanged.
            if choice == "upload":
                up = st.session_state.get(f"upload_{draft.id}_{event.id}")
                if up is not None:
                    saved = _save_upload(up, ".mp4")
                    if saved:
                        all_choices[event.id] = "upload"
                        all_uploads[event.id] = saved
            elif choice == "link":
                link = (st.session_state.get(f"link_{draft.id}_{event.id}") or "").strip()
                if link:
                    all_choices[event.id] = "link"
                    all_links[event.id] = link
            continue
        all_choices[event.id] = choice
        if choice == "upload":
            up = st.session_state.get(f"upload_{draft.id}_{event.id}")
            if up is not None:
                saved = _save_upload(up, ".mp4")
                if saved:
                    all_uploads[event.id] = saved
        elif choice == "link":
            link = (st.session_state.get(f"link_{draft.id}_{event.id}") or "").strip()
            if link:
                all_links[event.id] = link

    n_changed = len(all_choices)
    label = f"Apply sources ({n_changed} changed)" if n_changed else "Apply sources"
    if st.button(
        label,
        key=f"batch_apply_{draft.id}",
        type="primary" if n_changed else "secondary",
        disabled=n_changed == 0,
        use_container_width=True,
    ):
        for eid in all_choices:
            st.session_state[f"play_{draft.id}_{eid}"] = False
            st.session_state.pop(f"src_warn_{draft.id}_{eid}", None)
        choices = dict(all_choices)
        uploads = dict(all_uploads)
        links = dict(all_links)

        def work(progress: Callable[[str], None]) -> dict[str, str]:
            storage = _bg_storage()
            d = pipeline.resolve_event_sources(
                draft, choices, uploads, links=links, storage=storage, progress=progress
            )
            # Report per-event outcomes for warning messages.
            results: dict[str, str] = {"draft_id": d.id}
            if d.content:
                for eid, requested in choices.items():
                    applied = d.content.event_clip_sources.get(eid, "")
                    if applied != requested:
                        results[f"warn_{eid}"] = requested
            return results

        if jobs.start_job(f"sources_{draft.id}", work):
            st.rerun()


def _render_event_tile(
    draft: PostDraft, event: Event, index: int, total: int, *, disabled: bool
) -> None:
    """One event cell: still thumbnail OR its playing segment, plus play + source tools."""
    playing_key = f"play_{draft.id}_{event.id}"
    seg = _segment_path(draft, event.id)

    # Poll this event's segment render; when it finishes, mark it playing and rerun.
    def _on_seg_done(_r: Any) -> None:
        st.session_state[playing_key] = True

    seg_rendering = _poll_job(f"seg_{draft.id}_{event.id}", on_done=_on_seg_done)

    if st.session_state.get(playing_key) and seg.exists():
        # Full playable segment (clip + text). Use the browser player's fullscreen.
        st.video(str(seg))
    else:
        still = _still_path(draft, event.id)
        if not still.exists():
            _build_still(draft, event, index, total)
        if still.exists():
            st.image(str(still), width="stretch")
        else:
            st.info("preview unavailable")

    st.caption(f"**{index}. {event.title}**")

    # Show which source this sub-video ended up using.
    if draft.content is not None:
        cur = _current_source(draft.content, event.id)
        st.caption(f"🎬 Using: **{_SOURCE_LABELS.get(cur, cur)}**")

    # Play / Show-still toggle. Play (re)renders the segment in the background if the
    # cache is stale, then swaps the thumbnail for the video player.
    if not seg_rendering and not disabled:
        if st.session_state.get(playing_key):
            if st.button("Show still", key=f"still_{draft.id}_{event.id}", use_container_width=True):
                st.session_state[playing_key] = False
                st.rerun()
        elif st.button("▶ Play", key=f"playbtn_{draft.id}_{event.id}", use_container_width=True):
            if seg.exists():
                st.session_state[playing_key] = True
                st.rerun()
            else:
                # Render to the signature-keyed path so switching source/text reuses
                # a prior segment instead of overwriting it.
                seg_out = seg

                def work(progress: Callable[[str], None]) -> str:
                    storage = _bg_storage()
                    d = storage.get_draft(draft.id) or draft
                    pipeline.render_event_preview(
                        d, event.id, out_path=seg_out, progress=progress
                    )
                    return d.id

                if jobs.start_job(f"seg_{draft.id}_{event.id}", work):
                    st.rerun()

    if not disabled:
        _render_event_source_control(draft, event)


def _render_event_source_control(draft: PostDraft, event: Event) -> None:
    """Per-event background-source picker (radio only — Apply is batch below the grid)."""
    content = draft.content
    if content is None:
        return
    has_promo = bool(event.image_url)
    options = _source_options(get_settings(), has_promo)
    current = _current_source(content, event.id)
    display_options = options if current in options else [current, *options]
    st.radio(
        "Background source",
        display_options,
        index=display_options.index(current),
        format_func=lambda v: _SOURCE_LABELS.get(v, v),
        key=f"src_{draft.id}_{event.id}",
        label_visibility="collapsed",
    )
    choice = st.session_state.get(f"src_{draft.id}_{event.id}", current)
    if choice == "upload":
        st.file_uploader(
            f"Upload short for {event.title}",
            type=["mp4", "mov"],
            key=f"upload_{draft.id}_{event.id}",
            label_visibility="collapsed",
        )
    elif choice == "link":
        st.text_input(
            "Clip link",
            key=f"link_{draft.id}_{event.id}",
            placeholder="https://…mp4  or page URL",
            label_visibility="collapsed",
        )

    warn_key = f"src_warn_{draft.id}_{event.id}"
    warn = st.session_state.get(warn_key)
    if warn:
        st.warning(warn)


def _render_combined_video(draft: PostDraft) -> None:
    """The single expensive encode: combine all event stills into one video."""
    st.divider()

    def _on_render_done(_r: Any) -> None:
        pass  # the draft's video_path is already persisted by render_draft

    handled = _poll_job(f"combine_{draft.id}", on_done=_on_render_done)

    if draft.video_path and Path(draft.video_path).exists():
        st.markdown("**Combined video**")
        col_vid, _ = st.columns([1, 1])
        col_vid.video(draft.video_path)
        label = "Re-combine into video"
    else:
        st.info("Combine the events above into a single video when you're happy with them.")
        label = "Combine into video"

    if not handled and st.button(
        label, type="primary", key=f"combine_{draft.id}", use_container_width=True
    ):

        def work(progress: Callable[[str], None]) -> str:
            storage = _bg_storage()
            d = storage.get_draft(draft.id) or draft
            pipeline.render_draft(d, storage=storage, progress=progress)
            return d.id

        if jobs.start_job(f"combine_{draft.id}", work):
            st.rerun()


def _render_thumbnail_pane(draft: PostDraft) -> None:
    """Thumbnail pane: current pick + a gallery of 10+ options to choose from.

    Each option pairs a heading layout with a different (vibrant) event backdrop.
    Also supports editing the headline, regenerating options, and uploading a
    custom image. The chosen thumbnail is what viewers see before pressing play.
    """
    if draft.content is None:
        return
    st.divider()
    st.markdown("### 🖼️ Thumbnail — shown before the video plays")

    gen_key = f"thumbopts_{draft.id}"
    generating = _poll_job(gen_key, on_done=lambda _r: None)

    # Current selection.
    thumb = draft.thumbnail_path
    if thumb and Path(thumb).exists():
        st.image(thumb, width=240, caption="Current thumbnail")
    elif not generating:
        st.caption("No thumbnail yet — click **Generate 10 options** below.")

    # Headline + custom upload controls.
    default_title = (
        draft.thumbnail_title if draft.thumbnail_title is not None else draft.content.title
    )
    new_title = st.text_input("Thumbnail headline", default_title, key=f"thumbtitle_{draft.id}")
    c1, c2 = st.columns(2)
    if not generating and c1.button(
        "Generate 10 options", key=f"thumbgen_{draft.id}", use_container_width=True
    ):
        title_override = new_title

        def work(progress: Callable[[str], None]) -> str:
            storage = _bg_storage()
            d = storage.get_draft(draft.id) or draft
            d.thumbnail_title = title_override
            storage.save_draft(d)
            pipeline.render_thumbnail_options(d, count=10, storage=storage, progress=progress)
            return d.id

        if jobs.start_job(gen_key, work):
            st.rerun()

    upload = c2.file_uploader(
        "Upload your own", type=["jpg", "jpeg", "png"], key=f"thumbupload_{draft.id}",
        label_visibility="collapsed",
    )
    if upload is not None:
        up_path = _save_upload(upload, ".jpg")
        if up_path is not None and c2.button(
            "Use uploaded image", key=f"thumbuse_{draft.id}", use_container_width=True
        ):
            import shutil

            dest = get_settings().output_dir / draft.id / "thumbnail.jpg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(up_path, dest)
            draft.thumbnail_path = str(dest)
            draft.thumbnail_choice = None
            _storage().save_draft(draft)
            st.rerun()

    # Option gallery — pick one.
    fresh = _storage().get_draft(draft.id) or draft
    options = [(k, p) for k, p in fresh.thumbnail_options.items() if Path(p).exists()]
    if options:
        st.caption("Pick a thumbnail:")
        for row_start in range(0, len(options), _GALLERY_COLS):
            cols = st.columns(_GALLERY_COLS)
            for col, (opt_key, path) in zip(
                cols, options[row_start : row_start + _GALLERY_COLS], strict=False
            ):
                with col:
                    is_sel = opt_key == fresh.thumbnail_choice
                    st.image(path, width="stretch")
                    if st.button(
                        "✓ Selected" if is_sel else "Use this",
                        key=f"thumbpick_{draft.id}_{opt_key}",
                        disabled=is_sel,
                        use_container_width=True,
                    ):
                        fresh.thumbnail_choice = opt_key
                        fresh.thumbnail_path = path
                        _storage().save_draft(fresh)
                        st.rerun()


_SOURCE_LABELS = {
    "wikimedia": "Wikimedia — real venue/act footage",
    "pexels": "Pexels — stock video",
    "pixabay": "Pixabay — stock video",
    "coverr": "Coverr — stock video",
    "stock": "Stock video (any provider)",
    "promo": "Animated promo image",
    "upload": "Upload your own short",
    "link": "Paste a clip link",
}


def _source_options(settings: object, has_promo: bool) -> list[str]:
    """Available source bullets for one event: keyless + key-configured providers.

    Stock providers only appear when their key is set (so the user isn't offered a
    source that can't work); "promo" only when the event has an image. "link" (paste
    a clip URL) and "upload" are always available.
    """
    from events_gen.content.video_clips import provider_available

    opts: list[str] = ["wikimedia"]  # keyless, always available
    for prov in ("pexels", "pixabay", "coverr"):
        if provider_available(prov, settings):  # type: ignore[arg-type]
            opts.append(prov)
    if has_promo:
        opts.append("promo")
    opts.extend(["link", "upload"])
    return opts


def _current_source(content: PostContent, event_id: str) -> str:
    """Which source the event's current clip uses (for the radio default)."""
    if event_id in content.event_clip_sources:
        src = str(content.event_clip_sources[event_id])
        # Legacy "stock" clips predate per-provider tracking; keep them selectable.
        return src
    if content.event_background_overrides.get(event_id) == "promo":
        return "promo"
    if event_id in content.event_video_clips:
        return "stock"  # legacy clip without source tracking
    return "wikimedia"


# Number of thumbnail options shown per row.
_GALLERY_COLS = 3

# Placements/styles for the font pane.
_PLACEMENTS = ["top", "center", "bottom"]
_TEXT_STYLES = ["panel", "outline", "shadow"]


def _show_font_sample(font_path: str, font_name: str) -> None:
    """Render the font name in its own typeface as a small preview image."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype(font_path, 28)
        img = Image.new("RGBA", (400, 44), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((8, 6), font_name, fill=(255, 255, 255, 240), font=font)
        st.image(img, width=300)
    except Exception:  # noqa: BLE001
        pass


def _render_font_style(draft: PostDraft) -> None:
    """Single post-render typography pane: font, sizes, colors, placement, style.

    All video + thumbnail text uses one :class:`FontStyle`. Changing it here and
    clicking Apply re-renders the video (and thumbnail) in the background with the
    new typography applied everywhere at once.
    """
    from events_gen.models import FontStyle
    from events_gen.render import available_fonts

    if draft.content is None or not draft.events:
        return
    st.divider()
    st.markdown("### 🎨 Font & style — applied to all text")
    st.caption(
        "Adjust the controls — the preview on the right updates **instantly** "
        "(a real frame of the video with your typography). Click **Apply & re-render** "
        "to bake it into the final video and thumbnail."
    )

    fs = draft.font_style or FontStyle()
    fonts = available_fonts()  # name -> path
    font_names = ["(default)", *fonts.keys()]
    cur_font_idx = font_names.index(fs.font_name) if fs.font_name in font_names else 0

    controls, preview = st.columns([3, 2])
    with controls:
        c1, c2 = st.columns(2)
        font_name = c1.selectbox(
            "Font family",
            font_names,
            index=cur_font_idx,
            key=f"fs_font_{draft.id}",
            help="Only fonts that render Latin text are listed (CJK/emoji/symbol fonts filtered out).",
        )
        # Show the selected font's name rendered in its own typeface so you can see
        # what it looks like before applying.
        if font_name != "(default)" and font_name in fonts:
            _show_font_sample(fonts[font_name], font_name)

        placement = c2.selectbox(
            "Text placement",
            _PLACEMENTS,
            index=_PLACEMENTS.index(fs.placement) if fs.placement in _PLACEMENTS else 1,
            format_func=str.capitalize,
            key=f"fs_place_{draft.id}",
        )

        _ALIGNS = ["left", "center", "right"]
        text_align = st.radio(
            "Text alignment",
            _ALIGNS,
            index=_ALIGNS.index(fs.text_align) if fs.text_align in _ALIGNS else 0,
            format_func=str.capitalize,
            horizontal=True,
            key=f"fs_align_{draft.id}",
        )

        c3, c4, c5 = st.columns(3)
        title_size = c3.number_input(
            "Title size", 24, 200, value=int(fs.title_size), step=2, key=f"fs_tsize_{draft.id}"
        )
        body_size = c4.number_input(
            "Body size", 16, 140, value=int(fs.body_size), step=2, key=f"fs_bsize_{draft.id}"
        )
        text_style = c5.selectbox(
            "Legibility",
            _TEXT_STYLES,
            index=_TEXT_STYLES.index(fs.text_style) if fs.text_style in _TEXT_STYLES else 2,
            format_func=str.capitalize,
            key=f"fs_style_{draft.id}",
            help="Panel = box behind text; Outline/Shadow keep the video visible.",
        )

        c6, c7, c8 = st.columns(3)
        title_color = c6.color_picker("Title color", fs.title_color, key=f"fs_tcol_{draft.id}")
        body_color = c7.color_picker("Body color", fs.body_color, key=f"fs_bcol_{draft.id}")
        accent_color = c8.color_picker("Accent color", fs.accent_color, key=f"fs_acol_{draft.id}")

        panel_opacity = st.slider(
            "Panel opacity",
            0.0,
            1.0,
            value=float(fs.panel_opacity),
            step=0.05,
            disabled=text_style != "panel",
            key=f"fs_pop_{draft.id}",
            help="Only used with the Panel legibility style.",
        )
        uppercase = st.checkbox(
            "Uppercase titles", value=fs.uppercase_titles, key=f"fs_upper_{draft.id}"
        )

    # Build the in-progress FontStyle from the current control values.
    live_fs = FontStyle(
        font_path=fonts.get(font_name),
        font_name=None if font_name == "(default)" else font_name,
        title_size=int(title_size),
        body_size=int(body_size),
        title_color=title_color,
        body_color=body_color,
        accent_color=accent_color,
        placement=placement,
        text_align=text_align,
        text_style=text_style,
        panel_opacity=panel_opacity,
        uppercase_titles=uppercase,
    )

    # Live preview: render an instant still of the first event with the current
    # style overlaid on the real video frame. Pure Pillow, so it updates on every
    # widget change with no video encode.
    with preview:
        st.caption("Live preview")
        still = _render_style_preview_still(draft, live_fs)
        if still is not None:
            st.image(still, width="stretch")
        else:
            # Fallback: show the plain first-event still (no font_style) so the
            # preview area is never empty.
            fallback = _still_path(draft, draft.events[0].id)
            if not fallback.exists():
                _build_still(draft, draft.events[0], 1, len(draft.events))
            if fallback.exists():
                st.image(str(fallback), width="stretch")
                st.caption("_Font preview loading…_")

    key = f"combine_{draft.id}"  # reuse the combine job slot — it re-renders video
    rendering = jobs.is_running(key)
    if not rendering and st.button(
        "Apply & re-render",
        type="primary",
        key=f"fs_apply_{draft.id}",
        use_container_width=True,
    ):
        draft.font_style = live_fs
        # Sync the legacy render fields so they can never conflict with font_style.
        draft.text_style = live_fs.text_style
        draft.text_position = live_fs.placement
        draft.intensity = live_fs.panel_opacity
        _storage().save_draft(draft)

        def work(progress: Callable[[str], None]) -> str:
            storage = _bg_storage()
            d = storage.get_draft(draft.id) or draft
            pipeline.render_video_in_place(d, storage=storage, progress=progress)
            return d.id

        if jobs.start_job(key, work):
            st.rerun()


def _render_publish(draft: PostDraft) -> None:
    """R8/R9: destination-aware publish buttons with dry-run + live modes."""
    st.markdown("**Publish (R8/R9)**")
    targets = draft.targets or [Platform.YOUTUBE, Platform.INSTAGRAM]
    dry_run = st.toggle(
        "Dry run (no real upload)",
        value=True,
        key=f"dry_{draft.id}",
        help="Simulates the publish flow end-to-end without touching any account.",
    )
    chosen = st.multiselect(
        "Destinations",
        [Platform.YOUTUBE, Platform.INSTAGRAM],
        default=targets,
        format_func=lambda p: p.value.capitalize(),
        key=f"pubtargets_{draft.id}",
    )
    if st.button("Publish now", key=f"pub_{draft.id}", disabled=not chosen):
        from events_gen import publish

        with st.status("Publishing…", expanded=True) as status:
            try:
                results = publish.publish_draft(
                    draft, targets=chosen, dry_run=dry_run, storage=_storage()
                )
                for r in results:
                    if r.success:
                        status.write(f"✅ {r.platform.value}: {r.url}")
                    else:
                        status.write(f"❌ {r.platform.value}: {r.error}")
                ok = all(r.success for r in results)
                if ok:
                    # Clear this draft's cached clips once published (M: session cache).
                    from events_gen.content import clip_cache

                    clip_cache.clear_draft_cache(get_settings(), draft.id)
                status.update(
                    label="Published." if ok else "Some destinations failed.",
                    state="complete" if ok else "error",
                )
            except publish.PublishError as exc:
                status.update(label="Publish error.", state="error")
                st.warning(str(exc))


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
    """R9/M7.4: publish results + a run log of every job (incl. scheduled runs)."""
    st.header("History")
    storage = _storage()

    published = storage.list_drafts(status=DraftStatus.PUBLISHED.value)
    if published:
        st.subheader("Published")
        for draft in published:
            st.write(f"**{draft.city_slug}** — {draft.content.title if draft.content else ''}")
            for result in draft.results:
                icon = "✅" if result.success else "❌"
                st.write(f"  {icon} {result.platform.value}: {result.url or result.error}")

    jobs = storage.list_jobs()
    st.subheader("Run log")
    if not jobs:
        st.info("No runs yet. Generate, publish, or trigger a schedule to populate this.")
        return
    st.dataframe(
        [
            {
                "when": (j.created_at.strftime("%Y-%m-%d %H:%M") if j.created_at else ""),
                "kind": j.kind,
                "status": j.status.value,
                "detail": j.detail or j.error or "",
            }
            for j in jobs
        ],
        use_container_width=True,
        hide_index=True,
    )


# ── Schedules page (M7.3) ─────────────────────────────────────────────────


def page_schedules() -> None:
    st.header("Schedules")
    st.caption("Automation is **off by default**. Enable a per-city cadence to auto-generate.")
    storage = _storage()
    cities = _cities()
    types = _event_types()
    city_by_slug = {c.slug: c for c in cities}

    with st.expander("New schedule", expanded=not storage.list_schedules()):
        city_slug = st.selectbox(
            "City",
            [c.slug for c in cities],
            format_func=lambda s: city_by_slug[s].name,
            key="sched_city",
        )
        cadence = st.radio(
            "Cadence",
            [ScheduleCadence.WEEKLY, ScheduleCadence.MONTHLY],
            format_func=lambda c: c.value.capitalize(),
            horizontal=True,
            key="sched_cadence",
        )
        window = st.radio(
            "Window",
            [TimeWindow.WEEK, TimeWindow.MONTH],
            format_func=lambda w: w.value.capitalize(),
            horizontal=True,
            key="sched_window",
        )
        sel_types = st.multiselect(
            "Event types (empty = all)", [t.slug for t in types], key="sched_types"
        )
        count = st.slider("Number of events", 3, 15, 5, key="sched_count")
        targets = st.multiselect(
            "Destinations",
            [Platform.YOUTUBE, Platform.INSTAGRAM],
            format_func=lambda p: p.value.capitalize(),
            key="sched_targets",
        )
        auto_publish = st.toggle(
            "Auto-publish (otherwise: generate draft, review required)",
            value=False,
            key="sched_autopub",
        )
        if st.button("Create schedule", type="primary"):
            storage.save_schedule(
                Schedule(
                    city_slug=city_slug,
                    cadence=cadence,
                    window=window,
                    event_types=sel_types,
                    event_count=count,
                    targets=targets,
                    auto_publish=auto_publish,
                    enabled=True,
                )
            )
            st.success("Schedule created.")
            st.rerun()

    schedules = storage.list_schedules()
    if not schedules:
        st.info("No schedules yet.")
        return

    st.subheader("Existing")
    for sched in schedules:
        name = city_by_slug.get(sched.city_slug)
        title = name.name if name else sched.city_slug
        pub = "auto-publish" if sched.auto_publish else "review required"
        with st.expander(f"{title} · {sched.cadence.value} · {pub}"):
            enabled = st.toggle("Enabled", value=sched.enabled, key=f"en_{sched.id}")
            if enabled != sched.enabled:
                sched.enabled = enabled
                storage.save_schedule(sched)
                st.rerun()
            col1, col2 = st.columns(2)
            if col1.button("Run now", key=f"runnow_{sched.id}"):
                from events_gen.scheduler import run_schedule

                with st.status("Running schedule…", expanded=True) as status:
                    job = run_schedule(sched, storage=storage)
                    status.write(job.detail or job.error or "done")
                    status.update(
                        label=f"Run {job.status.value}.",
                        state="complete" if job.status.value == "succeeded" else "error",
                    )
            if col2.button("Delete", key=f"delsched_{sched.id}"):
                storage.delete_schedule(sched.id)
                st.rerun()


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
    st.subheader("Source status")
    st.caption(
        "Keyless-first: rows marked *keyless* always work with no setup. Others are "
        "active only when their key is set in `.env` — add a key to widen the pool."
    )

    def _status_table(title: str, rows: list[tuple[str, bool, str]]) -> None:
        st.markdown(f"**{title}**")
        for label, active, note in rows:
            icon = "✅" if active else "⚪️"
            st.markdown(f"{icon} **{label}** — {note}")

    _status_table(
        "🎬 Video clips",
        [
            ("Wikimedia Commons", True, "keyless — real venue/performer footage"),
            ("Pexels", bool(s.pexels_api_key), "PEXELS_API_KEY — stock clips"),
            ("Pixabay", bool(s.pixabay_api_key), "PIXABAY_API_KEY — stock clips"),
            ("Coverr", bool(s.coverr_api_key), "COVERR_API_KEY — optional extra clips"),
        ],
    )
    _status_table(
        "🎵 Music",
        [
            ("Openverse audio", True, "keyless — aggregates Jamendo + Freesound + more"),
            ("Jamendo", bool(s.jamendo_client_id), "JAMENDO_CLIENT_ID — mood-matched tracks"),
        ],
    )
    _status_table(
        "🖼️ Images / captions",
        [
            ("Openverse images", True, "keyless — CC venue/place backgrounds"),
            ("Unsplash", bool(s.unsplash_access_key), "UNSPLASH_ACCESS_KEY — venue photos"),
            ("Gemini captions", bool(s.gemini_api_key), "GEMINI_API_KEY — AI captions"),
            ("Anthropic captions", bool(s.anthropic_api_key), "ANTHROPIC_API_KEY — AI captions"),
        ],
    )
    _status_table(
        "📅 Events / publishing",
        [
            ("Ticketmaster", bool(s.ticketmaster_api_key), "TICKETMASTER_API_KEY — live events"),
            ("Eventbrite", bool(s.eventbrite_api_token), "EVENTBRITE_API_TOKEN — live events"),
            ("SeatGeek", bool(s.seatgeek_client_id), "SEATGEEK_CLIENT_ID — live events"),
            ("PredictHQ", bool(s.predicthq_api_token), "PREDICTHQ_API_TOKEN — live events"),
            ("YouTube", bool(s.youtube_client_secrets_file), "OAuth client — publishing"),
            ("Instagram", bool(s.instagram_access_token), "access token — publishing"),
        ],
    )

    # Destinations management (Feature 4).
    st.divider()
    _render_destinations_section()


def _render_destinations_section() -> None:
    """Per-city destination management: list, add, and delete publishing destinations."""
    from events_gen.models import Destination, Platform

    st.subheader("Destinations")
    st.caption(
        "Manage publishing destinations per city. Each destination is a linked "
        "YouTube or Instagram account."
    )
    storage = _storage()
    cities = _cities()
    if not cities:
        st.info("No cities configured.")
        return

    city_by_slug = {c.slug: c for c in cities}
    city_slugs = [c.slug for c in cities]

    dest_city = st.selectbox(
        "City",
        city_slugs,
        format_func=lambda s: city_by_slug[s].name,
        key="dest_city_select",
    )

    destinations = storage.list_destinations(city_slug=dest_city)

    # Show existing destinations.
    if destinations:
        for dest in destinations:
            platform_icon = "📺" if dest.platform == Platform.YOUTUBE else "📷"
            col_info, col_del = st.columns([5, 1])
            col_info.markdown(f"{platform_icon} **{dest.label}** — {dest.platform.value.capitalize()}")
            if col_del.button("Delete", key=f"del_dest_{dest.id}"):
                storage.delete_destination(dest.id)
                st.rerun()
    else:
        st.info("No destinations for this city yet.")

    # Add a new destination.
    with st.expander("Add destination", expanded=False):
        platform = st.selectbox(
            "Platform",
            [Platform.YOUTUBE, Platform.INSTAGRAM],
            format_func=lambda p: p.value.capitalize(),
            key="dest_platform",
        )
        label = st.text_input("Label (e.g. 'Main channel')", key="dest_label")
        youtube_secrets_path: str | None = None
        if platform == Platform.YOUTUBE:
            youtube_secrets_path = st.text_input(
                "Path to client_secrets.json",
                placeholder="./secrets/youtube_client_secret.json",
                key="dest_yt_secrets",
            )
        if st.button("Add destination", disabled=not label, type="primary"):
            new_dest = Destination(
                city_slug=dest_city,
                label=label,
                platform=platform,
                youtube_client_secrets_path=youtube_secrets_path if platform == Platform.YOUTUBE else None,
            )
            storage.save_destination(new_dest)
            st.success(f"Added {platform.value.capitalize()} destination: {label}")
            st.rerun()


PAGES = {
    "Create": page_create,
    "Drafts": page_drafts,
    "Schedules": page_schedules,
    "History": page_history,
    "Settings": page_settings,
}


def main() -> None:
    st.set_page_config(page_title="Events-Gen", page_icon="🎬", layout="centered")
    st.sidebar.title("🎬 Events-Gen")
    choice = st.sidebar.radio("Navigate", list(PAGES.keys()))
    st.sidebar.caption("Discover city events → generate a video → publish.")

    # One-click Publish Favorites (M14).
    storage = _storage()
    favorites = storage.list_favorites()
    if favorites:
        st.sidebar.divider()
        if st.sidebar.button("Publish Favorites", use_container_width=True):
            _publish_favorites(favorites, storage)

    PAGES[choice]()


def _publish_favorites(favorites: list[str], storage: Storage) -> None:
    """Batch dry-run publish the latest ready draft for each favorite city."""
    from events_gen import publish
    from events_gen.models import DraftStatus

    st.sidebar.info(f"Publishing {len(favorites)} favorite(s)…")
    for slug in favorites:
        drafts = storage.list_drafts(city_slug=slug, status=DraftStatus.READY.value, limit=1)
        if not drafts:
            st.sidebar.warning(f"{slug}: no ready draft — generate one first.")
            continue
        draft = drafts[0]
        issues = publish.validate_draft(draft)
        if any("missing" in i.lower() or "no rendered" in i.lower() for i in issues):
            st.sidebar.warning(f"{slug}: {issues[0]}")
            continue
        results = publish.publish_draft(draft, dry_run=True, storage=storage)
        for r in results:
            if r.success:
                st.sidebar.success(f"{slug} → {r.platform.value}: {r.url}")
            else:
                st.sidebar.error(f"{slug} → {r.platform.value}: {r.error}")


if __name__ == "__main__":
    main()
