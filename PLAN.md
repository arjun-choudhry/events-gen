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

- [ ] **M7.1** `scheduler.py` (APScheduler) — weekly/monthly per-city jobs
- [ ] **M7.2** Job model persisted; survives restart
- [ ] **M7.3** UI toggle per city/cadence + "review-required vs auto-publish" switch
- [ ] **M7.4** Run history / logs view in UI
- [ ] **M7.5** Guardrails: quota checks, skip if no events, notify on failure
- [ ] **M7.6** **Update README** — document scheduler setup, job management, guardrails, and **runnable steps to try M7** (enable a schedule, trigger a run, inspect history)

**Deliverable:** enable a city schedule → auto-generates (and optionally auto-publishes).
**Acceptance:** a scheduled job produces a draft (or publishes) at the configured time; visible in history.

---

### M8 — Hardening, docs, and release
**Goal:** robust, documented, credential-ready.

- [ ] **M8.1** Retries/backoff (tenacity) + rate-limit handling across all clients
- [ ] **M8.2** Error surfacing in UI (per-source, per-publish)
- [ ] **M8.3** Quota/token-expiry handling + re-auth prompts (YouTube/IG)
- [ ] **M8.4** Test coverage: aggregator, captions, render smoke, publisher mocks
- [ ] **M8.5** `README.md` — full setup + **credential walkthrough** (per §6)
- [ ] **M8.6** Sample `.env`, seed cities, and a demo dry-run mode
- [ ] **M8.7** **Update README** — final pass: full credential walkthrough, quickstart, troubleshooting, and a **consolidated "Trying it out per milestone" section** verified end-to-end

**Deliverable:** a documented app another person could set up from README.
**Acceptance:** clean checkout → follow README → produce and (dry-run) publish a post.

---

## 6. External accounts & credentials (setup checklist)

- [ ] **Anthropic API key** (captions)
- [ ] **AI image provider** key (chosen at config time)
- [ ] **Event APIs**: Ticketmaster, Eventbrite, PredictHQ, SeatGeek, Meetup
- [ ] **YouTube**: Google Cloud project → enable YouTube Data API v3 → OAuth client → authorize channel
- [ ] **Instagram**: convert to Business/Creator, link a Facebook Page, create Meta app, enable Instagram Graph API, generate long-lived token
- [ ] **Music**: royalty-free library placed in `assets/music/`

> **Instagram note:** publishing is 2-step — create a **media container** (needs a public video URL for Reels) then **publish**. M6.3 delivers the hosting helper for this.

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

- [ ] Which specific AI image provider to wire into `ai_provider.py` (M3.4)
- [ ] Full initial set of cities to seed `cities.yaml` (M0.4/M1)
- [ ] Where to host rendered videos for IG publish (bucket vs tunnel) (M6.3)
- [ ] Preferred video style/branding (colors, fonts, intro/outro, logo) (M4)

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
