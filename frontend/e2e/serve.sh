#!/usr/bin/env bash
# The API and the built frontend on port 8019, with forecasts rebuilt from the saved
# fixtures (no network), and small files for the map's other layers. Used by
# `npm run e2e` (playwright.config.ts starts it).
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
echo '{"generated_at":null,"viirs_date":null,"locations":[]}' >"$data/sat/index.json"
# One snow station, one field report and one ATES file, so the map's feature layers load
# (the worker fetches the real ones hourly).
mkdir -p "$data/stations" "$data/overlays"
cat >"$data/stations/stations.json" <<'JSON'
{"generated_at":"2026-11-04T18:00:00+00:00","errors":[],"stations":[{"id":"908:WA:SNTL","name":"Olallie Meadows","network":"snotel","lat":47.37,"lon":-121.44,"elev_m":1222,"obs_time":"2026-11-04T17:00+00:00","depth_cm":40.6,"change24_cm":15.2,"daily":[{"date":"2026-11-01","depth_cm":10.2},{"date":"2026-11-02","depth_cm":20.3},{"date":"2026-11-03","depth_cm":25.4}],"url":"https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=908"}]}
JSON
cat >"$data/avalanche/observations.geojson" <<'JSON'
{"type":"FeatureCollection","generated_at":"2026-11-04T18:00:00+00:00","days":14,"errors":[],"features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-117.1,51.3]},"properties":{"id":"c8bc99e4-1b77-11f1-9993-0a58a9feac02","title":"Whumpfing at treeline","time":"2026-11-03T19:00+00:00","region":"Purcells","kinds":["snowpack","quick"],"images":1,"url":"https://avalanche.ca/mountain-information-network/submissions/c8bc99e4-1b77-11f1-9993-0a58a9feac02"}}]}
JSON
cat >"$data/overlays/test-area.geojson" <<'JSON'
{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"name":"Bowl","ATES":"Challenging"},"geometry":{"type":"Polygon","coordinates":[[[-121.45,47.4],[-121.4,47.4],[-121.4,47.43],[-121.45,47.4]]]}}]}
JSON
exec uv run --frozen uvicorn --factory snowwatch.api.app:production_app --port 8019
