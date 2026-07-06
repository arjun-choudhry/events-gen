# Events-Gen

Discover upcoming events for a city (this week / this month), generate a short
**video** showcasing them (city background + event cards + music), write captions
with an LLM, and — on your approval — publish to **YouTube** and **Instagram**.
Driven from a **Streamlit** UI.

See [`PLAN.md`](./PLAN.md) for the full milestone roadmap.

> **Status:** M0–M7 complete; M8 (hardening & release) done. The full pipeline —
> discover → caption → render → preview → publish, plus optional scheduling —
> runs end-to-end. It works **keyless** in dev (mock event source, template
> captions, placeholder background, dry-run publish); real API keys switch on
> live sources and publishing.

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) on your `PATH` (used for video rendering)

## Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install the package (with dev tools)
pip install -e ".[dev]"

# 3. Configure environment (all keys optional for local dev)
cp .env.example .env
#   edit .env to add API keys as you enable each feature
```

Optional extras:

- `pip install -e ".[publish]"` — YouTube/Instagram publishing clients (M6)
- `pip install -e ".[scrape]"` — HTML scraping support (M2)

## Quickstart

Prove the whole pipeline works with **no keys and no config** — generate a video
and dry-run publish it end-to-end:

```bash
python -m events_gen.cli demo
# or: events-gen demo --count 5 --format landscape
```

Then launch the UI to drive it interactively:

```bash
./scripts/run.sh        # Streamlit console at http://localhost:8501
```

## Configuration

Configuration comes from two places:

- **`.env`** — secrets and runtime settings, loaded by `events_gen.settings.Settings`.
  Every field is optional; missing credentials degrade gracefully (image generation
  falls back to a mock provider, event sources without keys are skipped). See
  [`.env.example`](./.env.example) for the full list.
- **`config/*.yaml`** — data files describing the catalog the app operates on:
  - `config/cities.yaml` — the city registry (name, timezone, coordinates, default assets)
  - `config/event_types.yaml` — the event-type taxonomy and default music mapping

## Project layout

```
config/            YAML data: cities + event types
assets/            Default background images, music, fonts
data/              SQLite db, response cache, rendered output (git-ignored)
src/events_gen/
  settings.py      Env/config loading (pydantic-settings)
  models.py        Domain models: Event, PostDraft, Job, Schedule
  storage.py       SQLite persistence
  sources/         Event discovery (APIs + scraper)      [M2]
  content/         Captions (Claude), images, music       [M3]
  render/          Video rendering (MoviePy/FFmpeg)        [M4]
  publish/         YouTube + Instagram publishing          [M6]
  ui/app.py        Streamlit UI                            [M5]
scripts/           lint / test / run helpers
tests/             pytest suite
```

## Development

```bash
./scripts/lint.sh    # ruff check + format check + mypy
./scripts/test.sh    # pytest
./scripts/run.sh     # launch the Streamlit UI (from M5 onward)
```

Or invoke tools directly:

```bash
ruff check src tests
mypy
pytest
```

## Trying it out per milestone

Each milestone adds a feature you can run and see working. This section grows
as milestones land (see the "Update README" step in each milestone of
[`PLAN.md`](./PLAN.md)).

### M0 — foundations (config, models, storage)

Verify the scaffolding works end-to-end (no API keys needed):

```bash
# Run the full test + lint suite
./scripts/test.sh
./scripts/lint.sh

# Smoke check: settings load, config files resolve, and a draft round-trips
# through SQLite (uses a throwaway temp DB — your real data/ is untouched)
python scripts/smoke.py
```

Expected: tests pass, lint is clean, and the smoke check prints
`M0 smoke check passed ✅`.

### M1 — city & event-type registry

Inspect the catalog and add new cities from the CLI (no API keys needed):

```bash
# List configured cities and event types
python -m events_gen.cli list-cities
python -m events_gen.cli list-types

# Add a new city (slug derived from name; creates assets/images/<slug>/)
python -m events_gen.cli add-city \
    --name "Paris" --country France --country-code FR \
    --timezone Europe/Paris --lat 48.8566 --lon 2.3522

# It now appears everywhere:
python -m events_gen.cli list-cities   # Paris is listed
```

After `pip install -e .`, the same CLI is available as the `events-gen` command
(e.g. `events-gen list-cities`).

### M2 — data sourcing (event discovery)

Fetch events for a city from the CLI. With **no API keys**, a deterministic
`MockSource` supplies synthetic events so you can see the full flow; add keys to
`.env` and real sources (Ticketmaster, Eventbrite) take over automatically.

```bash
# This week's events for Tokyo (mock data until keys are set)
python -m events_gen.cli fetch tokyo --window week --count 5

# This month, filtered to specific event types
python -m events_gen.cli fetch london --window month --types music arts --count 8
```

**Sourcing model:** real API sources are used when their keys are present in
`.env` (`TICKETMASTER_API_KEY`, `EVENTBRITE_API_TOKEN`, …); if none are
configured the mock source is used so dev never dead-ends. Responses are cached
under `data/cache/` (TTL) to avoid burning rate limits. A robots.txt-aware
scraper source exists for public event pages that publish schema.org JSON-LD; it
only activates for a city with a configured `scrape_url` and never touches
login-gated sites.

### M3 — content generation

Generate the caption, background image, and music selection for a city's events
— all with **no API keys** (template captions + a Pillow-generated placeholder
background):

```bash
python -m events_gen.cli generate-content tokyo --window week --types music arts --count 4
```

This prints the title/caption/hashtags and writes a 1080×1920 background under
`data/output/`. Content sources:

- **Captions** — a pluggable LLM. Set `GEMINI_API_KEY` (free, no credit card)
  or `ANTHROPIC_API_KEY` (paid) in `.env`. `EG_CAPTION_PROVIDER` (`auto` by
  default) picks whichever key is present, preferring free Gemini; with neither,
  a deterministic template is used. Models via `EG_GEMINI_MODEL`
  (`gemini-2.0-flash`) / `EG_CLAUDE_MODEL` (`claude-sonnet-5`).
- **Background image** — resolved by priority: your uploaded image → the city's
  default asset (`assets/images/<slug>/default.jpg`) → a generated image. The
  generator is `EG_IMAGE_PROVIDER` (`mock` by default; `ai` uses
  `EG_IMAGE_API_KEY` once an image API is wired in, falling back to `mock`).
- **Music** — resolved by priority: your uploaded track → the default track for
  the dominant event type (`assets/music/<type>/default.mp3`) → the city default
  → none (silent). Default tracks are royalty-free files you add under `assets/`.

#### Smart features (per-event, toggle in the UI Create page)

- **🖼️ Smart backgrounds** — instead of one shared background, each event card
  shows a background of *where it's happening*, resolved in priority order:
  1. the event's own promo image (from Ticketmaster/Eventbrite), else
  2. an [Unsplash](https://unsplash.com/developers) search for the venue/city
     (`UNSPLASH_ACCESS_KEY` — note: Unsplash apps stay rate-limited until
     approved, so this may return nothing), else
  3. an [Openverse](https://openverse.org) search — Creative-Commons images,
     **no API key required**, so this works out of the box, else
  4. the shared city background.

  Ignored when you upload a background. Each fetch is best-effort — a miss falls
  through to the next tier, never breaking the render.
- **🎵 Smart music** — picks a default track based on the dominant event type
  present. Off means silent unless you upload a track. Needs audio files under
  `assets/music/<type>/default.mp3` (royalty-free; you supply them).
- **🎧 Auto music** — auto-selects a **popularity-ranked, royalty-free
  instrumental** from [Jamendo](https://devportal.jamendo.com) (`JAMENDO_CLIENT_ID`,
  free, no card) and **rotates it** so it isn't reused across your last
  `EG_MUSIC_HISTORY_SIZE` posts (default 5). Takes priority over the type/city
  default, but an uploaded track always wins.
  > ⚠️ **Why not Billboard / chart hits?** Commercial audio is copyrighted —
  > auto-attaching it would get your videos **muted or struck** by YouTube
  > Content ID / Instagram audio matching, and violates this project's
  > royalty-free-only rule. Jamendo's popularity ranking is the legal analog to
  > "trending music."

Programmatically these are flags on `pipeline.run(...)`:
`smart_backgrounds=True`, `smart_music=True`, `auto_music=True`.

### M4 — video rendering

Render a slideshow mp4 from discovered events — background image + fading event
cards + optional music. Requires **FFmpeg** on your `PATH` (brew/apt/choco).

```bash
# Render a 9:16 Reel/Short (default)
python -m events_gen.cli render new-york --count 5

# Render a 16:9 YouTube landscape video
python -m events_gen.cli render tokyo --format landscape --window month --count 8

# Specify an output path
python -m events_gen.cli render london -o my_video.mp4
```

The video includes:
- **Intro card** — post title (city + time window)
- **Per-event cards** — title, date/time, venue, price range (4 seconds each by default)
- **Outro card** — closing message
- **Music** — if a track is resolved (per M3 rules), it's faded in/out and trimmed to the video length

Formats: `reel` (1080×1920), `landscape` (1920×1080), `reel_4k` (2160×3840),
`landscape_4k` (3840×2160). All at 24fps. Output lands in
`data/output/cli-<city>/<format>.mp4` by default.

#### Image quality & resolution (M9)

- All images are resized with **LANCZOS** (high-quality) resampling.
- A **minimum-resolution gate** rejects images smaller than 70% of the target —
  they're never hard-upscaled. Instead, an automatic **blur-fill** background
  (zoomed + gaussian blur) is generated, and the sharp (smaller) image is
  overlaid centered. This looks premium and hides the resolution gap.
- Unsplash is now queried at `raw` resolution (up to 3840px), not `regular`.
- Card text is **supersampled at 2×** then downscaled for crisp edges.
- The x264 encode uses **CRF 18** (visually lossless) by default. Tunable via
  `EG_RENDER_CRF` in `.env` (lower = better quality, bigger file).

#### Themes

A **theme** controls the video's look — fonts, color palette, and the
**intensity** of the panel the text sits on — independently of the format.
Pick one in the UI Create page (with an intensity slider), or from the CLI:

```bash
python -m events_gen.cli list-themes                     # see all themes
python -m events_gen.cli render new-york --theme neon    # pick a theme
python -m events_gen.cli render tokyo --theme minimal --intensity 0.25
```

Nine themes ship (`classic`, `midnight`, `sunset`, `neon`, `minimal`,
`editorial`, `mono`, `bold`, `pastel`), each with distinct fonts, colors, and
default panel intensity. `--intensity 0.0–1.0` overrides that panel opacity:
higher = more opaque/readable, lower = more of the background image shows
through. Programmatically: `render_video(..., theme="neon", intensity=0.3)` or
`pipeline.run(..., theme="neon", intensity=0.3)`.

Fonts are resolved from `assets/fonts/` first, then your OS's system fonts, by
trying each theme's candidate list — so themes look their best where those
fonts exist and **degrade gracefully** (to Pillow's default) where they don't.
Drop `.ttf` files into `assets/fonts/` to guarantee a consistent look across
machines.

#### Animations (M12)

Videos can have **motion** via animation presets — composable with any theme:

| Preset | Look |
|---|---|
| `none` | Static background, fade in/out cards (current default) |
| `hype` | Fast Ken Burns zoom (1→1.12×), slide-up card entrance, emoji hook intro |
| `cinematic` | Subtle zoom (1→1.04×), slow fade entrance, elegant hook intro |

```bash
python -m events_gen.cli render new-york --animation hype
python -m events_gen.cli render new-york --theme neon --animation cinematic
```

In the UI, select from the **Animation** radio (None / Hype / Cinematic) on the
Create page. The hook intro adds 1.5–2s to the video with scroll-stopping text
(e.g. "🔥 TOP 5 IN NYC 🔥"). Programmatically:
`render_video(..., animation="hype")` or `pipeline.run(..., animation="hype")`.

### M5 — Streamlit operator console

Launch the browser UI that wires every control to the pipeline:

```bash
./scripts/run.sh          # or: streamlit run src/events_gen/ui/app.py
```

Then, from the **Create** page:

1. Pick a **city** (R1), **time window** — week/month (R2), **event types** (R3),
   and the **number of events** slider, 3–15 (R4).
2. Optionally upload a **background image** (R5) or **music track** (R6) —
   otherwise city/type defaults (or a generated placeholder) are used.
3. Choose **destinations** — YouTube / Instagram / both (R8).
4. Click **Fetch Events** — discovers a pool of ~30 candidates and opens the
   **interactive event picker** below.
5. **Pick events** — the picker shows all candidates (title, date, venue, price)
   with checkboxes. Sort by Popularity / Date / Price / Name. Use "Select top N"
   for a quick default, or hand-pick exactly what goes in the video. A live
   summary strip shows the selected count + estimated duration, updating as you
   toggle.
6. Click **Generate Video** (or **Preview themes**) — renders only the events you
   selected. The **preview** appears: video player + editable title/caption/hashtags
   (R7). Click **Save edits** to persist changes.
7. **Compare themes** — render one video per theme and pick the best one.
8. **Save as preset** stores the current controls for one-click reuse (R10).

   > **Quick Generate** (next to Fetch) skips the picker and runs the old direct
   > flow — useful when you trust the auto-ranking and don't need to curate.

Other pages:
- **Drafts** — every saved `PostDraft`: re-open, preview, edit caption, delete.
- **History** — published posts + external IDs (populated in M6).
- **Settings** — resolved paths and which credentials are present.

Everything runs **keyless** by default (mock event source, template captions,
Pillow placeholder background), so the console works end-to-end with no API
keys. Programmatically, the same flow is one call:

```python
from events_gen import pipeline
draft = pipeline.run(city_slug="new-york", count=5, render_format="reel")
print(draft.video_path)
```

### M6 — Publishing (YouTube + Instagram)

Publish a rendered draft to YouTube and/or Instagram. The flow is **dry-run by
default** — it simulates the full publish end-to-end (no accounts, no network),
so you can try it with zero credentials:

```bash
# Generate a draft and dry-run publish to both destinations
python -m events_gen.cli publish new-york --count 5 --targets youtube instagram

# Go live (requires credentials, see below)
python -m events_gen.cli publish new-york --live --targets youtube
```

In the UI, every draft preview has a **Publish** section: pick destinations,
toggle **Dry run**, and click **Publish now** — results (and post URLs) surface
inline and are stored in **History**.

Publishing needs the optional extra: `pip install -e ".[publish]"`.

**YouTube (Data API v3, OAuth):**
1. Create a Google Cloud project → enable **YouTube Data API v3**.
2. Create an **OAuth client** (Desktop app) → download the client-secrets JSON.
3. Set `YOUTUBE_CLIENT_SECRETS_FILE` (and `YOUTUBE_TOKEN_FILE` for the cached
   token). First live publish opens a browser to authorize your channel.
4. Videos upload as **private** by default (change via `privacy_status`).

**Instagram (Graph API):** publishing a Reel is two-step — create a media
container from a **public video URL**, then publish it. So you need:
1. An Instagram **Business/Creator** account linked to a Facebook Page.
2. A Meta app with the Instagram Graph API + a **long-lived token**:
   set `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_BUSINESS_ACCOUNT_ID`.
3. A public host for the rendered mp4: set `EG_PUBLIC_VIDEO_BASE_URL` to a base
   URL serving `data/output/` (S3, static host, or a tunnel). The hosting helper
   maps `data/output/<draft>/reel.mp4` → `<base>/<draft>/reel.mp4`.

Failure is isolated per destination: if one platform fails, the other still
publishes and the draft is marked `failed` with the error recorded.

### M7 — Automation & scheduling (optional, off by default)

Schedules make the app run itself on a cadence per city. Nothing is scheduled
until you create one — automation is opt-in.

From the **Schedules** page in the UI: pick a city, cadence (weekly/monthly),
window, event types, count, destinations, and whether to **auto-publish** or
just generate a draft for review. Toggle **Enabled**, use **Run now** to trigger
immediately, and watch results land in **History** (a run-log table of every
job). Or manage schedules headlessly:

```bash
# Add a weekly, review-required schedule (generate only)
python -m events_gen.cli schedule add new-york --cadence weekly --count 5

# Add a monthly auto-publishing schedule
python -m events_gen.cli schedule add tokyo --cadence monthly --auto-publish \
    --targets youtube instagram

python -m events_gen.cli schedule list          # see ids + state
python -m events_gen.cli schedule run <id>      # trigger one immediately
```

- **Cadence:** weekly fires Monday 09:00, monthly fires the 1st at 09:00, in the
  **city's timezone**.
- **Review vs auto-publish:** with `auto_publish=false` (default) a run only
  generates a draft you approve later; with `true` it publishes to the
  schedule's destinations.
- **Restart-safe:** enabled schedules live in the database; the scheduler
  reconstructs its jobs from storage on start, so they survive restarts.
- **Guardrails:** a run that finds no events is *skipped* (recorded, not failed);
  any error is caught and recorded so one bad run never kills the scheduler.

To run the scheduler in a long-lived process:

```python
from events_gen.scheduler import SchedulerService
svc = SchedulerService()
svc.start()   # reconstructs jobs from storage and begins firing
```

## Credentials checklist

Everything below is **optional** — the app runs keyless. Add each as you enable
the matching feature (see the per-feature sections above for details):

| Feature | Env var(s) | Where to get it |
|---|---|---|
| Captions (Gemini, free) | `GEMINI_API_KEY` | aistudio.google.com/apikey |
| Captions (Claude, paid) | `ANTHROPIC_API_KEY` | console.anthropic.com |
| AI backgrounds | `EG_IMAGE_PROVIDER=ai`, `EG_IMAGE_API_KEY` | your chosen image provider |
| Ticketmaster | `TICKETMASTER_API_KEY` | developer.ticketmaster.com |
| Eventbrite | `EVENTBRITE_API_TOKEN` | eventbrite.com/platform/api |
| YouTube | `YOUTUBE_CLIENT_SECRETS_FILE`, `YOUTUBE_TOKEN_FILE` | Google Cloud Console → YouTube Data API v3 → OAuth client |
| Instagram | `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID`, `EG_PUBLIC_VIDEO_BASE_URL` | Meta app + IG Business/Creator account + public host |

## Troubleshooting

- **`ffmpeg not found` / render fails** — install FFmpeg and ensure it's on your
  `PATH` (`ffmpeg -version`). On macOS: `brew install ffmpeg`.
- **No events found** — with no API keys the mock source always returns events;
  if a live source is configured but returns nothing, widen the window
  (`--window month`) or drop the `--types` filter. Scheduled runs *skip* (not
  fail) when there are no events.
- **YouTube "quota exceeded" (403)** — the Data API has a daily quota; each
  upload is expensive. Wait for the quota to reset or request more in Cloud
  Console.
- **YouTube keeps opening a browser / "token expired"** — delete the token file
  (`YOUTUBE_TOKEN_FILE`) and re-run to re-authorize the channel.
- **Instagram "needs a public video URL"** — set `EG_PUBLIC_VIDEO_BASE_URL` to a
  host that serves `data/output/` (S3, static host, or a tunnel like
  cloudflared/ngrok). IG downloads the mp4 itself, so `localhost` won't work.
- **Transient API blips** — HTTP calls to event APIs and Instagram retry
  automatically with exponential backoff on network errors, 5xx, and 429
  rate-limits; other 4xx (bad key/params) fail fast.
- **Reset local state** — delete `data/events_gen.db` (drafts/jobs/schedules)
  and `data/output/` (rendered videos); both are git-ignored and rebuilt.
