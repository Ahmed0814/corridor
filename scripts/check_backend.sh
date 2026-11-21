#!/usr/bin/env bash
# Run exactly the backend checks the CI "backend" job runs, in the same order, before pushing.
# Usage: ./scripts/check_backend.sh   (Postgres + Redis must be running; see docs/development.md)
set -euo pipefail
cd "$(dirname "$0")/../backend"
step() { echo "==> $*"; "$@"; }
step uv run ruff check .
step uv run ruff format --check .
step uv run python scripts/gen_importlinter.py
step git diff --exit-code -- .importlinter      # generated contracts must be committed
step uv run lint-imports
step uv run mypy .
step uv run mypy . --platform linux             # CI runs on Linux
step uv run python manage.py check --fail-level WARNING
step uv run python manage.py makemigrations --check --dry-run
step uv run python scripts/gen_permission_matrix.py --check
REQUIRE_SERVICES=1 step uv run pytest -q
step uv run pip-audit --strict --skip-editable
echo "All backend CI checks passed."
