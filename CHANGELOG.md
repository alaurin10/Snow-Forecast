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
- **Avalanche danger zones on the map.** Every forecast zone in the West from
  avalanche.org's centers and Avalanche Canada, in the official danger colours for
  today's highest rating (grey when expired or unrated), exactly as published; tap one
  for its three-band pyramid, problems and a link to the center.
- **Avalanche problems on the map.** The terrain today's listed problems describe
  (their aspects and elevation bands, steeper than 25, 30 or 35°) for the zone in the
  middle of the map, using approximate treeline bands from `config/treeline.yaml`,
  which the owner can override near a location.
- **Experimental concern index**, behind `HAZARD_INDEX` (owner only by default): the
  app's own estimate from the bulletin's rating for each band, slope angle, the listed
  problems, likely wind loading and sun, in four classes in a non-danger palette, with
  a one-time acknowledgement and a fixed caption. The Inspector shows every factor.
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
