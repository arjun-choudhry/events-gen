#!/usr/bin/env bash
# Launch the Streamlit UI (available from M5).
set -euo pipefail
cd "$(dirname "$0")/.."
exec streamlit run src/events_gen/ui/app.py "$@"
