# Architecture

How Snow Watch is put together: the moving parts, where data comes from, how the
forecast is computed, and the rules the code keeps. For running it, see
[`DEPLOYMENT.md`](DEPLOYMENT.md). The original design documents are in
[`history/`](history/).

## Moving parts

```
browser ─► reverse proxy or tunnel (HTTPS) ─► api :8000 (FastAPI: the app + /api)
                                               │ reads; writes only locations, jobs, owner
                                               │ sessions, push subscriptions, spot ensembles
                                             SQLite (WAL) in ./data
                                               ▲ writes
   Open-Meteo, NWS, SNOTEL, BC RFC,  ◄───────── worker (APScheduler: runs, job queue,
   avalanche centers, map sources                avalanche, map frames, backups, cleanup)
                                                 │ forecasts and elevation, when OPEN_METEO_URL is set
   public Open-Meteo data on AWS ◄── openmeteo :8080 (optional, compose profile `openmeteo`)
                                         ▲ serves what lands in its volume
   NOAA (AWS), ECMWF, Environment  ◄── openmeteo-ensembles (optional, profile `ensembles`)
   Canada: ensemble runs
```

| Piece | What it does |
|---|---|
| `api` | `uvicorn --factory snowwatch.api.app:production_app`. Serves the built SvelteKit app and `/api`. Never calls weather services itself, except the Manage page's auto-detect, the map tile cache (which also fetches the Mapterhorn elevation tiles it paints terrain-adjusted snow totals on) and, with a self-hosted Open-Meteo server, forecasts for a tapped point (spots, below) |
| `worker` | `snowwatch worker`. Eight forecast runs a day (every 3 hours), avalanche checks, the job queue (every 15 s), the map's pictures (radar and nowcast every 6 min, forecast frames to 10 days every 30 min, snow totals to 10 days hourly, with the same by elevation for the terrain-adjusted map), `config/webcams.yaml` where it changed (at start and every 5 min), ski runs from OpenStreetMap (weekly), lookups (weekly), a nightly backup and retention, a weekly VACUUM. Touches a heartbeat file every 30 s |
| `openmeteo` | Optional (compose profile `openmeteo`, used when `OPEN_METEO_URL` is set): Open-Meteo's own server, image pinned by digest and run unmodified. It reads the public Open-Meteo data on AWS as asked and caches it in the `openmeteo-data` volume. It answers every forecast and elevation request from `worker` and `api` (Manage's auto-detect, spots); ensembles stay on the public API unless the downloader below fills its volume. No published port |
| `openmeteo-ensembles` | Optional (compose profile `ensembles`): the same image running `docker/ensembles.sh`, which every 10 minutes downloads each new GEFS, ECMWF ENS and GEPS run (snowfall only, 16 days) from NOAA on AWS, ECMWF and Environment Canada into the `openmeteo-data` volume, where the server serves it at `/v1/ensemble` with no restart. One system at a time, 2 CPUs, a 2 h limit per download; it deletes what the server doesn't need after each run and skips runs below 5 GB free. It writes `ensembles/status.json` (each system's last run, time, size, last error) and `ensembles/disk.log` (a line a day). `worker` and `api` mount the volume read-only at `/openmeteo`; `snowwatch openmeteo status` reads it. The app uses what it downloads only with `OPEN_METEO_ENSEMBLES` (below) |
| `./data` | `snowwatch.db`, `raw/` (24 h of upstream responses, for `snowwatch rebuild`), `backups/`, `precip/`, `maps/` (model grid maps, cached NOAA GRIB messages and GeoMet grids, snow totals as numbers and by elevation, the terrain-adjusted snow tiles drawn so far), `tiles/`, `osm/`, `avalanche/zones.geojson` (every forecast zone in the map's box, rewritten with each avalanche check), `sat/` (the satellite index, the passes already judged and their grids, cached pass pictures, and each drawn view's tiles) |

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
              blend.py (joins sources as numbers, with no visible seams)
              render.py (frames, index, pruning) totals.py (snow totals to 10 days)
              bins.py terrain_totals.py (snow totals every 250 m of elevation)
              tiles_render.py (those painted on the terrain as tiles, by the api)
              layers.py (snow level, temperature, wind, snow on the ground, observed snowfall,
              clouds) point.py (tap-for-numbers from the pictures' probes)
              sat.py (choosing recent Sentinel-2 views per location, daily VIIRS)
              satrender.py (drawing those views and cutting them into tiles)
              sources/ (radar_eccc, rainviewer, hrrr, nbm, rdps_gdps, snodas,
              nohrsc, gibs)
  pipeline.py scheduler.py jobs.py http.py (retries, budgets, routing to a
  self-hosted Open-Meteo with the public fallback) cli.py checks.py (check-sources,
  openmeteo status) spots.py (a forecast for any point, built on request)
  avalanche.py avalanche_zones.py (every zone for the map, treeline bands)
  stations.py (every snow station in the map's box) observations.py (Avalanche
  Canada's field reports) nwac_obs.py (NWAC's observations page, read in headless
  Chromium) overlays.py (the owner's ATES files)
  precip.py (re-exports maps/) tiles.py osm.py (runs, huts, glaciers, routes …)
  lookups.py push.py verify.py
frontend/src/
  routes/     overview, location/[id], spot (a point's forecast), map, compare, calendar,
              more, status, about, admin
  lib/        api.ts (the client) types.gen.ts (generated) charts/ components/
              (LocationView: the forecast page a location and a spot share)
              recentSpots.ts (the last 10 spots, in the browser)
              backcountry/ confidence/ observed/ manage/ share/ + small helpers
              railui.svelte.ts (the desktop rail folded or open over the full-window map)
              compare.ts (Compare: lining up several locations' steps on one timeline, day
              cells, the comparison's edits, its URL and the groups kept in the browser);
              charts/CompareChart, components/CompareTimeline, CompareAdd, CompareGroups
              map/ (the Map page's pieces: style.ts, layers/, Timeline, LayersSheet,
              TerrainControls, AvalancheControls, SatControls, sat.ts, Legend,
              Measure and Profile (measure.ts: lines, GPX, stats); DockItem and DockTabs (the
              controls at the map's foot: one open over a row of tabs); MapPanel, the one
              panel a tap opens, showing Inspector (the spot), StationCard, ReportCard,
              ZoneCard or FeatureCard; features.ts (stations, reports, ATES) and here.ts
              (what a tap landed on, ranked, as the panel's targets);
              avalanche.ts (zones, treeline, problems); terrain/ decodes elevation
              and works out slope, aspect, sun and shade, the wind effect and the
              concern index in a Web Worker, served to MapLibre as dem:// and
              terrain:// and as one picture for the view)
  service-worker.ts
```

The API's response models (`api/models.py`, `doc.py`) are exported as JSON Schema
(`snowwatch schema`) and turned into TypeScript (`npm run types`); CI fails if
either is out of date, so the two sides can't drift.

## A forecast run

For each active location (`pipeline.run_all`), 20 s apart to stay polite (no pause
with a self-hosted Open-Meteo server, see below):

1. **Fetch** (`pipeline.fetch_responses`): Open-Meteo's high-resolution blend and
   multi-model forecasts at base, mid and summit, upper-air levels, ensembles at
   mid (twice a day, cached between), NWS alerts (US), and the snow station.
   Each source fails on its own; only the two Open-Meteo forecasts are required.
2. **Build** (`analysis/build.py`) one snapshot document, described below.
3. **Store**: the gzipped snapshot (newest 8 kept), per-day totals for the trend
   and scorecard, observations, and when each flag was first raised.
4. **After the run**: avalanche forecasts, then one push digest per subscribed
   device covering every location with something new (`push.py`): a powder day or
   storm alerts once when it comes within 5 days, and again only if it grows a lot;
   `push_log` keeps flickering flags and storms that shift by a day quiet.

**Self-hosted Open-Meteo** (`OPEN_METEO_URL`; docs/OPEN-METEO-PLAN.md): the request
builders don't change. `http.Fetcher` rewrites `https://api.open-meteo.com/v1/`
(forecasts, elevation) to the server in one place and gives it one try with a 120 s
timeout; `ensemble-api.open-meteo.com` is never rewritten. On a connection error,
timeout or 5xx it retries once on the public URL when `OPEN_METEO_FALLBACK` is on, the
caller allows it, and today's public budget has room; after a connection failure it
skips the server for 5 minutes, so a stopped container costs one failed connection.
`total_weight` counts only requests that reached a public Open-Meteo host. When a run
finishes, its requests go into the usage ledger (`api_usage`: per UTC day and host,
public weight, requests, fallbacks, and the server's requests and seconds), which the
Status page, `snowwatch budget` and the budget check read; with a server configured,
every public Open-Meteo request checks the ledger first. NWS, NRCS AWDB and the BC RFC
get at least 0.5 s between requests now that the pause between locations is gone;
while a run is falling back, locations are 20 s apart again for the public API's
per-minute limit.
With a server, `MAX_LOCATIONS` defaults to 50 and `SITE_SPACING_S` to 0.

**Self-hosted ensembles** (`OPEN_METEO_ENSEMBLES`, milestone 1b): `public` leaves
everything above as it is. With `local`, `Fetcher._route` also rewrites
`ensemble-api.open-meteo.com/v1/ensemble` to the server for a system (the request's
`models`) whose downloaded run is fresh, read from `<folder>/static/meta.json` in the
read-only volume (`snowwatch/ensembles.py`: GEFS and ECMWF ENS 14 h, GEPS 26 h). An
answer missing members or not reaching far enough ahead (GEFS and GEPS 360 h, ECMWF
336 h) counts as a failure. `pipeline.fetch_responses` reads fresh systems every run;
when one fails it takes the cached ensembles (`ensemble_cache`, 13 h) first and the
public API only when the public schedule would have asked anyway (`ensemble_runs_utc`),
each system on its own. While forecasts are falling back too, optional requests
(ensembles, upper air, clouds, station) leave `pipeline.forecast_reserve` (the rest of
today's runs' blend and multi-model requests) in the public budget. Each run records
each system's source in `ensemble_state`, shown on the Status page. With `shadow`, each
public ensemble a run fetches is also asked of the server (`Fetcher.shadow_ensemble`),
and the comparison goes into `ensemble_shadow` (members, reach, member totals' mean and
largest difference, and both runs: the server's from its meta.json, the public data's
from the public bucket's), summarised on the Status page over 7 days, same runs only.
`snowwatch check-ensembles` builds each snapshot with both and lists every field that
differs. Systems served locally cost nothing in the budget (`public_daily_weight`).

## Forecasts anywhere (spots)

With a self-hosted Open-Meteo server, anyone can tap a point in the US or Canada on the
map for the same forecast a saved location has (`GET /api/spot?lat=&lon=`,
`snowwatch/spots.py`, docs/OPEN-METEO-PLAN.md milestone 2). Nothing about it is stored
but its ensembles:

1. **Where**: the point, rounded to ~100 m, must be inside `config/borders.geojson`
   (Natural Earth's US and Canada outlines, simplified; within 3 km counts), which also
   picks the country's short-range models. Outside: 422.
2. **Bands from the terrain**: one `/v1/elevation` request for the point and 24 samples
   on rings 1 and 2.5 km out. Near the highest ground the point is the summit (base the
   lowest, mid 60 % up); near the lowest it's the base; otherwise it's mid. Bands stay
   150 m apart; flat ground gets 300 m below and above. All three share the point.
3. **A transient `Location`** (`spot-<geohash>`, backcountry, time zone from the
   forecast) named after a peak within 2 km in the map's OpenStreetMap file, else "6 km
   NE of" a saved location within 40 km, else its coordinates.
4. **Fetch** with the saved locations' request builders, from the server only: no
   public fallback, so a stopped server means 503. No snow station, SNOTEL or BC data.
   US spots get NWS alerts, kept 10 minutes per 0.1° cell. Every request runs at once
   (a thread pool): the terrain, upper air, clouds and alerts first, then the blend,
   multi-model forecast and ensembles once the bands are known. The multi-model forecast
   and upper air are asked for one model per request and joined (`merge_models`), since
   the server reads one request's models in turn. The API logs each request's time.
5. **Ensembles** (mid band), per system: a nearby spot's from `spot_ensembles` (per
   0.25° cell and 100 m of elevation, 6 h); else the server's while its run is fresh
   (`OPEN_METEO_ENSEMBLES=local`, free); else the public API within the spots' daily
   allowance (`spots.ensemble_allowance`, 2,000 weighted calls, recorded in `api_usage`
   as host `spots`, which counts in the public total). Past it the spot builds without
   them and says so (`Snapshot.spot.ensembles`).
6. **Build** with `inputs_from_responses` and `build_snapshot`, unchanged, plus
   `Snapshot.spot` (the point, which band holds it, how the bands were chosen, the
   ensembles' source, the nearest saved location).

`/api/spot/nearby` gives a spot's Observed and Backcountry extras from local files: the
nearest snow stations and field reports (shared with `/locations/{id}/nearby` as
`nearby_at`) and the avalanche zone it's in, with that zone's forecast from the map's
zones file.

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
- **Snow depth**: the pipeline works in snow water and turns it into depth once,
  with the headline method (`depth_method` in `config/forecast.yaml`, `slr` since
  Nov 2026): each period's snow water × a ratio from the median temperature of its
  snowing hours (8:1 heavy and wet to 17:1 dry); hours outside the periods (the past
  24–72 h, days past the 20th period) use their own temperature's ratio. With nothing
  snowing, and under `raw`, it is Open-Meteo's fixed 7:1. Every surfaced depth follows
  it: the bars, hourly series and window totals (a window is the sum of its bars), the
  ensemble ranges and member totals, each model's bar, Model agreement's daily rows, the
  past 24 h, the Backcountry storm and loading rose, Plan-a-day, the ski-day rating,
  flags and so push alerts, the overview and Calendar. The snapshot keeps the 7:1
  figures as `*_raw` (and the ratio ones as `*_slr`). The map's snow totals use the same
  ratio bands, so the map and the location pages agree.
- **Trend and scorecard**: every run stores the consensus both ways in
  `forecast_daily` (`cons` at 7:1, `cons_slr` temperature-based); the trend reads the
  headline one, so changing `depth_method` shows no step, and the scorecard scores
  both, marks the headline (`headline` in the response) and says which has been closer.
  Each model's and the ensemble's records stay at their own 7:1.
  The scorecard has two checks. Snow depth: the station's depth gain against each
  source, plus the consensus as settled snow (`cons_settled`, its snow water at
  `verify_settled_ratio`, 8:1), leaving out days the depth can't measure (no snowpack,
  or above freezing all day). Precipitation: the gauge's catch against each source's
  total water (`water_mm`), on every day, bare ground and rain included. Both checks
  also score a forecast for the station's own spot and elevation (`stn_cons`, and
  settled `stn_settled`): each run asks Open-Meteo for every model's snowfall and
  precipitation there, 3 days ahead (`station_request`, about 1.2 calls), and stores
  the models' daily median. The bands don't move; the charts lead with this forecast
  once it has a week of days. SNOTEL dates
  its daily depth, snow water and gauge total by the day they close; the parser moves
  them to the day they open (`snotel.start_of_day`), as the BC stations are read.
- **Bands**: everything is computed at base, mid and summit at each band's own
  coordinates, except the freezing level: one height for the location, found at the
  lowest band (from the model, or from its upper-air levels with the lowest band's
  temperature as the bottom of the column) and shared by every band. The snow level is
  305 m below it. The map's snow level is a different product (NBM's in the US, Canada's
  models' WEonG), so the two can differ.
- **Backcountry** (no safety judgement, with two bounded exceptions below): avalanche
  danger exactly as published and hidden once expired (each listed problem's aspects
  and elevations redrawn as a small rose), ridge-height wind, a snow-loading rose,
  warming, rain on snow, refreeze, cloud above treeline, daylight, and a day-by-day
  outlook (`backcountry.outlook`, today and six days on, whole calendar days with the
  high-res model's past days behind them): each day's summit new snow and 72 h total,
  sustained ridge wind and the slopes it loads, rain onto snow and how high it reaches,
  the freezing level, hours of thaw at the summit, warming in 24 h, and the refreeze the
  night before at each band.
  The map's Sun & shade and Wind effect layers are estimates from the shape of the
  terrain (and, for wind, the nearest location's loading rose), labelled as such; they
  describe sun and likely drifting, not stability. Its danger zones are the centers'
  ratings as published, in their colours; its Avalanche problems layer only redraws
  what a bulletin lists (aspects and elevation bands) on the terrain, with treeline
  numbers that are labelled approximate.
- **Exception one: the map's concern index.** An experimental, app-computed
  estimate per slope: `(published danger for the band + wind + sun) × slope × match`
  (`frontend/src/lib/map/terrain/concern.ts`, numbers in `config/forecast.yaml` →
  `terrain:`), drawn in four relative classes in a palette unlike the danger scale's,
  only inside the zone whose bulletin it uses, and only while that bulletin has a
  current rating for today. It is open to every visitor (there are no visitor
  accounts); `HAZARD_INDEX=off` hides it for the whole site. Each browser accepts a
  warning before it is first drawn, remembered in that browser, and it always carries
  the caption
  "Experimental estimate from the bulletin and terrain shape. Not a forecast. Doesn't
  show runouts or slopes above you." The Inspector shows every factor for a spot.
- **Exception two: the outlook's weather loading** (`stress` in the code). Each outlook
  day grades four factors 0–3 (new snow, drifting, rain onto snow, warming) on
  rule-of-thumb thresholds
  (`config/forecast.yaml` → `backcountry: outlook_*`, `analysis/backcountry.py`): new
  snow on the day's or the 72 h total, drifting only with recent snow to move, warming
  from a sharp 24 h rise or a summit thaw (held at 1 after a good refreeze, one more
  after none). The day's stress is its strongest factor, one more when two are strong
  together, with a rising / steady / easing trend. It grades the weather, not the
  snowpack, and is never a danger rating: it uses its own words (Little, Some, Strong,
  Very strong) and the concern index's blue-to-magenta hues, never the danger scale's,
  shows the published danger beside it only for days the bulletin covers, and always
  carries a key under the days: "estimated from the forecast. It isn't a danger rating,
  and it can't see the snowpack itself: buried weak layers stay dangerous through quiet
  weather." The thresholds travel in the snapshot (`backcountry.outlook_steps`) so the key
  can show them in the viewer's units. `HAZARD_INDEX=off` (`hazard_index` in `/api/meta`)
  hides the grade and leaves the facts.
- **Ski-day rating** for resorts: Powder, Great, Good, Fair or Poor, with the
  reasons, from new snow, snow quality, rain, summit gusts, cloud and temperature.
- **Flags**: powder day, storm incoming, model outlier, low confidence, rain on
  snow, snow-level crossing, wind hold, wind loading, rapid warming, refreeze,
  NWS alert, avalanche danger 4+. Thresholds live in `config/forecast.yaml`.
- **Confidence** (the browser, `frontend/src/lib/confidence.ts`): high, medium or low
  for each window from the ensembles' 10–90% range against the consensus (agreement
  within 5 cm is always high; small totals are judged against 10 cm), falling back to
  the models' lowest and highest when there is no ensemble; how the consensus moved
  between the newest run and the oldest of the last five (about a day, the trend
  taking one run per 6 hours), over the days both cover.
- **Trend and scorecard**: each run keeps per-day totals; the Confidence tab shows how
  the forecast moved over the last runs (one per 6 hours, so runs that repeat the same
  model data don't flatten it) and each source's track record, and the
  Observed tab charts the forecast made before each day against what the snow station
  measured, by calendar day.
- **Nearby** (`/api/locations/{id}/nearby`): the stations within 60 km and the field
  reports from the last two weeks (Avalanche Canada's and NWAC's), read from the files
  the map's layers use (no upstream calls), for the Observed tab and the Webcams tab's
  photos. The photos are grouped: *near* (within 20 km and closer to this location than
  to any other) and *zone* (farther, in the location's avalanche zone: NWAC's zone id, or
  the zone outline from `zones.geojson` that holds the report).

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
| `spot_ensembles` | 6 h (`spots.ensemble_cache_h`), dropped as new ones are written |
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
  cache misses are rate limited and the cache is capped on disk; the map's
  tap-for-numbers (`/api/map/point`) reads only local files and is rate limited;
  terrain-adjusted snow tiles (`/api/snowtiles/…`) are drawn only for grids the worker
  wrote (16-hex ids), zoom 5–11, from local files and cached Mapterhorn elevation tiles,
  and count against the tile cache's miss limit when not already drawn.
  Forecasts for a tapped point (`/api/spot`, only with a self-hosted Open-Meteo server)
  are the one place the API makes outbound requests for any visitor: to the `openmeteo`
  server, NWS alerts and the public ensemble API. Each built spot is kept for an hour
  (300 at most, per ~100 m); new ones are limited per visitor (8, then one every 15 s),
  to 2 at a time and to about 600 an hour for the whole site, and run in the thread
  pool; cached ones have a lighter limit. Public ensembles for spots stay within a daily
  allowance, and the outline check rejects points outside the US and Canada before any
  request. `/api/spot/nearby` reads local files only.
- **Headers**: a strict Content-Security-Policy (only the hashed start-up script;
  third parties limited to Mapterhorn and AWS elevation tiles, and https images; satellite
  imagery comes through the server's tile cache, which fetches only Sentinel-2 items in its
  own index and a fixed list of GIBS layers), `nosniff`,
  frame denial, a referrer policy, a permissions policy, and HSTS in production.
- **Links** shown to visitors must be http(s); bad upstream links are dropped.
- **The app's estimates** (`HAZARD_INDEX`): when it is off, `GET /api/map/concern`
  answers 404, so the map has nothing to work out the concern index with and doesn't
  offer it, and `/api/meta` says `hazard_index: false`, so the Backcountry tab shows the
  outlook's facts without the weather-loading grade.
- **Privacy**: no analytics; the owner's contact email goes only to NWS, which
  asks for it; viewers' settings and positions stay in their browsers.

See [`../SECURITY.md`](../SECURITY.md) for reporting a problem.

## The app

A SvelteKit single-page app (`adapter-static`), hand-built SVG charts on d3
scales, MapLibre for the map. A service worker caches the app and the last API
answers for offline use (only the last 10 spots), saves map areas on request, shows push
notifications, and waits for the page's "Reload" before switching to a new version.

A location's page and a spot's page are one component, `LocationView`: the route loads
the forecast and passes loaders for the rest (trend, scorecard, nearby, avalanche), and
a section with no loader is left out, so a spot shows no trend, scorecard or webcams.
With `/api/meta`'s `local_forecasts`, the map's spot panel offers "Full forecast here"
and a right-click or long press opens one (`/spot?lat=…&lon=…`); the owner can save a
spot as a location from its page (Manage, with its three bands filled in).

Rules the charts keep: one y-axis per chart, marks never outside the plot (tested),
units converted in the browser (the API is metric only), and every chart works at
380 px with a thumb.
