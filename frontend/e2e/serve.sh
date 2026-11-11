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
# No avalanche zones (they come from the network), but the file, so the map's
# avalanche layers load and say there's no zone here.
mkdir -p "$data/avalanche"
echo '{"type":"FeatureCollection","generated_at":null,"features":[]}' >"$data/avalanche/zones.geojson"
# A satellite index with no scenes and no VIIRS day, so the Recent satellite base loads
# without asking the network for tiles.
mkdir -p "$data/sat"
echo '{"generated_at":null,"viirs_date":null,"hls_date":null,"locations":[]}' >"$data/sat/index.json"
exec uv run --frozen uvicorn --factory snowwatch.api.app:production_app --port 8019
