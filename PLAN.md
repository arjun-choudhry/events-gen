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

- [ ] **M9.1** Image source upgrades — request Unsplash `raw`/`w=2160&fit=crop` and Openverse `url` (not `thumbnail`). Add a minimum-resolution filter: skip any image < 70% of target px and fall through to the next source.
- [ ] **M9.2** `Image.LANCZOS` everywhere — update `_cover_fit` (venue.py), `resolve_background`, and `_load_background` (video.py) to use LANCZOS resampling. **Never upscale beyond 1.25×**; if an image is too small, apply a blur-fill (zoom + gaussian blur as full-bleed backdrop).
- [ ] **M9.3** Blur-fill fallback — when the only available image is too small for sharp scaling, generate a zoomed+blurred copy at the target size and overlay the crisp (smaller) image centered. Looks premium, hides the resolution gap.
- [ ] **M9.4** Quality-selectable `VideoFormat` — add a `quality` field (`"1080p"` or `"4k"`) to `VideoFormat`; define new presets `reel_4k` (2160×3840) and `landscape_4k` (3840×2160). Add `"4k"` as an option in the UI format selector and CLI `--quality`.
- [ ] **M9.5** x264 encode quality — set `ffmpeg_params=["-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p"]` in `write_videofile`. Expose `EG_RENDER_CRF` in settings (default 18) so it's tunable without code.
- [ ] **M9.6** Card text rendering at 2× — render card images at 2× the target size then downscale (supersampling), so text edges are sub-pixel smooth even without anti-aliased fonts.
- [ ] **M9.7** Tests — assert output resolution matches the chosen format; assert bitrate is above a threshold; assert sub-resolution images trigger blur-fill (not upscale). Smoke render at 4K without crash.
- [ ] **M9.8** **Update README** — document quality selection, CRF setting, blur-fill behavior, and 4K format presets.

**Deliverable:** visibly crisp output at 1080p and 4K, selectable per render.
**Acceptance:** (a) a 1080p render using an Openverse image shows no upscaling blur on phone; (b) a 4K render produces a 3840×2160 file with CRF 18 and looks sharp on a desktop monitor.

---

### M10 — Better event ranking + interactive manual picker
**Goal:** stop surfacing boring events; give the operator full control over which events appear, with a **live-updating preview** as events are toggled. *(addresses "curated events are boring")*

- [ ] **M10.1** Fetch-first flow — split the Create page into two phases: (1) **Fetch** (city/window/types/count) → populates a candidate pool, stored on `PostDraft.candidate_events`; (2) **Generate** uses only the selected subset.
- [ ] **M10.2** **Interactive event picker** — a full-width table/grid of all fetched candidates showing: ☑ checkbox, thumbnail (event promo image), title, date, venue, price, source badge. Sortable columns. Checked events are the ones that make it into the video.
- [ ] **M10.3** Live lightweight preview — as the user toggles events on/off, a **timeline strip** (horizontal row of card thumbnails in order) + a text summary ("5 selected, ~24s video") updates instantly below the picker. No full video render until Generate.
- [ ] **M10.4** Sort-by control — buttons above the picker: "Popularity" (default) / "Date" / "Price ↓" / "Name A–Z". Clicking re-orders the grid.
- [ ] **M10.5** Better ranking signals from sources — Ticketmaster `attractions[0].upcomingEvents._total` (popularity proxy), SeatGeek `score` / `stats.listing_count`, PredictHQ `rank`/`phq_attendance`. Map each into `Event.rank_score`; the picker's default sort uses this.
- [ ] **M10.6** Additional event sources (deferred M2.8) — SeatGeek, PredictHQ, Meetup. Each new source adds more candidates to the pool and brings its own popularity signal.
- [ ] **M10.7** LLM "interestingness" scorer (optional toggle) — ask Gemini to rate each candidate's shareability (1–10) from its metadata. Cached per event id so it's not re-called. Adds to the composite `rank_score`. Keyless-degradable (off if no LLM key).
- [ ] **M10.8** "Select top N" button — auto-checks the top N by the current sort, as a quick default if the operator doesn't want to hand-pick.
- [ ] **M10.9** Tests — picker selection overrides auto top-N in the pipeline; sort orders match expectations; LLM scorer error degrades gracefully; new source signals affect order.
- [ ] **M10.10** **Update README** — document the fetch→pick→generate flow, the picker UI, sort options, the LLM scorer, and new sources.

**Deliverable:** an interactive picker with live preview, backed by richer ranking + new sources.
**Acceptance:** fetch 30 candidates → use the picker to hand-select 5 → the video contains exactly those 5; the timeline preview updates live.

---

### M11 — Scale to many cities (type-in, multi-select, favorites, combined roundup)
**Goal:** make many-city operation effortless — type any city, batch-generate for several, and save a favorites set that persists. Also support an optional **combined multi-city roundup video** alongside per-city ones.

- [ ] **M11.1** **Geocoded type-in** — a text input that accepts any city name, calls a geocoding service (Nominatim/OpenStreetMap — keyless; or Google Geocoding), resolves `name → country / country_code / coords / timezone`, and adds it to the registry on the fly. Debounced autocomplete showing matching candidates as you type.
- [ ] **M11.2** **Multi-city select** — the city control becomes a multi-select (Streamlit `multiselect` with type-to-search). Selecting N cities generates N independent drafts (one pipeline run per city, sequentially with per-city progress).
- [ ] **M11.3** **Favorites** — a `favorite_cities` storage table (city_slug, user-set order). A "⭐ Favorites" chip-row at the top of the Create page lets you select your favorites with one click. A "Mark as favorite" star button on each city in the dropdown. Favorites persist across sessions.
- [ ] **M11.4** Batch-generation UX — for multi-city, show a per-city progress row ("NYC ✅ / Tokyo ⏳ / London…") and route each finished draft to the Drafts page (or a new "Batch" view grouped by run).
- [ ] **M11.5** **Combined roundup video** (optional) — after per-city videos are generated, an opt-in "Combined roundup" toggle renders a single video pulling the top event from each city into one clip (e.g. "5 Cities × 1 Event Each"). Uses a dedicated intro card ("THIS WEEKEND AROUND THE WORLD") and its own caption.
- [ ] **M11.6** Roundup pipeline — `pipeline.run_roundup(city_slugs, ...)` merges the top event per city, builds a combined content bundle, renders one video.
- [ ] **M11.7** Seed more cities — add 20+ major world cities to `cities.yaml` covering all continents. With M11.1, the seed list becomes just a convenience (any typed city works).
- [ ] **M11.8** CLI support — `events-gen generate --cities new-york,tokyo,london` (comma-separated); `events-gen favorites add/list/remove`.
- [ ] **M11.9** Tests — geocoder called on unknown city; multi-select produces N drafts; favorites round-trip; roundup video combines events from multiple cities.
- [ ] **M11.10** **Update README** — document type-in, multi-city workflow, favorites, roundup, CLI batch commands.

**Deliverable:** type any city, multi-select with favorites, batch-generate, optional combined roundup.
**Acceptance:** type 3 new cities → mark as favorites → next session one-click favorites → generates 3 per-city drafts + 1 combined roundup.

---

### M12 — Catchier, more clickable videos (animation presets)
**Goal:** make renders eye-catching and view-optimized. Two selectable animation styles: **"hype"** (TikTok/Reels-native: fast cuts, zoom, text pop) and **"cinematic"** (polished Ken Burns, smooth reveals). Existing static themes remain as a third "none" option.

- [ ] **M12.1** Animation preset model — `AnimationPreset` dataclass (name, bg_motion, card_enter, card_exit, text_reveal, hook_style). Registry like themes: `ANIMATIONS = {"hype": ..., "cinematic": ..., "none": ...}`.
- [ ] **M12.2** Background motion (Ken Burns / zoom) — per-card segment, the background slowly zooms in or pans. `"hype"` = fast 1.0→1.15× zoom + slight shake; `"cinematic"` = slow 1.0→1.05× pan across the image. Implemented via MoviePy `resize`+`position` keyframes.
- [ ] **M12.3** Card enter/exit transitions — `"hype"` = slide-up from bottom + slight bounce/overshoot; `"cinematic"` = fade-in with a gentle upward drift. Replace the current `FadeIn`/`FadeOut` with preset-driven transition functions.
- [ ] **M12.4** Kinetic text reveal — `"hype"` = per-word pop (each word scales from 0→1 in quick succession); `"cinematic"` = full-line fade with a subtle left-to-right wipe. Implemented as multiple timed `ImageClip`s or character-level animation.
- [ ] **M12.5** Countdown numbers — events numbered "#N → #1" (highest-ranked last) with animated number transition between cards. Optional per preset (`"hype"` = yes, `"cinematic"` = no).
- [ ] **M12.6** Hook intro — first 1–2s: big animated title text over a dimmed/blurred best-image. `"hype"` = "🔥 TOP {N} EVENTS IN {CITY} 🔥" with shake + zoom-in; `"cinematic"` = elegant fade with a slow Ken Burns on the city skyline.
- [ ] **M12.7** Beat-synced pacing (optional, if music present) — analyze the track's BPM/onsets (librosa or aubio); snap card transitions to beats. Falls back to fixed `seconds_per_card` if no music or analysis fails. Add `librosa` as an optional dep.
- [ ] **M12.8** LLM-generated scroll-stopping hooks — ask Gemini for 3 hook variants optimized for CTR; display in the UI for the operator to pick one; the winner becomes the intro text. Also generates thumbnail text (short, high-contrast, emoji-heavy).
- [ ] **M12.9** Thumbnail generation — render a 1280×720 JPEG (YouTube standard) with big text + the best venue image, auto-set on YouTube upload (`snippet.thumbnails`). UI shows a thumbnail preview.
- [ ] **M12.10** Wire into themes — each `Theme` gains an `animation` field (defaults to `"none"` for existing themes); new themes `"hype"` and `"cinematic"` ship with matching visual + animation presets.
- [ ] **M12.11** UI integration — animation preset selector (separate from visual theme, since you can combine "neon" visuals with "hype" motion). Preview renders use the selected animation.
- [ ] **M12.12** Tests — each animation preset renders without error; hook text is generated; thumbnail is a valid JPEG at 1280×720; beat analysis returns a BPM or degrades; countdown ordering matches rank.
- [ ] **M12.13** **Update README** — document animation presets, hook generation, thumbnail, beat-sync, and the UI controls.

**Deliverable:** two animation presets (hype + cinematic), hook intro, kinetic text, optional beat-sync, thumbnail.
**Acceptance:** render "hype" and "cinematic" side-by-side — both visibly more dynamic than the current static version; hook grabs attention in the first second; thumbnail is auto-set on YouTube.

---

### M13 — Per-city destinations (Instagram + multiple YouTube channels)
**Goal:** route each city's video to its own accounts. One city can publish to **1+ YouTube channels** and **its own Instagram account** — all managed in the UI.

- [ ] **M13.1** Destination model — `Destination` (id, city_slug, platform, label, credentials_ref). Stored in a `destinations` table. A city has 0..N destinations.
- [ ] **M13.2** Destination management UI — in the city settings (or a new "Destinations" page), for each city: list configured destinations, add/remove. "Connect YouTube channel" triggers the OAuth flow and saves the token under a unique ref. "Connect Instagram" stores account id + token.
- [ ] **M13.3** Multi-channel YouTube — each YouTube destination has its own `client_secrets_file` + `token_file` (stored under `secrets/<dest_id>/`). The publisher receives a specific `Destination` and uses its credential set. Supports N channels per city.
- [ ] **M13.4** Per-city Instagram — each IG destination stores `access_token` + `business_account_id` independently. The Instagram publisher receives the destination's credentials. A "Connect IG for this city" button in the UI saves them.
- [ ] **M13.5** Publish routing — `publish_draft(draft, destinations=...)` iterates the city's configured destinations (or a manual override). For each, picks the right publisher + credentials. Results recorded per destination in `PublishResult` (extend model to include `destination_id`).
- [ ] **M13.6** Default destinations on the city — when a city has configured destinations, they auto-fill the publish targets so the operator doesn't re-pick each time. Overridable per draft.
- [ ] **M13.7** Credential security — tokens live in `secrets/<dest_id>/token.json`, never in the DB payload. `.gitignore` covers `secrets/`. Document the file layout.
- [ ] **M13.8** Migration — existing global `YOUTUBE_CLIENT_SECRETS_FILE` / `INSTAGRAM_ACCESS_TOKEN` env vars become the "default" destination (used when no per-city destination is configured). Backward compatible.
- [ ] **M13.9** Tests/mocks — city with 2 YT channels + 1 IG publishes to all three; one fails, others succeed; results tracked per destination; credential isolation.
- [ ] **M13.10** **Update README** — document per-city destination setup (YouTube + IG), the secrets layout, the UI flow, and backward compatibility.

**Deliverable:** one draft → published to all of a city's configured channels/accounts.
**Acceptance:** configure city X with 2 YouTube channels + 1 Instagram → publish → all three receive the video, each tracked independently in history.

---

### M14 — Straight-to-publish polish (ties everything together)
**Goal:** close the remaining gaps so "generate → publish" needs zero manual cleanup. The end-state: **one button → favorites → generated → published.**

- [ ] **M14.1** Configurable YouTube visibility — `EG_YOUTUBE_PRIVACY` (per destination or global default): `public` | `unlisted` | `private`. Default: `unlisted` (visible via link, not searchable — safe to test, easy to switch to public).
- [ ] **M14.2** Live Instagram publishing — verify end-to-end with a real Business account. Solve the public-URL hosting gap: either (a) built-in S3 upload (add `boto3`, upload the mp4, return the URL), or (b) a simple `cloudflared tunnel` helper that serves `data/output/` for the duration of the publish, or (c) Firebase Hosting / Vercel deploy. Decide in M14.2a, implement in M14.2b.
- [ ] **M14.3** Pre-publish validation — before publishing, automatically check: video file exists + is valid mp4 (probe); resolution ≥ platform minimum; audio track present (if music selected); caption ≤ platform limit (2200 chars IG, 5000 YT); hashtag count ≤ 30 (IG). Block publish with a clear message if any check fails.
- [ ] **M14.4** One-click "Publish favorites" — a top-level action (button in sidebar + CLI command) that: loads favorite cities → for each, generates a draft (or uses the latest ready draft) → publishes to all configured destinations → shows a batch summary.
- [ ] **M14.5** Post-publish confirmation — after publish, show the live URL(s), embed a preview if possible (YouTube oEmbed / IG embed), and record analytics (publish time, destinations, external ids) in history.
- [ ] **M14.6** Scheduling integration — the scheduler (M7) gains per-city destination awareness so `auto_publish=True` publishes to the city's configured destinations (not a global target set).
- [ ] **M14.7** Tests — validation blocks bad drafts; batch publish hits N destinations; scheduler uses per-city destinations; S3 upload (mocked) returns a URL.
- [ ] **M14.8** **Update README** — document the publish-favorites flow, validation checks, IG hosting solution, scheduler destination routing, and the final end-to-end workflow.

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
