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

- [ ] **M0.1** Repo layout per §3; `pyproject.toml` with deps; `ruff` + `mypy` + `pytest` configured
- [ ] **M0.2** `.env.example` enumerating every secret; `.gitignore` (env, db, cache, assets output)
- [ ] **M0.3** `config/settings.py` (pydantic-settings) loading env + sane defaults
- [ ] **M0.4** `config/cities.yaml` (seed 3–5 cities) + `config/event_types.yaml` (taxonomy + music map)
- [ ] **M0.5** `models.py` — `Event`, `PostDraft`, `Job`, `Schedule` (typed)
- [ ] **M0.6** `storage.py` — SQLite schema + CRUD for drafts/jobs/history/schedules
- [ ] **M0.7** `README.md` skeleton + `make`/scripts for lint/test/run
- [ ] **M0.8** **Update README** — document setup, layout, and how to run lint/test

**Deliverable:** `pip install -e .` works; `pytest` green on model/storage tests.
**Acceptance:** create → read → update a `PostDraft` in SQLite via `storage.py` in a test.

---

### M1 — City & event-type registry
**Goal:** manage the catalog of cities and event types the app operates on. *(R1, R3)*

- [ ] **M1.1** City registry loader (name, country, coords, timezone, default asset paths)
- [ ] **M1.2** Event-type taxonomy loader + validation
- [ ] **M1.3** Helper to add a new city (writes `cities.yaml` + asset folders)
- [ ] **M1.4** Unit tests for loaders + add-city helper
- [ ] **M1.5** **Update README** — document city/event-type config format + how to add a city

**Deliverable:** programmatic access to cities/types used by pipeline + UI.
**Acceptance:** adding a city via helper makes it selectable everywhere without code changes.

---

### M2 — Data sourcing (event discovery)
**Goal:** fetch, normalize, dedupe, and rank events for a city/window/type. *(R2, R3, R4)*

- [ ] **M2.1** `sources/base.py` — `EventSource` interface → `list[Event]`
- [ ] **M2.2** First API source: **Ticketmaster** (auth, query by city+date+category, pagination)
- [ ] **M2.3** Second API source: **Eventbrite**
- [ ] **M2.4** Response **caching** layer (`data/cache/`) with TTL
- [ ] **M2.5** `aggregator.py` — merge sources, **dedupe** (title+date+venue), **normalize**, **rank**, top-N
- [ ] **M2.6** Time-window filter (this week / this month / custom)
- [ ] **M2.7** Generic public-page **scraper** (`scraper.py`), robots.txt-aware, isolated/optional
- [ ] **M2.8** Additional API sources (PredictHQ, SeatGeek, Meetup) — incremental
- [ ] **M2.9** Tests: dedupe, ranking, window filter, source failure isolation
- [ ] **M2.10** **Update README** — document event sources, required API keys, and caching

**Deliverable:** `aggregator.fetch(city, window, types, count) -> list[Event]`.
**Acceptance:** given a city, returns a deduped, ranked, correctly-sized list from ≥2 live sources; one source failing does not break the result.

---

### M3 — Content generation
**Goal:** produce captions, background images, and music selection for a post. *(R5, R6)*

- [ ] **M3.1** `captions.py` (Claude) — title, caption, hashtags from selected events (prompt + schema)
- [ ] **M3.2** `content/images/base.py` — `ImageProvider` interface
- [ ] **M3.3** `mock_provider.py` — local placeholder image (dev, no keys)
- [ ] **M3.4** `ai_provider.py` — AI image generation (config-selected provider)
- [ ] **M3.5** Image override path — accept user upload, validate/resize
- [ ] **M3.6** `music.py` — default track per event type + user upload override
- [ ] **M3.7** Tests: caption schema/shape, provider selection, upload validation
- [ ] **M3.8** **Update README** — document caption/image/music config + provider selection

**Deliverable:** for a set of events → `{title, caption, hashtags, background_image, music_track}`.
**Acceptance:** pipeline produces valid content bundle with mock providers (no paid keys) and with real providers when keys present.

---

### M4 — Video rendering
**Goal:** compose the final video from content + events. *(R6, R7)*

- [ ] **M4.1** `cards.py` (Pillow) — per-event card (name, date, venue, thumbnail)
- [ ] **M4.2** `formats.py` — presets: 9:16 (Reel/Short), 16:9 (YouTube)
- [ ] **M4.3** `video.py` (MoviePy/FFmpeg) — background + animated cards + music → mp4
- [ ] **M4.4** Duration/pacing logic scaled to number of events
- [ ] **M4.5** Music mixing (fade in/out, trim to length)
- [ ] **M4.6** Render smoke test (small clip) in CI
- [ ] **M4.7** **Update README** — document FFmpeg dependency, formats, and render usage

**Deliverable:** `render.video(content, events, fmt) -> path/to.mp4`.
**Acceptance:** produces a playable mp4 in both aspect ratios with music and readable cards.

---

### M5 — Streamlit UI (control + preview + drafts)
**Goal:** the operator console wiring all controls to the pipeline. *(R1–R8, R10)*

- [ ] **M5.1** App shell + navigation (Create / Drafts / History / Settings)
- [ ] **M5.2** Controls: city (R1), window (R2), event types (R3), count slider (R4)
- [ ] **M5.3** Asset controls: background upload-or-default (R5), music upload-or-default (R6)
- [ ] **M5.4** "Generate" → runs `pipeline.run`, shows progress
- [ ] **M5.5** **Preview**: video player + editable caption/hashtags (R7)
- [ ] **M5.6** Destination selector: YouTube / Instagram / both (R8)
- [ ] **M5.7** **City presets** save/load (R10)
- [ ] **M5.8** Drafts list (saved `PostDraft`s) with re-open/edit/delete
- [ ] **M5.9** **Update README** — document how to launch the UI and the operator workflow

**Deliverable:** end-to-end draft creation + preview from the browser.
**Acceptance:** from a fresh start, user sets controls → generates → previews → saves a draft, all in UI.

---

### M6 — Publishing
**Goal:** push approved drafts to YouTube and Instagram. *(R8, R9)*

- [ ] **M6.1** `publish/base.py` — `Publisher` interface + result model
- [ ] **M6.2** `youtube.py` — OAuth flow, resumable upload, title/description/tags/visibility
- [ ] **M6.3** Video **hosting helper** — upload rendered mp4 to a public URL (required by IG)
- [ ] **M6.4** `instagram.py` — create media container (Reel) → poll status → publish
- [ ] **M6.5** Instagram image/carousel path (fallback format)
- [ ] **M6.6** Persist publish results + external post IDs to history
- [ ] **M6.7** UI **Publish** buttons wired per destination with success/error surfacing
- [ ] **M6.8** Tests/mocks for both publisher clients
- [ ] **M6.9** **Update README** — document YouTube/Instagram credential setup + publish flow

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
- [ ] **M7.6** **Update README** — document scheduler setup, job management, and guardrails

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
- [ ] **M8.7** **Update README** — final pass: full credential walkthrough, quickstart, troubleshooting

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
