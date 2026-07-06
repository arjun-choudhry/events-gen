#!/usr/bin/env bash
# Lint + type-check the codebase.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== ruff =="
ruff check src tests
echo "== ruff format (check) =="
ruff format --check src tests
echo "== mypy =="
mypy
