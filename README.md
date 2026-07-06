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

<!-- M2: fetch events for a city from the CLI -->
<!-- M3: generate a content bundle with mock providers -->
<!-- M4: render a sample mp4 -->
<!-- M5: ./scripts/run.sh  →  generate + preview a draft in the UI -->
<!-- M6: dry-run publish, then live publish a draft -->
<!-- M7: enable a schedule, trigger a run, inspect history -->
