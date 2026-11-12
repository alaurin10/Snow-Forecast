# Changelog

Notable changes to Snow Watch. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **Map radar covers the whole West and has a type.** Radar now comes from
  Environment Canada's North American composite (Canadian and US radars, 1 km),
  split into snow, mix and rain by its precipitation-type product, and goes back
  three hours. RainViewer is kept as the fallback.
- The map's pictures cover a fixed western North America box (BC, Alberta, the US
  Rockies, California), widened only if a location is outside it (`map:` in
  `config/forecast.yaml`).
- The worker draws the map in three jobs: radar every 6 minutes, forecast frames
  every 30, snow totals hourly. Its memory limit is now 1.5 GB.

### Added
- **Measure on the map.** A new tool measures a line tapped out on the map: distance,
  climb and descent, its average and steepest grade, the steepest ground it crosses, and
  an elevation profile coloured like the slope overlay (drag along it to find the spot on
  the map). Tap a ski run or route and choose Profile for the same numbers; or open a
  GPX track, which is read on the device and never uploaded.
- **More on the map from OpenStreetMap:** huts and shelters, trailheads, passes,
  glaciers, cliffs, and ski routes made of many ways (so tours like the Spearhead
  Traverse have their names). Tapping one names it in the Inspector. The file is now
  served gzipped.
- **Snow stations on the map.** Every SNOTEL station and BC snow pillow in the map's box,
  coloured by snow depth and labelled with the last 24 hours' new snow; tap one for its
  numbers and a week's sparkline. Refreshed hourly (`map.stations_minutes`,
  `snowwatch map stations`).
- **Field reports on the map.** Avalanche Canada's Mountain Information Network reports
  from the last two weeks, as rings coloured by what they report; tap one for a link to
  the full report. Reporters' names aren't kept. Refreshed hourly (`map.obs_minutes`,
  `map.obs_days`, `snowwatch map obs`).
- **ATES terrain ratings.** The owner can add Avalanche Terrain Exposure Scale files
  (KMZ from Avalanche Canada's trip planner, KML or GeoJSON) on the Manage page or in
  `data/overlays/`; the map then offers them as a layer, as published.
- **Snow totals adjusted to the terrain.** Zoomed in (from zoom 8), the map's Snow total
  is drawn on the terrain: the model's precipitation falls as snow above the model's
  snow level (with a 300 m rain/snow mix band) and as rain below it, so ridges get the
  snow and valleys under the snow level don't. Tapping the map gives the snow at the
  spot's own height, and three days' worth at a few heights around it. The worker keeps
  each window's snow every 250 m of elevation (`data/maps/totals/bins-*.npy`, ~32 MB a
  window) and the api paints tiles from it on demand (`/api/snowtiles/…`).
- **More weather on the map.** Snow level (every 250 m) and wind (gusts near the ground,
  or the wind at ridge level) every 3 hours for about 3½ days, from Canada's HRDPS and
  RDPS and NOAA's National Blend, blended across the border; snow on the ground (SNODAS
  in the US, CaLDAS in Canada); snow that fell in the last 24, 48 and 72 hours (NOHRSC,
  the US only); and the last three hours of GOES-West clouds. One weather layer at a
  time, from the controls or the Layers sheet. Zoomed in on Snow level, the rain/snow
  line is draped on the terrain. Drawn by a new `layers` job every 30 minutes
  (`map.layers_minutes`, `snowwatch map layers`).
- **Tap the map for the weather there.** The Inspector adds forecast snow for 24 hours,
  3 and 7 days, the next two days hour by hour, the snow level, the wind, snow on the
  ground and snow that fell, from `GET /api/map/point`. Away from saved locations the
  Wind effect layer now uses the map's own forecast for the next 24 and 72 hours.
- **Recent satellite base map.** Sentinel-2 at 10 m over the 24 km round each location:
  first the newest clear view, stitched from the newest passes that saw each part, with
  dashed lines and dates where they meet; then the newest whole scenes that cover the
  area and see at least 85% of it. Snow-vs-cloud view (snow cyan, cloud white). Views are
  drawn by the worker every 6 hours and served as finished tiles, so the map loads and
  pans quickly. NOAA-20's daily VIIRS mosaic (375 m) elsewhere. `sat_*` in `map:`,
  `snowwatch map sat`. Esri's imagery stays as "Satellite".
- **Avalanche danger zones on the map.** Every forecast zone in the West from
  avalanche.org's centers and Avalanche Canada, in the official danger colours for
  today's highest rating (grey when expired or unrated), exactly as published; tap one
  for its three-band pyramid, problems and a link to the center.
- **Avalanche problems on the map.** The terrain today's listed problems describe
  (their aspects and elevation bands, steeper than 25, 30 or 35°) for the zone in the
  middle of the map, using approximate treeline bands from `config/treeline.yaml`,
  which the owner can override near a location.
- **Experimental concern index** on the map, for every visitor: the app's own
  estimate from the bulletin's rating for each band, slope angle, the listed problems,
  likely wind loading and sun, in four classes in a non-danger palette. Each browser
  accepts a warning once (remembered there), and the layer always carries a fixed
  caption. The Inspector shows every factor. `HAZARD_INDEX=off` hides it.
- The map's Inspector names the avalanche zone, the spot's elevation band and today's
  rating for it.
- `GET /api/avalanche/zones.geojson` and `GET /api/map/concern`; `snowwatch avalanche`
  also writes the zones.
- **Sun & shade on the map.** Terrain shadows for any date and time of day (with the
  hills lit from where the sun really is), or the day's hours of direct sun. Tap the
  map for when the sun first and last reaches a spot.
- **Wind effect on the map.** Where the forecast wind at the nearest location's summit
  would likely strip or load snow, from the shape of the terrain (Winstral's Sx), for
  the last 48 hours or the next 24 or 72. An estimate, labelled as one.
- `GET /api/map/wind`; snapshots carry loading roses for those three windows.
- A 72-minute radar nowcast between the radar and the forecast on the map's slider.
- `snowwatch map radar|forecast|totals|all`.
- `backend/snowwatch/maps/`, including NOAA GRIB2 reading by byte range
  (`gribberish`), ready for the longer forecast in milestone 2 of
  `docs/MAP-PLAN.md`.

## [1.0.0] – 2026-11-10

The first release prepared as a product: no third-party login, safe to expose
publicly, and documented for anyone who wants to run it.

### Changed
- The **More** tab is now **Settings** (with a gear icon); old `/more` links
  redirect there.
- **Owner password instead of Cloudflare Access.** Forecasts are public and
  read-only; `OWNER_PASSWORD` unlocks Manage locations. `ADMIN_EMAILS`,
  `CF_ACCESS_TEAM`, `CF_ACCESS_AUDS` and `DEV_ADMIN_EMAIL` are gone. Upgrading
  from an Access setup: see [docs/deploy-notes-home.md](docs/deploy-notes-home.md).
- The scorecard compares the consensus with observations by calendar day, like
  the model rows (it used 06:00–06:00 windows before).
- The API container runs `uvicorn --factory snowwatch.api.app:production_app`
  with JSON logs; both containers run read-only.
- Plain-language wording throughout ("temperature-based depth", "high-resolution
  models").

### Added
- A Version card in Settings: the app's version, the server's version and
  build, and a "Reload to update" button when the two differ.
- About page: data sources and licences, a forecast and avalanche disclaimer, a
  privacy note and the version. A friendly not-found page.
- "A new version is ready — Reload" instead of silent updates.
- `/api/meta` (version, commit, budgets and alert thresholds) and
  `/api/push/prefs`; the Alerts card now shows a device's saved choices.
- `snowwatch owner logout-all` and `snowwatch healthcheck worker`; the worker has
  a Docker health check.
- Nightly retention for forecast history, runs, jobs, flags and observations.
- Security headers (a strict Content-Security-Policy, HSTS in production),
  per-visitor rate limits, a tile-cache size cap (`TILES_MAX_MB`) and a
  push-subscription cap (`PUSH_MAX_SUBSCRIPTIONS`).
- Browser smoke tests, coverage, dependency audits and Dependabot in CI.
- MIT licence, security policy, contributing guide, deployment and architecture
  docs.

### Security
- MapLibre GL JS upgraded from 5.x to 6.17 for a critical sanitizer-bypass XSS
  advisory (GHSA-jrc7-96c5-q579).

### Fixed
- Push subscriptions could point anywhere, making the server send requests to
  any address; only browser push services are accepted now.
- Links from upstream data or old rows could be `javascript:` addresses.
- Quickly switching locations could show the previous location's data.
- A failed request read as "No avalanche zone" or "needs a snow station".
- A database error mid-run left the run "running" forever and skipped the
  remaining locations; interrupted runs and jobs are now closed at start-up.
- An empty upstream answer could wipe the ski-area list or avalanche zones; one
  bad avalanche product or radar image stopped the rest; a failed product fetch
  replaced the stored full forecast with a thin one.
- `Retry-After` was ignored, and an upstream outage could hold the worker for
  hours; a time budget now limits retries.
- Manage page actions failed silently; job polling continued after leaving.
- Dialogs didn't trap or restore focus; several inputs had no label.
- The owner's contact email was sent to every upstream service, not just NWS.

### Removed
- The prototype (`docs/reference/`, `sources/prototype.py`, the parity test).
- Unused components and the write-only `alerts` and `obs_hourly` tables.
