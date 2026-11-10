# Architecture

How Snow Watch is put together: the moving parts, where data comes from, how the
forecast is computed, and the rules the code keeps. For running it, see
[`DEPLOYMENT.md`](DEPLOYMENT.md). The original design documents are in
[`history/`](history/).

## Moving parts

```
browser ─► reverse proxy or tunnel (HTTPS) ─► api :8000 (FastAPI: the app + /api)
                                               │ reads; writes only locations, jobs,
                                               │ owner sessions and push subscriptions
                                             SQLite (WAL) in ./data
                                               ▲ writes
   Open-Meteo, NWS, SNOTEL, BC RFC,  ◄───────── worker (APScheduler: runs, job queue,
   avalanche centers, map sources                avalanche, map frames, backups, cleanup)
```

| Piece | What it does |
|---|---|
| `api` | `uvicorn --factory snowwatch.api.app:production_app`. Serves the built SvelteKit app and `/api`. Never calls weather services itself, except the Manage page's auto-detect and the map tile cache |
| `worker` | `snowwatch worker`. Four forecast runs a day, avalanche checks, the job queue (every 15 s), the map's pictures (radar and nowcast every 6 min, forecast frames to 10 days every 30 min, snow totals to 10 days hourly), ski runs from OpenStreetMap (weekly), lookups (weekly), a nightly backup and retention, a weekly VACUUM. Touches a heartbeat file every 30 s |
| `./data` | `snowwatch.db`, `raw/` (24 h of upstream responses, for `snowwatch rebuild`), `backups/`, `precip/`, `maps/` (model grid maps, cached NOAA GRIB messages, snow totals as numbers), `tiles/`, `osm/` |

Both run from one image (`docker/Dockerfile`: a Node stage builds the app, a
Python 3.12 slim stage runs it, as uid 1000, read-only, with no capabilities).

## Code map

```
backend/snowwatch/
  api/        app.py (routes, headers, static files) auth.py (owner sign-in)
              public.py admin.py push_api.py models.py ratelimit.py
  sources/    one module per upstream: requests and parsing
  analysis/   periods, consensus, hourly, ensemble, slr, ridge, freezing,
              backcountry, skiday, flags, build (assembles the snapshot)
  locations/  resolve.py (auto-detect for Manage) service.py (the list)
  store/      db.py migrations/*.sql repo.py backup.py retention.py
  maps/       the map's weather pictures: region.py (the box) geomet.py (Environment
              Canada's WMS/WCS) grib.py (NOAA GRIB2 by byte range) palette.py
              render.py (frames, index, pruning) totals.py (snow totals to 10 days)
              sources/ (radar_eccc, rainviewer, hrrr, nbm, rdps_gdps)
  pipeline.py scheduler.py jobs.py http.py (retries, budgets) cli.py
  avalanche.py precip.py (re-exports maps/) tiles.py osm.py lookups.py push.py verify.py
frontend/src/
  routes/     overview, location/[id], map, calendar, more, status, about, admin
  lib/        api.ts (the client) types.gen.ts (generated) charts/ components/
              backcountry/ observed/ manage/ share/ + small helpers
  service-worker.ts
```

The API's response models (`api/models.py`, `doc.py`) are exported as JSON Schema
(`snowwatch schema`) and turned into TypeScript (`npm run types`); CI fails if
either is out of date, so the two sides can't drift.

## A forecast run

For each active location (`pipeline.run_all`), 20 s apart to stay polite:

1. **Fetch** (`pipeline.fetch_responses`): Open-Meteo's high-resolution blend and
   multi-model forecasts at base, mid and summit, upper-air levels, ensembles at
   mid (twice a day, cached between), NWS alerts (US), and the snow station.
   Each source fails on its own; only the two Open-Meteo forecasts are required.
2. **Build** (`analysis/build.py`) one snapshot document, described below.
3. **Store**: the gzipped snapshot (newest 8 kept), per-day totals for the trend
   and scorecard, observations, and when each flag was first raised.
4. **After the run**: avalanche forecasts, then push alerts for flags first
   raised in this run.

A location that fails keeps its last good snapshot. A run always ends `ok`,
`partial` or `failed`; runs and jobs interrupted by a restart are marked failed
when the worker starts. `/api/health` answers 503 when the last good run is
older than `STALE_AFTER_H` (12 h).

## The analysis

- **Periods**: day 06–18 and night 18–06 in the location's time (a night belongs
  to its evening's date); 20 periods, the first may be partial.
- **Consensus** per period: the median of the deterministic models while at least
  three cover it; the short-range models (HRRR, NBM, HRDPS) and the blend join in
  the first 48 h; after that, the ensemble mean. The basis is shown in the app.
- **Hourly series add up to the bars**: the hourly shape comes from the model
  median and is scaled so each period sums to its consensus.
- **Ensembles**: running totals per system (GEFS, ECMWF ENS, GEPS); the pooled
  10–90% band stops where the shortest system ends, so no percentile line dips.
- **Snow depth**: model snowfall uses a fixed 7:1 snow-to-water ratio. A
  temperature-based ratio (8:1 heavy and wet to 17:1 dry) is computed alongside;
  `depth_method` in `config/forecast.yaml` picks the headline one, and the
  scorecard shows which has been closer.
- **Bands**: everything is computed at base, mid and summit at each band's own
  coordinates; freezing level comes from the model or from the upper-air levels.
- **Backcountry** (no safety judgement anywhere): avalanche danger exactly as
  published and hidden once expired, ridge-height wind, a snow-loading rose,
  warming, rain on snow, refreeze, cloud above treeline, daylight.
- **Ski-day rating** for resorts: Powder, Great, Good, Fair or Poor, with the
  reasons, from new snow, snow quality, rain, summit gusts, cloud and temperature.
- **Flags**: powder day, storm incoming, model outlier, low confidence, rain on
  snow, snow-level crossing, wind hold, wind loading, rapid warming, refreeze,
  NWS alert, avalanche danger 4+. Thresholds live in `config/forecast.yaml`.
- **Trend and scorecard**: each run keeps per-day totals; the Models tab shows how
  the forecast moved over the last runs, and the scorecard compares the forecast
  made before each day with what the snow station measured, by calendar day.

## Storage and retention

SQLite in WAL mode; plain SQL migrations in `store/migrations/`, applied in order
and recorded by name. Nightly (`store/retention.py`):

| Data | Kept |
|---|---|
| Snapshots | newest 8 per location |
| `forecast_daily` | everything for 14 days, then the forecasts up to 2 days ahead (what the scorecard uses), for 400 days |
| `runs`, `jobs`, `flag_log` | 90 days (runs still referenced are kept) |
| `obs_daily` | 400 days |
| Avalanche forecasts | 30 days |
| Raw responses | 24 h |
| Map tiles | 45 days unused, and at most `TILES_MAX_MB` |
| Backups | 14 nightly copies |

## Security model

- **No accounts.** Forecasts are public and read-only. One owner password
  (`OWNER_PASSWORD`, 12+ characters) unlocks Manage. A sign-in stores a random
  token in an HttpOnly, SameSite=Strict cookie (Secure in production) and its
  SHA-256 in `owner_sessions`; sessions last 30 days and can all be ended with
  `snowwatch owner logout-all`. Wrong passwords lock a client out for longer
  each time, with a global cap. Owner writes must carry this site's `Origin`.
- **Public endpoints are bounded**: push subscriptions must point at a browser
  push service, are capped in size and number, and are rate limited; map tile
  cache misses are rate limited and the cache is capped on disk.
- **Headers**: a strict Content-Security-Policy (only the hashed start-up script;
  third parties limited to AWS terrain tiles and https images), `nosniff`,
  frame denial, a referrer policy, a permissions policy, and HSTS in production.
- **Links** shown to visitors must be http(s); bad upstream links are dropped.
- **Privacy**: no analytics; the owner's contact email goes only to NWS, which
  asks for it; viewers' settings and positions stay in their browsers.

See [`../SECURITY.md`](../SECURITY.md) for reporting a problem.

## The app

A SvelteKit single-page app (`adapter-static`), hand-built SVG charts on d3
scales, MapLibre for the map. A service worker caches the app and the last API
answers for offline use, saves map areas on request, shows push notifications,
and waits for the page's "Reload" before switching to a new version.

Rules the charts keep: one y-axis per chart, marks never outside the plot (tested),
units converted in the browser (the API is metric only), and every chart works at
380 px with a thumb.
