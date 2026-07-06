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
from typing import Any

import streamlit as st

from events_gen import pipeline
from events_gen.models import (
    City,
    CityPreset,
    DraftStatus,
    EventType,
    Platform,
    PostDraft,
    Schedule,
    ScheduleCadence,
    TimeWindow,
)
from events_gen.registry import load_cities, load_event_types
from events_gen.render import DEFAULT_THEME, FORMATS, THEMES
from events_gen.render.animations import ANIMATIONS
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

    # Render format
    fmt = st.selectbox(
        "Video format",
        list(FORMATS.keys()),
        index=list(FORMATS.keys()).index(defaults.get("render_format", "reel")),
        format_func=lambda f: f"{f} ({FORMATS[f].width}×{FORMATS[f].height})",
    )

    # Theme (fonts / colors / style) + scrim intensity
    theme_names = list(THEMES.keys())
    default_theme = defaults.get("theme", DEFAULT_THEME)
    theme = st.selectbox(
        "Theme",
        theme_names,
        index=theme_names.index(default_theme) if default_theme in theme_names else 0,
        format_func=lambda t: f"{t} — {THEMES[t].description}",
        help="Each theme sets its own fonts, colors, and default text-panel intensity.",
    )
    preset_intensity = defaults.get("intensity")
    intensity = st.slider(
        "Background panel intensity",
        0.0,
        1.0,
        value=float(
            preset_intensity if preset_intensity is not None else THEMES[theme].card_opacity / 255
        ),
        step=0.05,
        help=(
            "Opacity of the panel the text sits on. Higher = more opaque/readable; "
            "lower = more of the background image shows through."
        ),
    )

    # Animation preset (motion style)
    anim_names = list(ANIMATIONS.keys())
    animation = st.radio(
        "Animation",
        anim_names,
        format_func=lambda a: f"{a} — {ANIMATIONS[a].description}",
        horizontal=True,
        help="Motion style: none (static), hype (fast zoom + slide), cinematic (subtle Ken Burns).",
    )

    # R5/R6: asset overrides
    col1, col2 = st.columns(2)
    image_upload = col1.file_uploader(
        "Background image (R5) — optional", type=["jpg", "jpeg", "png"]
    )
    music_upload = col2.file_uploader("Music track (R6) — optional", type=["mp3", "wav", "m4a"])

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

    # R8: destinations
    targets = st.multiselect(
        "Destinations (R8)",
        [Platform.YOUTUBE, Platform.INSTAGRAM],
        default=defaults.get("targets", []),
        format_func=lambda p: p.value.capitalize(),
    )

    # ── Action buttons ──
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
                    theme=theme,
                    intensity=intensity,
                    targets=targets,
                )
            )
            st.success(f"Saved preset '{preset_name}'.")

    # Shared generation kwargs (used by both picker-Generate and Quick Generate).
    gen_kwargs: dict[str, object] = {
        "city_slug": city_slug,
        "window": window_val,
        "event_types": selected_types,
        "count": count,
        "render_format": fmt,
        "theme": theme,
        "intensity": intensity,
        "animation": animation,
        "image_upload": _save_upload(image_upload, ".jpg"),
        "music_upload": _save_upload(music_upload, ".mp3"),
        "smart_backgrounds": smart_bg,
        "smart_music": smart_music,
        "auto_music": auto_music,
        "targets": targets,
    }

    # ── Quick Generate (old flow, no picker) ──
    if quick_gen:
        _run_generation(**gen_kwargs, preview_all_themes=False)

    # ── Fetch → Picker → Generate flow (M10) ──
    if fetch_clicked:
        _do_fetch(city_slug, window_val, selected_types, count, settings=None)

    current_params = {"city": city_slug, "window": window_val, "types": selected_types}
    _render_picker_section(count, fmt, gen_kwargs, current_params)

    # Show the just-generated draft's preview inline.
    draft_id = st.session_state.get("last_draft_id")
    if draft_id:
        draft = storage.get_draft(draft_id)
        if draft:
            st.divider()
            _render_preview(draft)


_CANDIDATE_POOL_SIZE = 30


def _do_fetch(
    city_slug: str,
    window_val: TimeWindow,
    selected_types: list[str],
    count: int,
    *,
    settings: object,
) -> None:
    """Fetch a candidate pool and store in session state."""
    from events_gen.registry import get_city, load_event_types
    from events_gen.settings import get_settings
    from events_gen.sources import aggregator
    from events_gen.timewindow import compute_window

    s = get_settings()
    city = get_city(city_slug, s)
    all_types = load_event_types(s)
    wanted = set(selected_types)
    types = [t for t in all_types if t.slug in wanted] if wanted else []
    date_range = compute_window(window_val, city.timezone)
    candidates = aggregator.fetch(city, date_range, types, count=_CANDIDATE_POOL_SIZE, settings=s)
    st.session_state["m10_candidates"] = [e.model_dump(mode="json") for e in candidates]
    st.session_state["m10_selected_ids"] = {e.id for e in candidates[:count]}
    st.session_state["m10_sort_key"] = "rank"
    st.session_state["m10_fetch_params"] = {
        "city": city_slug,
        "window": window_val,
        "types": selected_types,
    }
    if not candidates:
        st.warning("No events found for these criteria.")
    st.rerun()


def _render_picker_section(
    count: int,
    fmt_name: str,
    gen_kwargs: dict[str, object],
    current_params: dict[str, Any],
) -> None:
    """Render the interactive event picker + live preview + Generate button."""
    from events_gen.models import Event as _Event
    from events_gen.render import get_format
    from events_gen.ui.picker import (
        estimate_duration,
        is_fetch_stale,
        select_top_n,
        sort_candidates,
    )

    raw = st.session_state.get("m10_candidates")
    if not raw:
        return

    fetch_params = st.session_state.get("m10_fetch_params")
    if is_fetch_stale(fetch_params, current_params):
        st.info("Controls changed since last fetch. Click **Fetch Events** to refresh.")

    st.divider()
    st.subheader("Event Picker")

    # Sort control
    sort_options = {"Popularity": "rank", "Date": "date", "Price": "price", "Name": "name"}
    sort_label = st.radio(
        "Sort by", list(sort_options.keys()), horizontal=True, key="m10_sort_radio"
    )
    sort_key = sort_options[sort_label]

    candidates = sort_candidates([_Event.model_validate(e) for e in raw], sort_key)
    selected_ids: set[str] = st.session_state.get("m10_selected_ids", set())

    # Action buttons
    col_top, col_all, col_clear = st.columns(3)
    if col_top.button(f"Select top {count}", use_container_width=True):
        st.session_state["m10_selected_ids"] = select_top_n(candidates, count)
        st.rerun()
    if col_all.button("Select all", use_container_width=True):
        st.session_state["m10_selected_ids"] = {e.id for e in candidates}
        st.rerun()
    if col_clear.button("Clear all", use_container_width=True):
        st.session_state["m10_selected_ids"] = set()
        st.rerun()

    # Picker grid
    new_selected: set[str] = set()
    for ev in candidates:
        cols = st.columns([0.5, 4, 2, 2, 2])
        checked = cols[0].checkbox("", value=(ev.id in selected_ids), key=f"ev_{ev.id}")
        if checked:
            new_selected.add(ev.id)
        cols[1].markdown(f"**{ev.title}**" + (f"  \n_{ev.event_type}_" if ev.event_type else ""))
        cols[2].caption(ev.start.strftime("%a %d %b %H:%M"))
        cols[3].caption(ev.venue or "—")
        price = ""
        if ev.price_min is not None:
            cur = ev.currency or "$"
            price = f"{cur}{ev.price_min:.0f}"
            if ev.price_max and ev.price_max != ev.price_min:
                price += f"–{cur}{ev.price_max:.0f}"
        cols[4].caption(price or "—")

    st.session_state["m10_selected_ids"] = new_selected

    # Live preview strip
    n = len(new_selected)
    if n > 0:
        video_fmt = get_format(fmt_name)
        dur = estimate_duration(n, video_fmt)
        st.markdown(f"**{n} selected** — estimated video: ~{dur:.0f}s")
        selected_evs = [e for e in candidates if e.id in new_selected]
        thumb_cols = st.columns(min(n, 10))
        for col, ev in zip(thumb_cols, selected_evs[:10], strict=False):
            with col:
                if ev.image_url:
                    st.image(str(ev.image_url), width=70)
                else:
                    st.caption(ev.title[:15])
    else:
        st.info("Select at least one event to generate a video.")

    # Generate + Preview buttons (only when selection is non-empty)
    if n > 0:
        col_g, col_p = st.columns(2)
        gen_clicked = col_g.button("Generate Video", type="primary", use_container_width=True)
        prev_clicked = col_p.button("Preview themes", use_container_width=True)
        if gen_clicked or prev_clicked:
            selected_events = [e for e in candidates if e.id in new_selected]
            _run_generation(
                **gen_kwargs,
                events=selected_events,
                preview_all_themes=prev_clicked,
            )


def _apply_preset(preset: CityPreset) -> None:
    st.session_state["preset_defaults"] = {
        "city_slug": preset.city_slug,
        "window": preset.window.value,
        "event_types": preset.event_types,
        "event_count": preset.event_count,
        "render_format": preset.render_format,
        "theme": preset.theme or DEFAULT_THEME,
        "intensity": preset.intensity,
        "targets": preset.targets,
    }


def _run_generation(*, preview_all_themes: bool = False, **kwargs: object) -> None:
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
        return
    except Exception as exc:  # surface unexpected failures in the UI
        status.update(label="Generation failed.", state="error")
        st.exception(exc)
        return

    if preview_all_themes:
        # Stream a preview per theme, filling the grid live as each completes.
        _run_theme_previews(draft, list(THEMES.keys()))
    else:
        st.rerun()


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

    _render_theme_gallery(draft)
    _render_publish(draft)

    st.caption(f"Draft `{draft.id}` · {len(draft.events)} events · status: {draft.status.value}")


# Number of theme previews shown per row (the page uses the wide layout).
_GALLERY_COLS = 3


def _render_theme_gallery(draft: PostDraft) -> None:
    """Compare themes: render one preview per theme, then pick the final one.

    Content is already finalized on the draft, so this only re-renders the look
    (fonts/colors/scrim) per theme — captions/background/music are reused. Each
    preview appears the moment its render finishes.
    """
    st.markdown("### Compare themes")
    st.caption(
        "Finalize your caption above first, then render a preview per theme and "
        "pick the one you want to publish."
    )
    chosen_themes = st.multiselect(
        "Themes to preview",
        list(THEMES.keys()),
        default=list(THEMES.keys()),
        format_func=lambda t: f"{t} — {THEMES[t].description}",
        key=f"gallery_themes_{draft.id}",
    )
    if st.button(
        "Render theme previews", key=f"gallery_run_{draft.id}", disabled=not chosen_themes
    ):
        _run_theme_previews(draft, chosen_themes)
        return  # _run_theme_previews reruns once done

    if not draft.theme_previews:
        return

    st.write(f"Selected theme: **{draft.theme or '—'}**")
    items = [(n, p) for n, p in draft.theme_previews.items() if Path(p).exists()]
    for row_start in range(0, len(items), _GALLERY_COLS):
        cols = st.columns(_GALLERY_COLS)
        row = items[row_start : row_start + _GALLERY_COLS]
        for col, (name, path) in zip(cols, row, strict=False):
            with col:
                _preview_cell(draft, name, path, interactive=True)


def _preview_cell(draft: PostDraft, name: str, path: str, *, interactive: bool) -> None:
    """Render one theme's video + a select button into the current container."""
    is_selected = name == draft.theme
    st.markdown(f"{'✅ ' if is_selected else ''}**{name}**")
    st.video(path)
    if not interactive:
        return
    if st.button(
        "Use this theme" if not is_selected else "Selected",
        key=f"pick_{name}_{draft.id}",
        disabled=is_selected,
        type="primary" if not is_selected else "secondary",
        use_container_width=True,
    ):
        pipeline.select_theme(draft, name, storage=_storage())
        st.rerun()


def _run_theme_previews(draft: PostDraft, themes: list[str]) -> None:
    """Render each theme one at a time, showing each preview as it completes."""
    storage = _storage()
    status = st.status(f"Rendering {len(themes)} theme preview(s)…", expanded=True)

    # Pre-lay a grid of placeholders so each preview can appear in place, live.
    st.write("Previews (appear as each finishes):")
    slots: dict[str, Any] = {}
    for row_start in range(0, len(themes), _GALLERY_COLS):
        cols = st.columns(_GALLERY_COLS)
        for col, name in zip(cols, themes[row_start : row_start + _GALLERY_COLS], strict=False):
            with col:
                st.markdown(f"**{name}**")
                slots[name] = st.empty()
                slots[name].info("⏳ rendering…")

    try:
        for name in themes:
            status.write(f"Rendering '{name}'…")
            # Render just this theme; the pipeline appends it and persists.
            pipeline.render_theme_previews(draft, themes=[name], storage=storage)
            path = draft.theme_previews.get(name)
            if path and Path(path).exists():
                slots[name].video(path)  # fill the placeholder immediately
        status.update(label="Theme previews ready.", state="complete")
        st.rerun()  # final rerun renders the interactive gallery with select buttons
    except pipeline.PipelineError as exc:
        status.update(label="Could not render previews.", state="error")
        st.warning(str(exc))
    except Exception as exc:  # surface unexpected render failures
        status.update(label="Preview render failed.", state="error")
        st.exception(exc)


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
    "Schedules": page_schedules,
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
