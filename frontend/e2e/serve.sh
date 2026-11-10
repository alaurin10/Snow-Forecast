#!/usr/bin/env bash
# The API and the built frontend on port 8019, with forecasts rebuilt from the saved
# fixtures (no network). Used by `npm run e2e` (playwright.config.ts starts it).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data="$(mktemp -d)"
trap 'rm -rf "$data"' EXIT
cd "$here/../../backend"
export DATA_DIR="$data" STATIC_DIR="$here/../build" OWNER_PASSWORD="e2e-owner-password"
uv run --frozen snowwatch init >/dev/null
uv run --frozen snowwatch rebuild --from tests/fixtures/live-20261104 >/dev/null
exec uv run --frozen uvicorn --factory snowwatch.api.app:production_app --port 8019
