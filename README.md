# Events-Gen

Discover upcoming events for a city (this week / this month), generate a short
**video** showcasing them (city background + event cards + music), write captions
with an LLM, and — on your approval — publish to **YouTube** and **Instagram**.
Driven from a **Streamlit** UI.

See [`PLAN.md`](./PLAN.md) for the full milestone roadmap.

> **Status:** M0 (scaffolding & foundations) complete. Config, domain models, and
> SQLite persistence are in place; event sourcing, content generation, rendering,
> UI, and publishing land in later milestones.

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) on your `PATH` (used for video rendering in M4)

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

- **Captions** — Anthropic Claude when `ANTHROPIC_API_KEY` is set (model via
  `EG_CLAUDE_MODEL`, default `claude-sonnet-5`); otherwise a deterministic
  template. Set the key in `.env` to get LLM copy.
- **Background image** — resolved by priority: your uploaded image → the city's
  default asset (`assets/images/<slug>/default.jpg`) → a generated image. The
  generator is `EG_IMAGE_PROVIDER` (`mock` by default; `ai` uses
  `EG_IMAGE_API_KEY` once an image API is wired in, falling back to `mock`).
- **Music** — resolved by priority: your uploaded track → the default track for
  the dominant event type (`assets/music/<type>/default.mp3`) → the city default
  → none (silent). Default tracks are royalty-free files you add under `assets/`.

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

Formats: `reel` (1080×1920, 24fps) and `landscape` (1920×1080, 24fps). Output
lands in `data/output/cli-<city>/<format>.mp4` by default.

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
4. Click **Generate** — a progress panel shows fetch → captions → render, then
   the **preview** appears: an embedded video player plus editable
   title/caption/hashtags (R7). Click **Save edits** to persist changes.
5. **Save as preset** stores the current controls for one-click reuse (R10).

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

<!-- M7: enable a schedule, trigger a run, inspect history -->
