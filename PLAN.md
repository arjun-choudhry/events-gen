# Events-Gen — Project Plan

An app that discovers upcoming events for a given city (this week / this month),
generates a short **video** showcasing them (city background + event cards + music),
writes captions with an LLM, and — on your approval — publishes to a **YouTube channel**
and an **Instagram** account. Controlled from a **Streamlit** UI.

---

## 1. Decisions (locked)

| Area | Decision |
|------|----------|
| **Language** | Python 3.11+ |
| **Data sourcing** | **Hybrid** — event APIs (Ticketmaster, Eventbrite, PredictHQ, SeatGeek, Meetup) as backbone + pluggable scraper for *public* (non-login) city event pages |
| **Post format** | **Video for both** — rendered slideshow video → YouTube video/Short + Instagram Reel |
| **UI** | **Streamlit** (local web app) |
| **Text/captions** | **Anthropic Claude** (titles, captions, hashtags) |
| **Images** | AI-generated backgrounds behind a **provider-agnostic interface** (config-selectable); manual upload overrides |
| **Instagram publishing** | **Official Instagram Graph API** (Business/Creator account + linked FB Page) |
| **YouTube publishing** | **YouTube Data API v3** (OAuth) |
| **Automation** | **Review-then-publish by default**, with an **optional toggleable scheduler** per city/cadence |
| **Music** | Per-event-type default library + user override upload; must be licensed/royalty-free |

---

## 2. User-facing controls (requirements traceability)

Each control maps to the milestone that delivers it.

| # | Control | Delivered in |
|---|---------|--------------|
| R1 | Pick **city** from a managed world-city list (easily extensible) | M1, M5 |
| R2 | Pick **time window**: this week / this month (custom range optional) | M2, M5 |
| R3 | Pick **event type(s)** (music, sports, arts, food, tech, nightlife, family…) | M1, M2, M5 |
| R4 | Toggle **number of events** in a post (slider 3–15) | M2, M5 |
| R5 | Choose **background image** (upload) OR default AI-generated city image | M3, M5 |
| R6 | Choose **music** (upload) OR default track per event type | M3, M4, M5 |
| R7 | **Preview** video + caption before publishing | M4, M5 |
| R8 | Choose destination(s): **YouTube**, **Instagram**, or both | M5, M6 |
| R9 | **Publish** per post + optional **scheduler** toggle | M6, M7 |
| R10 | Save/load **city presets** (default image, music, types, count) | M5 |

---

## 3. Architecture

```
events-gen/
├── PLAN.md
├── README.md
├── pyproject.toml
├── .env.example                 # all API keys & secrets (never committed)
├── config/
│   ├── settings.py              # pydantic-settings: env + defaults
│   ├── cities.yaml              # city registry (name, country, coords, default assets)
│   └── event_types.yaml         # event taxonomy + default music mapping
├── assets/
│   ├── images/<city>/           # curated/generated default backgrounds
│   ├── music/<event_type>/      # default royalty-free tracks
│   └── fonts/
├── data/
│   ├── cache/                   # cached API responses
│   └── events_gen.db            # SQLite: drafts, jobs, publish history, schedules
├── src/events_gen/
│   ├── models.py                # Event, PostDraft, Job, Schedule
│   ├── sources/                 # EventSource interface + API/scraper impls + aggregator
│   ├── content/                 # captions (Claude), images (provider iface), music
│   ├── render/                  # cards (Pillow) + video (MoviePy/FFmpeg) + formats
│   ├── publish/                 # Publisher iface + youtube + instagram
│   ├── pipeline.py              # fetch -> select -> render -> draft
│   ├── scheduler.py             # APScheduler jobs (toggleable)
│   ├── storage.py               # SQLite persistence
│   └── ui/app.py                # Streamlit app
└── tests/
```

### Data flow
```
[Streamlit UI]
  -> pipeline.run(city, window, types, count, image?, music?)
      -> aggregator: fetch enabled APIs (+scraper) -> normalize -> dedupe -> rank -> top N
      -> captions (Claude) + images (AI or upload) + music (default or upload)
      -> render.video -> mp4 (per target aspect ratio)
      -> storage: save PostDraft (status=draft)
  -> UI preview
  -> publish.youtube / publish.instagram (on click) OR scheduler (if enabled)
  -> storage: record result + external post IDs
```

---

## 4. Tech stack

- **UI:** Streamlit
- **Video:** MoviePy + FFmpeg; Pillow for card/text composition
- **HTTP/APIs:** httpx, tenacity (retries/backoff)
- **Scraping:** httpx + selectolax/BeautifulSoup; Playwright only if JS needed (respect robots.txt)
- **LLM:** `anthropic` SDK (Claude, latest model)
- **Images:** provider-agnostic interface; mock provider for dev
- **Publishing:** `google-api-python-client` + `google-auth-oauthlib` (YouTube); httpx (Instagram Graph API)
- **Persistence:** SQLite (SQLModel or sqlite3)
- **Scheduling:** APScheduler
- **Config/secrets:** pydantic-settings + `.env`
- **Quality:** pytest, ruff, mypy

---

## 5. Milestones

Legend: `[ ]` todo · `[~]` in progress · `[x]` done. Each milestone lists **sub-milestones**,
its **deliverable**, and **acceptance criteria** (how we know it's done).

---

### M0 — Project scaffolding & foundations
**Goal:** a runnable skeleton with config, models, and persistence — no external keys required.

- [x] **M0.1** Repo layout per §3; `pyproject.toml` with deps; `ruff` + `mypy` + `pytest` configured
- [x] **M0.2** `.env.example` enumerating every secret; `.gitignore` (env, db, cache, assets output)
- [x] **M0.3** `src/events_gen/settings.py` (pydantic-settings) loading env + sane defaults
- [x] **M0.4** `config/cities.yaml` (seed 5 cities) + `config/event_types.yaml` (taxonomy + music map)
- [x] **M0.5** `models.py` — `Event`, `PostDraft`, `Job`, `Schedule` (typed)
- [x] **M0.6** `storage.py` — SQLite schema + CRUD for drafts/jobs/history/schedules
- [x] **M0.7** `README.md` skeleton + `scripts/` for lint/test/run + `scripts/smoke.py` (M0 runnable check)
- [x] **M0.8** **Update README** — document setup, layout, how to run lint/test, and **how to run/try the M0 features** (see README "Trying it out per milestone")

**Deliverable:** `pip install -e .` works; `pytest` green on model/storage tests.
**Acceptance:** create → read → update a `PostDraft` in SQLite via `storage.py` in a test.

---

### M1 — City & event-type registry
**Goal:** manage the catalog of cities and event types the app operates on. *(R1, R3)*

- [x] **M1.1** City registry loader (name, country, coords, timezone, default asset paths) — `registry.load_cities`
- [x] **M1.2** Event-type taxonomy loader + validation — `registry.load_event_types`
- [x] **M1.3** Helper to add a new city (writes `cities.yaml` + asset folders) — `registry.add_city` + `cli.py`
- [x] **M1.4** Unit tests for loaders + add-city helper (14 tests)
- [x] **M1.5** **Update README** — documented config format, how to add a city, and runnable M1 CLI steps

**Deliverable:** programmatic access to cities/types used by pipeline + UI.
**Acceptance:** adding a city via helper makes it selectable everywhere without code changes.

---

### M2 — Data sourcing (event discovery)
**Goal:** fetch, normalize, dedupe, and rank events for a city/window/type. *(R2, R3, R4)*

- [x] **M2.1** `sources/base.py` — `EventSource` interface + `safe_fetch` (failure isolation) → `list[Event]`
- [x] **M2.2** First API source: **Ticketmaster** (auth, geo+date+category query, pagination) — via shared `http_api.ApiEventSource`
- [x] **M2.3** Second API source: **Eventbrite**
- [x] **M2.4** Response **caching** layer (`sources/cache.py`, `data/cache/`) with TTL
- [x] **M2.5** `aggregator.py` — merge sources, **dedupe** (richest-wins), window filter, **rank**, top-N
- [x] **M2.6** Time-window helper (`timewindow.py`) — week/month/custom, tz-aware, anchored to now
- [x] **M2.7** Generic public-page **scraper** (`scraper.py`), robots.txt-aware, JSON-LD, isolated/optional
- [ ] **M2.8** Additional API sources (PredictHQ, SeatGeek, Meetup) — *deferred (incremental; interface + config hints ready)*
- [x] **M2.9** Tests: dedupe, ranking, window filter, source failure isolation, parsing, cache (30 new tests)
- [x] **M2.10** **Update README** — documented sources, keys, caching, sourcing model, and runnable `fetch` CLI steps
- [x] **Extra** `MockSource` — deterministic keyless source so the pipeline runs end-to-end in dev/demo; `cli fetch` command

**Deliverable:** `aggregator.fetch(city, window, types, count) -> list[Event]`.
**Acceptance:** given a city, returns a deduped, ranked, correctly-sized list from ≥2 live sources; one source failing does not break the result.

---

### M3 — Content generation
**Goal:** produce captions, background images, and music selection for a post. *(R5, R6)*

- [x] **M3.1** `captions.py` (Claude via `messages.parse` + Pydantic schema) — title, caption, hashtags; deterministic template fallback when no key
- [x] **M3.2** `content/images/base.py` — `ImageProvider` interface
- [x] **M3.3** `mock_provider.py` — deterministic Pillow gradient placeholder (dev, no keys)
- [x] **M3.4** `ai_provider.py` — config-selected AI provider stub (raises until an API is wired; factory falls back to mock)
- [x] **M3.5** Image override path — `resolve_background` (upload → city default → generated), cover-fit resize
- [x] **M3.6** `music.py` — `resolve_music` (upload → dominant-type default → city default → silent)
- [x] **M3.7** Tests: captions, provider selection/fallback, upload validation, R5/R6 override rules, builder (16 new)
- [x] **M3.8** **Update README** — documented caption/image/music config + provider selection + runnable `generate-content` steps
- [x] **Extra** `builder.build_content` (assembles `PostContent`) + `cli generate-content` command

**Deliverable:** for a set of events → `{title, caption, hashtags, background_image, music_track}`.
**Acceptance:** pipeline produces valid content bundle with mock providers (no paid keys) and with real providers when keys present.

---

### M4 — Video rendering
**Goal:** compose the final video from content + events. *(R6, R7)*

- [x] **M4.1** `cards.py` (Pillow) — per-event card (name, date, venue, price); word-wrap, format-relative sizing
- [x] **M4.2** `formats.py` — presets: 9:16 `reel` (Reel/Short), 16:9 `landscape` (YouTube); configurable pacing
- [x] **M4.3** `video.py` (MoviePy 2.x) — background + fade-in/out overlay cards + music → mp4
- [x] **M4.4** Duration/pacing logic scaled to number of events (intro + N×seconds_per_card + outro)
- [x] **M4.5** Music mixing (fade in/out via AudioFadeIn/Out, trim to video length)
- [x] **M4.6** Render smoke tests (22 new tests): cards, formats, video output, music mux, pacing
- [x] **M4.7** **Update README** — documented FFmpeg dependency, formats, render CLI, and runnable steps to try M4

**Deliverable:** `render.video(content, events, fmt) -> path/to.mp4`.
**Acceptance:** produces a playable mp4 in both aspect ratios with music and readable cards.

---

### M5 — Streamlit UI (control + preview + drafts)
**Goal:** the operator console wiring all controls to the pipeline. *(R1–R8, R10)*

- [x] **M5.1** App shell + navigation (Create / Drafts / History / Settings) — `ui/app.py` sidebar
- [x] **M5.2** Controls: city (R1), window (R2), event types (R3), count slider (R4)
- [x] **M5.3** Asset controls: background upload-or-default (R5), music upload-or-default (R6)
- [x] **M5.4** "Generate" → runs `pipeline.run`, shows progress (via `st.status` + progress callback)
- [x] **M5.5** **Preview**: video player + editable caption/hashtags (R7)
- [x] **M5.6** Destination selector: YouTube / Instagram / both (R8)
- [x] **M5.7** **City presets** save/load (R10) — `CityPreset` model + storage CRUD + UI
- [x] **M5.8** Drafts list (saved `PostDraft`s) with re-open/preview/edit/delete
- [x] **M5.9** **Update README** — documented UI launch, operator workflow, and runnable M5 steps
- [x] **Extra** `pipeline.py` — the fetch→content→render→draft orchestrator the UI (and later scheduler) call

**Deliverable:** end-to-end draft creation + preview from the browser.
**Acceptance:** from a fresh start, user sets controls → generates → previews → saves a draft, all in UI.

---

### M6 — Publishing
**Goal:** push approved drafts to YouTube and Instagram. *(R8, R9)*

- [x] **M6.1** `publish/base.py` — `Publisher` interface + `safe_publish` (failure isolation) + dry-run contract
- [x] **M6.2** `youtube.py` — OAuth installed-app flow, resumable upload, title/description/tags/visibility
- [x] **M6.3** Video **hosting helper** (`hosting.py`) — maps a local mp4 to a public URL (required by IG)
- [x] **M6.4** `instagram.py` — create media container (Reel) → poll status → publish
- [ ] **M6.5** Instagram image/carousel path (fallback format) — *deferred (Reel path complete; carousel is incremental)*
- [x] **M6.6** Persist publish results + external post IDs to history (draft.results + `publish` Job)
- [x] **M6.7** UI **Publish** buttons wired per destination with dry-run toggle + success/error surfacing
- [x] **M6.8** Tests/mocks for both publisher clients (20 new; IG two-step flow via httpx MockTransport)
- [x] **M6.9** **Update README** — documented credential setup, publish flow, and runnable dry-run→live steps
- [x] **Extra** `publish_draft` orchestrator + `cli publish` command (dry-run by default, `--live` to go real)

**Deliverable:** one-click publish of a draft to selected destination(s).
**Acceptance:** a draft publishes to YouTube (real/sandbox) and IG container flow completes; result + IDs stored and shown.

---

### M7 — Automation & scheduling (optional, toggleable)
**Goal:** hands-off recurring runs, off by default. *(R9)*

- [x] **M7.1** `scheduler.py` (APScheduler) — `run_schedule` core + `SchedulerService` weekly/monthly cron per city
- [x] **M7.2** Schedules persisted in storage; `SchedulerService` reconstructs jobs from storage on start → survives restart
- [x] **M7.3** UI Schedules page: per-city/cadence create, enable toggle, review-required vs auto-publish switch, Run now/Delete
- [x] **M7.4** Run-log view in UI History page (every `Job` incl. `scheduled_run`, as a table)
- [x] **M7.5** Guardrails: skip (not fail) when no events; catch+record any error so a bad run never kills the scheduler; publish failure isolated per destination
- [x] **M7.6** **Update README** — documented scheduler model, management, guardrails, and runnable M7 steps
- [x] **Extra** `cli schedule` (add/list/run) for headless management + on-demand triggering

**Deliverable:** enable a city schedule → auto-generates (and optionally auto-publishes).
**Acceptance:** a scheduled job produces a draft (or publishes) at the configured time; visible in history.

---

### M8 — Hardening, docs, and release
**Goal:** robust, documented, credential-ready.

- [x] **M8.1** Retries/backoff (tenacity) + rate-limit handling — API sources (existing) + shared `publish/_http.py` wrapping Instagram (429/5xx/transport retried, other 4xx fail fast)
- [x] **M8.2** Error surfacing in UI — pipeline/publish/source errors shown via `safe_fetch`/`safe_publish` + `st.status`/`st.warning`/`st.exception`
- [x] **M8.3** Quota/token-expiry handling — YouTube maps 403 quota / 401 auth / `RefreshError` to actionable re-auth messages
- [x] **M8.4** Test coverage — 142 tests across aggregator, captions, render smoke, publisher mocks, scheduler, retry helper
- [x] **M8.5** `README.md` — setup + per-feature credential walkthrough + a credentials checklist table
- [x] **M8.6** Sample `.env` (complete), seed cities (5), and a **demo dry-run mode** (`cli demo` — full pipeline + dry-run publish, no keys)
- [x] **M8.7** **Update README** — quickstart (demo + UI), troubleshooting section, status refreshed; per-milestone steps verified end-to-end

**Deliverable:** a documented app another person could set up from README.
**Acceptance:** clean checkout → follow README → produce and (dry-run) publish a post.

---

## Phase 2 — "publish-ready" upgrades (M9–M14, planned)

> Backlog captured 2026-07-06; detailed plan 2026-07-06. M0–M8 are complete and
> live YouTube publishing works; these milestones target the gap between "it works"
> and "I'd publish this straight away." Not yet started — pick up from here.
> Ordering is roughly by impact on video quality.

---

### M9 — Sharper, higher-quality visuals
**Goal:** eliminate pixelation so backgrounds + cards look crisp on both phone and desktop. Render quality is **selectable** per video (1080p vs 4K).

**Root causes to fix:**
- Source images (Openverse Flickr thumbnails, Unsplash `regular`) are often < 1080×1920 → upscaling blur.
- x264 encode uses MoviePy's default (high CRF ≈ low quality).
- Resize algorithm is whatever Pillow defaults (not LANCZOS).

- [x] **M9.1** Image source upgrades — Unsplash now requests `raw&w=2160&h=3840&fit=crop&q=80` (was `regular`); Openverse already uses `url`. Added a minimum-resolution filter in `resize.is_large_enough`: images < 70% of target dimensions trigger blur-fill instead of being upscaled.
- [x] **M9.2** `Image.LANCZOS` everywhere — new shared `content/images/resize.py` with `cover_fit` + `resize_for_target` using LANCZOS; updated `venue.py`, `__init__._prepare_upload`, and `video._load_background` to use it. Never upscales beyond 1.25×.
- [x] **M9.3** Blur-fill fallback — `resize.blur_fill` generates a zoomed+GaussianBlur(25) backdrop, overlays the sharp (smaller) image centered (capped at `_MAX_UPSCALE`). Auto-triggered when the source is below the resolution gate.
- [x] **M9.4** 4K formats — added `REEL_4K` (2160×3840) and `LANDSCAPE_4K` (3840×2160) presets in `formats.py`. Selectable in the UI format dropdown and CLI `--format reel_4k`.
- [x] **M9.5** x264 encode quality — `write_videofile` now passes `ffmpeg_params=["-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"]`. `EG_RENDER_CRF` (default 18) exposed in settings + `.env.example`.
- [x] **M9.6** Card text supersampling — `render_card(..., supersample=2)` renders at 2× resolution then downscales with LANCZOS for sub-pixel-smooth text edges.
- [x] **M9.7** Tests — 14 new: resolution gate, cover_fit, blur-fill (size + center-pixel), resize dispatch, resize_bytes, 4K format dimensions, 4K render + ffprobe assertion, CRF size assertion.
- [x] **M9.8** **Update README** — (next step, below).

**Deliverable:** visibly crisp output at 1080p and 4K, selectable per render.
**Acceptance:** (a) a 1080p render using an Openverse image shows no upscaling blur on phone; (b) a 4K render produces a 3840×2160 file with CRF 18 and looks sharp on a desktop monitor.

---

### M10 — Better event ranking + interactive manual picker
**Goal:** stop surfacing boring events; give the operator full control over which events appear, with a **live-updating preview** as events are toggled. *(addresses "curated events are boring")*

- [x] **M10.1** Fetch-first flow — Create page split into Fetch → Pick → Generate. Fetch calls `aggregator.fetch(..., count=30)` → stores candidates in session state → picker appears.
- [x] **M10.2** **Interactive event picker** — grid of all candidates with ☑ checkbox, title+type, date, venue, price. "Select top N" / "Select all" / "Clear all" action buttons.
- [x] **M10.3** Live lightweight preview — selected count + estimated duration + horizontal thumbnail strip (event images) updates on every toggle.
- [x] **M10.4** Sort-by control — horizontal radio: Popularity / Date / Price / Name. Re-orders the grid instantly.
- [ ] **M10.5** Better ranking signals from sources — Ticketmaster `attractions[0].upcomingEvents._total` (popularity proxy), SeatGeek `score` / `stats.listing_count`, PredictHQ `rank`/`phq_attendance`. Map each into `Event.rank_score`; the picker's default sort uses this.
- [ ] **M10.6** Additional event sources (deferred M2.8) — SeatGeek, PredictHQ, Meetup. Each new source adds more candidates to the pool and brings its own popularity signal.
- [ ] **M10.7** LLM "interestingness" scorer (optional toggle) — ask Gemini to rate each candidate's shareability (1–10) from its metadata. Cached per event id so it's not re-called. Adds to the composite `rank_score`. Keyless-degradable (off if no LLM key).
- [x] **M10.8** "Select top N" button — auto-checks the first N by current sort. Also "Select all" / "Clear all".
- [x] **M10.9** Tests — 15 new: picker sort (4 criteria + unknown key), select_top_n (3 cases), estimate_duration (2), is_fetch_stale (3), pipeline preselected events (skip fetch + empty raises). Pipeline backward-compatible (no events param → fetches normally).
- [x] **M10.10** **Update README** — documented fetch→pick→generate flow, picker columns, sort options, Quick Generate fallback.
- [x] **Extra** `pipeline.run(events=[...])` accepts pre-selected events, skipping fetch — enables both the picker flow and programmatic curation.
- [x] **Extra** `src/events_gen/ui/picker.py` — pure testable helpers (no Streamlit deps): sort, select, duration estimate, stale detection.

**Deliverable:** an interactive picker with live preview, backed by richer ranking + new sources.
**Acceptance:** fetch 30 candidates → use the picker to hand-select 5 → the video contains exactly those 5; the timeline preview updates live.

---

### M11 — Scale to many cities (type-in, multi-select, favorites, combined roundup)
**Goal:** make many-city operation effortless — type any city, batch-generate for several, and save a favorites set that persists. Also support an optional **combined multi-city roundup video** alongside per-city ones.

- [x] **M11.1** **Geocoded type-in** — `ui/geocoding.py` using geopy Nominatim + timezonefinder (both keyless). Type a city name → geocode → add to registry on the fly. Live-verified (Paris → FR/Europe/Paris/48.86,2.32).
- [x] **M11.2** **Multi-city select** — replaced single selectbox with `st.multiselect`; first selected city used for the picker flow (batch generation for multi-city in progress).
- [x] **M11.3** **Favorites** — `favorites` SQLite table + CRUD (`save_favorite`/`remove_favorite`/`list_favorites`). UI: ⭐ chip row above the multiselect + toggle checkboxes. Persist across sessions.
- [ ] **M11.4** Batch-generation UX — *deferred (loop per city with per-city progress when >1 city selected).*
- [ ] **M11.5** Combined roundup UI toggle — *deferred (the pipeline function exists; UI integration pending).*
- [x] **M11.6** Roundup pipeline — `pipeline.run_roundup(city_slugs, events_per_city=1)` fetches top event per city, merges, renders one combined video. Tested.
- [x] **M11.7** Seeded **25 cities** (was 5) covering all continents.
- [ ] **M11.8** CLI batch/favorites commands — *deferred (incremental).*
- [x] **M11.9** Tests — 9 new: geocode (known city, garbage, slug format), favorites (add/list/idempotent/remove/empty), roundup (combined draft, empty raises).
- [x] **M11.10** **Update README** — documented type-in, multi-city select, favorites, roundup.

**Deliverable:** type any city, multi-select with favorites, batch-generate, optional combined roundup.
**Acceptance:** type 3 new cities → mark as favorites → next session one-click favorites → generates 3 per-city drafts + 1 combined roundup.

---

### M12 — Catchier, more clickable videos (animation presets)
**Goal:** make renders eye-catching and view-optimized. Two selectable animation styles: **"hype"** (TikTok/Reels-native: fast cuts, zoom, text pop) and **"cinematic"** (polished Ken Burns, smooth reveals). Existing static themes remain as a third "none" option.

- [x] **M12.1** Animation preset model — `AnimationPreset` dataclass in `render/animations.py` with bg_zoom, card_enter, hook config. Registry: `ANIMATIONS = {"none", "hype", "cinematic"}`.
- [x] **M12.2** Background motion (Ken Burns zoom) — `_make_ken_burns_clip` renders an oversized background and crops a progressively-zoomed region per frame. "hype" = 1.0→1.12×; "cinematic" = 1.0→1.04×.
- [x] **M12.3** Card entrance transitions — `_overlay_clip` accepts animation; "hype" = slide-up from 15% below with ease-out; "cinematic" = slow fade (0.6s); "none" = current fade. Fade-out on exit for all.
- [ ] **M12.4** Kinetic text reveal — *deferred* (per-word animation requires frame-by-frame text rendering; significant additional complexity).
- [ ] **M12.5** Countdown numbers — *deferred*.
- [x] **M12.6** Hook intro — big text overlay at the start ("🔥 TOP {n} IN {city} 🔥" for hype, elegant "{city} — {n} events" for cinematic). Adds 1.5–2s to the video duration.
- [ ] **M12.7** Beat-synced pacing (optional, if music present) — analyze the track's BPM/onsets (librosa or aubio); snap card transitions to beats. Falls back to fixed `seconds_per_card` if no music or analysis fails. Add `librosa` as an optional dep.
- [ ] **M12.8** LLM-generated scroll-stopping hooks — ask Gemini for 3 hook variants optimized for CTR; display in the UI for the operator to pick one; the winner becomes the intro text. Also generates thumbnail text (short, high-contrast, emoji-heavy).
- [ ] **M12.9** Thumbnail generation — render a 1280×720 JPEG (YouTube standard) with big text + the best venue image, auto-set on YouTube upload (`snippet.thumbnails`). UI shows a thumbnail preview.
- [x] **M12.10** Wire into pipeline + themes — `pipeline.run(animation=...)` → `render_video(animation=...)`. UI has a horizontal radio (None/Hype/Cinematic) separate from the visual theme.
- [x] **M12.11** UI integration — animation radio in the Create page; gen_kwargs passes it through to render.
- [x] **M12.12** Tests — 15 new: registry (3 presets, fallback), Ken Burns frame (size, start≠end), slide-up position (start/arrive/stay), render (each preset produces video, hype longer than none, combo with theme).
- [x] **M12.13** **Update README** — documented animation presets, CLI usage, UI control.

**Deliverable:** two animation presets (hype + cinematic), hook intro, kinetic text, optional beat-sync, thumbnail.
**Acceptance:** render "hype" and "cinematic" side-by-side — both visibly more dynamic than the current static version; hook grabs attention in the first second; thumbnail is auto-set on YouTube.

---

### M13 — Per-city destinations (Instagram + multiple YouTube channels)
**Goal:** route each city's video to its own accounts. One city can publish to **1+ YouTube channels** and **its own Instagram account** — all managed in the UI.

- [x] **M13.1** Destination model — `Destination` (id, city_slug, platform, label, yt_secrets_path/token_path, ig_token/account_id). Stored in `destinations` table.
- [ ] **M13.2** Destination management UI — *deferred (CRUD ready; UI page for add/remove pending).*
- [x] **M13.3** Multi-channel YouTube — `YouTubePublisher(destination=...)` loads per-destination credentials from `secrets/<dest_id>/`. Falls back to global settings when no destination.
- [x] **M13.4** Per-city Instagram — `InstagramPublisher(destination=...)` uses per-destination token/account_id. Same fallback.
- [x] **M13.5** Publish routing — `publish_draft(draft, destinations=[...])` iterates destinations, creates per-destination publishers, records `destination_id` on each `PublishResult`. Falls back to global targets when no destinations passed. Backward compatible.
- [ ] **M13.6** Default destinations auto-fill on publish — *deferred (needs M13.2 UI first).*
- [x] **M13.7** Credential layout — `secrets/<dest_id>/youtube_client_secret.json` + `youtube_token.json`. IG tokens stored directly on the Destination model (not files). `.gitignore` covers `secrets/`.
- [x] **M13.8** Migration — global `.env` credentials remain as the fallback (no destination configured → global). Zero breaking changes.
- [x] **M13.9** Tests — 7 new: storage CRUD (save/list-by-city/delete), publish routing (dry-run per-destination, results tracked, fallback to global, multi-YT destinations).
- [x] **M13.10** **Update README** — *(below).*

**Deliverable:** one draft → published to all of a city's configured channels/accounts.
**Acceptance:** configure city X with 2 YouTube channels + 1 Instagram → publish → all three receive the video, each tracked independently in history.

---

### M14 — Straight-to-publish polish (ties everything together)
**Goal:** close the remaining gaps so "generate → publish" needs zero manual cleanup. The end-state: **one button → favorites → generated → published.**

- [x] **M14.1** Configurable YouTube visibility — `EG_YOUTUBE_PRIVACY` (default `unlisted`). `YouTubePublisher` reads from settings; explicit param overrides. Added to `.env.example`.
- [ ] **M14.2** Live Instagram publishing — *deferred (needs a real Business account + public video host to verify end-to-end).*
- [x] **M14.3** Pre-publish validation — `validate_draft()` checks: video exists, caption ≤ 2200 (IG) / 5000 (YT), hashtags ≤ 30 (IG). Returns issue list; UI blocks on critical. Exported from `publish` package.
- [x] **M14.4** One-click "Publish favorites" — sidebar button loads favorites → finds latest ready draft per city → validates → dry-run publishes. Shows per-city success/fail inline.
- [ ] **M14.5** Post-publish confirmation — *deferred (URLs already shown in publish results; oEmbed/analytics is polish).*
- [ ] **M14.6** Scheduling + per-city destinations — *deferred (incremental).*
- [x] **M14.7** Tests — 9 new: validation (valid, no-video, missing-file, no-content, caption-too-long, too-many-hashtags) + YouTube privacy (default unlisted, settings override, explicit override).
- [x] **M14.8** **Update README** — *(below).*

**Deliverable:** one button → all favorite cities' videos generated and published to their destinations.
**Acceptance:** press "Publish favorites" → 3 cities × (2 YT channels + 1 IG each) = 9 successful publishes, all tracked in history with live URLs.

---

### Phase 2 dependency graph

```
M9 (visuals) ─────────────────┐
                               ├──> M14 (polish, ties it all together)
M10 (picker + ranking) ────────┤
                               │
M11 (multi-city + favorites) ──┤
                               │
M12 (animations + hooks) ──────┤
                               │
M13 (per-city destinations) ───┘
```

M9–M13 are independently startable (no hard dependencies between them).
M14 integrates them and is the final polish pass. Recommended order of
attack for maximum impact: **M9 → M10 → M12 → M11 → M13 → M14**.

---

## 6. External accounts & credentials (setup checklist)

- [ ] **Anthropic API key** (captions)
- [ ] **AI image provider** key (chosen at config time)
- [ ] **Event APIs**: Ticketmaster, Eventbrite, PredictHQ, SeatGeek, Meetup
- [ ] **YouTube**: Google Cloud project → enable YouTube Data API v3 → OAuth client → authorize channel
- [ ] **Instagram**: convert to Business/Creator, link a Facebook Page, create Meta app, enable Instagram Graph API, generate long-lived token
- [ ] **Music**: royalty-free library placed in `assets/music/`

> **Instagram note:** publishing is 2-step — create a **media container** (needs a public video URL for Reels) then **publish**. M6.3 delivers the hosting helper for this.
>
> **Status:** the code supports every credential above and degrades gracefully without them (keyless dev + dry-run). The boxes stay unchecked because they track the *operator* obtaining live accounts/keys, which is deployment-time, not code work.

---

## 7. Dependencies between milestones

```
M0 ─┬─> M1 ─┐
    │       ├─> M2 ─┐
    │       │       ├─> M3 ─> M4 ─┐
    │       │       │             ├─> M5 ─> M6 ─> M7
    │       │       │             │
    └───────┴───────┴─────────────┘   (M5 needs M1–M4; M6 needs M5; M7 needs M6)
M8 spans all (hardening applied continuously, finalized last).
```
Critical path: **M0 → M2 → M3 → M4 → M5 → M6**. M1 parallels M2. M7 and M8 come last.

---

## 8. Key risks & mitigations

- **Scraping fragility / ToS** → APIs primary; scraper limited to public, robots-allowed pages; isolated so failures don't break pipeline (M2.7).
- **Instagram video hosting requirement** → M6.3 hosting helper delivers the public URL.
- **API cost/latency (LLM + images)** → caching (M2.4), mock providers in dev (M3.3), batching.
- **Music licensing** → royalty-free defaults only; user uploads are user's responsibility (surfaced in UI).
- **OAuth token expiry** → long-lived tokens + refresh; clear re-auth prompts (M8.3).
- **Rate limits (IG ~25–50 posts/24h, YouTube quota)** → throttle + surface remaining quota (M7.5, M8.1).

---

## 9. Open items to confirm later (non-blocking)

- [ ] Which specific AI image provider to wire into `ai_provider.py` (M3.4) — *note: per-event backgrounds now come from event promo images / Unsplash / Openverse (2026-07-06), reducing the need for generated art.*
- [ ] Full initial set of cities to seed `cities.yaml` (M0.4/M1)
- [ ] Where to host rendered videos for IG publish (bucket vs tunnel) (M6.3) — *still open; blocks live Instagram publishing.*
- [x] Preferred video style/branding — **resolved 2026-07-06**: 9 selectable themes (fonts/colors/scrim intensity) in `render/themes.py`; per-video choice with a compare-themes gallery.

---

## Progress log

- 2026-07-05 — Plan created; core decisions locked (§1). Restructured into milestones M0–M8 with sub-milestones, deliverables, and acceptance criteria.
- 2026-07-05 — Added "Update README" as the final sub-milestone of every milestone.
- 2026-07-05 — Each "Update README" step now also adds **runnable steps to try that milestone's feature**, collected in the README's "Trying it out per milestone" section.
- 2026-07-05 — **M0 complete.** Repo scaffolding, `pyproject.toml` (ruff/mypy/pytest), `.env.example` + `.gitignore`, `settings.py`, `cities.yaml` + `event_types.yaml`, `models.py`, `storage.py` (SQLite), README, and scripts. 16 tests pass; ruff + mypy clean. Acceptance met: PostDraft create→read→update verified in SQLite.
- 2026-07-05 — **M1 complete.** Added `City`/`EventType` models, `registry.py` (loaders + validation + `add_city`), and `cli.py` (`list-cities`, `list-types`, `add-city`). Made `config_dir`/`assets_dir` overridable in settings for isolation. 30 tests pass (14 new); ruff + mypy clean. Acceptance met: added São Paulo via CLI → appears in `list-cities` with asset folder created, no code changes.
- 2026-07-05 — **M3 complete.** Added `content/` (`captions` with Claude + template fallback, `images/` provider interface + mock + AI stub + `resolve_background`, `music.resolve_music`, `builder.build_content`) and `cli generate-content`. Keyless-first: template captions + Pillow placeholder background run with no API keys; Claude/AI activate when keys present. Added mypy overrides to skip 3.12-only third-party stubs (numpy/moviepy/PIL). 74 tests pass (16 new); ruff + mypy clean. Acceptance met: content bundle (title/caption/hashtags/background/music) produced with mock providers, verified via CLI + tests. Caption LLM path untested against live Claude API (no key yet) — verified structurally; `AIImageProvider.generate` intentionally unimplemented pending provider choice (PLAN §9).
- 2026-07-05 — **M2 complete.** Added `timewindow.py`, `sources/` (`base` + `http_api` + `cache` + `ticketmaster` + `eventbrite` + `scraper` + `mock` + `aggregator`), and `cli fetch`. Sources gate on config and isolate failures via `safe_fetch`; aggregator dedupes (richest-wins), window-filters, ranks, returns top-N. 58 tests pass (30 new); ruff + mypy clean. Acceptance met: `fetch` returns a deduped/ranked/sized list; a failing source is isolated (test-verified). M2.8 (extra APIs) deferred as incremental. Note: real APIs untested against live endpoints (no keys yet) — parsing verified with mocked HTTP payloads.
- 2026-07-05 — **M4 complete.** Added `render/` (`formats.py` with reel/landscape presets, `cards.py` with Pillow card rendering + word-wrap + price/venue, `video.py` with MoviePy 2.x composition — background + fade-in/out overlay cards + music fade/trim → h264 mp4). Added `cli render` command. Pinned moviepy>=2.0 in pyproject. 96 tests pass (22 new); ruff + mypy clean. Acceptance met: produces playable mp4 in both aspect ratios (1080×1920 reel, 1920×1080 landscape) with music mixing and readable event cards, verified via ffprobe + tests.
- 2026-07-05 — **M5 complete.** Added `pipeline.py` (fetch→content→render→draft orchestrator with progress callback), `CityPreset` model + storage CRUD (presets table), and the Streamlit console `ui/app.py` (Create/Drafts/History/Settings pages wiring R1–R8, R10). Keyless-first: the console runs end-to-end with mock sources + template captions. 104 tests pass (8 new: pipeline + presets); ruff + mypy clean; app boots headless (HTTP 200 verified). Acceptance met: controls → generate → preview → save draft, all in-browser. UI page bodies are exercised via import + headless boot rather than unit tests (Streamlit needs a running script context); pipeline core is unit-tested.
- 2026-07-05 — **M6 complete.** Added `publish/` (`base` Publisher iface + `safe_publish` isolation + dry-run, `hosting` public-URL helper, `youtube` OAuth+resumable upload, `instagram` two-step Reel flow, `publish_draft` orchestrator persisting results + history Job), UI Publish buttons (dry-run toggle + per-destination status), and `cli publish` (dry-run default, `--live`). Installed google-api-python-client/oauthlib; added mypy override for the untyped google libs. 124 tests pass (20 new; IG flow via httpx MockTransport); ruff + mypy clean; UI boots headless clean. Acceptance met: dry-run publishes to both destinations end-to-end (CLI + tests) with results/IDs stored on the draft and a `publish` job recorded; IG container flow verified against mocked Graph API. M6.5 (IG carousel fallback) deferred. Live paths (real YouTube OAuth upload, live Graph API) untested against real accounts (no credentials yet) — verified structurally + with mocks.
- 2026-07-05 — **M8 complete.** Hardening + release pass. Added `publish/_http.py` (tenacity retry wrapper: transport/5xx/429 retried, other 4xx fail fast) wired into the Instagram client (M8.1; API sources already had retry). YouTube maps 403 quota / 401 auth / `RefreshError` to actionable re-auth messages (M8.3). Added `cli demo` — full pipeline + dry-run publish with no keys (M8.6 capstone). README: refreshed status, quickstart (demo + UI), credentials checklist table, and a troubleshooting section (M8.5/M8.7). 142 tests pass (8 new: retry helper, IG retry integration, demo e2e); ruff + mypy clean. Acceptance met: clean checkout → `pip install -e .` → `events-gen demo` produces a video and dry-run publishes it end-to-end with zero configuration. §6 credential boxes remain unchecked by design (operator/deploy-time, not code); live API paths still unverified against real accounts.
- 2026-07-05 — **M7 complete.** Added `scheduler.py`: `run_schedule` (generate → optionally auto-publish → record a `scheduled_run` Job, never raises) + `SchedulerService` (APScheduler `BackgroundScheduler`, weekly=Mon 09:00 / monthly=1st 09:00 cron in the city tz). Schedules live in the `schedules` table; the service rebuilds its jobs from storage on `start`/`reload`, so it survives restart (M7.2) without relying on APScheduler's jobstore. Guardrails: no-events → skipped (success), any error → recorded failed job, publish failures isolated per destination. Added UI **Schedules** page (create/enable/auto-publish/Run now/delete) + run-log table on History, and `cli schedule add/list/run`. 134 tests pass (10 new); ruff + mypy clean; UI boots headless clean; CLI add→list→run verified. Acceptance met: a schedule's run produces a draft (or publishes) and is visible in history. Cron *firing* over wall-clock time not tested (would require waiting/mocking the clock); trigger construction + on-demand `run_schedule`/`trigger_now` are tested, and job reconstruction-from-storage (restart survival) is test-verified.

---

### 2026-07-06 — Post-M8 enhancements (all M0–M8 milestones already complete)

A day of feature enhancements and going **live** with real credentials. All changes landed on top of the completed M0–M8 baseline. End state: **194 tests pass; ruff + mypy clean; live YouTube publishing verified end-to-end.**

- **Free LLM captions (Gemini).** Made `captions.py` provider-pluggable: `EG_CAPTION_PROVIDER` (`auto`|`gemini`|`anthropic`) with `_select_provider` preferring free **Gemini** (`GEMINI_API_KEY`, `google-genai`) over paid Anthropic, template fallback on any error. Live-verified with a real key. Fixed the free-tier `429` by switching the default model to `gemini-2.5-flash` (the `2.0-flash` free tier is disabled on new keys).
- **`.env` loading bug fixed (important).** `env_file` was relative, so `.env` only loaded when launched from the repo root — silently dropping *every* key (Gemini, Jamendo, event APIs) elsewhere. Changed to an absolute `REPO_ROOT / ".env"`; keys now load from any working directory.
- **Smart backgrounds (per-event venue images).** New `content/images/venue.py`: per event, resolve a background of *where it's happening* — event promo image → **Unsplash** (`UNSPLASH_ACCESS_KEY`) → **Openverse** (keyless, CC-licensed — works out of the box) → shared city background. Renderer now layers per-event background segments; `PostContent.event_backgrounds` carries them. UI toggle + `pipeline.run(smart_backgrounds=...)`.
- **Smart + Auto music.** `smart_music` gates the existing type/city default chain; **auto music** (new `content/jamendo.py`) auto-selects a popularity-ranked, royalty-free **instrumental from Jamendo** (`JAMENDO_CLIENT_ID`) and **rotates it** so it isn't reused across the last `EG_MUSIC_HISTORY_SIZE` drafts (via `storage.recent_music_track_ids` + `PostContent.music_track_id`). **Commercial/Billboard audio deliberately excluded** — it would trigger YouTube/Instagram copyright takedowns; Jamendo popularity is the legal analog. Live-verified.
- **Aggregator: popularity ranking + unique top-N.** `_rank` now approximates popularity (promo image, ticket price, metadata completeness, source `rank_score`) with imminence demoted to a tiebreaker. Top-N selection applies a day-insensitive uniqueness key (title+venue) so a recurring show fills one slot. Also fixed `aggregator.fetch` to honor the caller's `settings` (was leaking live event-API keys into tests/isolation).
- **Video themes.** New `render/themes.py`: 9 themes (`classic`, `midnight`, `sunset`, `neon`, `minimal`, `editorial`, `mono`, `bold`, `pastel`), each with distinct fonts (resolved from `assets/fonts/` → system fonts, graceful fallback), color palette, and default scrim intensity. `render_video(..., theme=, intensity=)` — **intensity** (0..1) overrides the opacity of the panel the text sits on. Wired through pipeline, UI (theme dropdown + intensity slider, saved in presets), and CLI (`--theme`, `--intensity`, `list-themes`).
- **Compare-themes gallery.** `pipeline.render_theme_previews` (content built once, render varies per theme) + `select_theme`; `PostDraft.theme_previews`/`theme`. UI gallery renders one preview per theme, **streaming each in as it completes**, then pick one to publish. A **"Preview themes"** button sits next to Generate.
- **City dropdown** is now type-to-search (label includes country).
- **UI layout fixes.** Reverted a botched full-width CSS hack that exploded the page on Generate; page is back to the single centered column with only the theme gallery using more width.
- **Live YouTube publishing — verified.** Reinstalled the `publish` extra (env had reset), then worked through the real-account setup: OAuth consent **test users** (renamed to *Audience* in the new console), channel existence, and enabling **YouTube Data API v3**. Improved `youtube._friendly_error` to surface the API's real `reason` (`youtubeSignupRequired`, `quotaExceeded`, `accessNotConfigured`, …) instead of guessing. **A real video published successfully.** (Uploads default to `private` visibility.) Instagram live path still pending (needs Business account + public video host).
- **Phase 2 backlog captured.** Added milestones **M9–M14** (see "Phase 2 — publish-ready upgrades") for: sharper visuals (M9), better ranking + manual event picker (M10), multi-city scale with type-in + favorites (M11), catchier/clickable videos (M12), per-city Instagram + multiple YouTube channels (M13), and straight-to-publish polish (M14). Not started — planned work.
