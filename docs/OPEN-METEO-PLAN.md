# Snow Watch: self-hosted Open-Meteo plan (richer forecasts, a full forecast anywhere)

Status: **milestone 1 built** (27 Nov 2026): the opt-in `openmeteo` service, routing with
the public fallback, the usage ledger and budget split, `snowwatch openmeteo status` and
`check-sources --local`. **Milestone 1b built** (27 Nov 2026): PR 1, the opt-in
`openmeteo-ensembles` downloader (compose profile `ensembles`) and its status; PR 2,
`OPEN_METEO_ENSEMBLES` (`public` by default, `shadow`, `local`), per-system freshness,
fallback and shadow comparisons, `check-ensembles`. Both tested end to end in a sandbox;
the owner's rollout on the mini PC (a few days of downloads, a week of shadow, then
local) is next. **Milestone 2, backend built** (27 Nov 2026): `GET /api/spot` and
`/api/spot/nearby` (`snowwatch/spots.py`), checked against the real server in a sandbox;
the frontend PR is next. Milestones 3–5 are planned. Each milestone's PRs tick its
checklist here and update this line.

Research findings and an implementation plan for handoff. Every measurement below was
taken on 26–27 Nov 2026 from a cloud sandbox running the real Open-Meteo server against
the public data, replaying Snow Watch's own requests. To start a milestone in a new
session, see [Appendix C](#appendix-c-starting-a-milestone-in-a-new-session).

## Context

Every forecast number in Snow Watch comes from Open-Meteo: the multi-model consensus at
base, mid and summit, ensembles, freezing level, ridge wind and the loading rose,
avalanche weather, touring weather, ski-day ratings, push alerts, the map's 3D clouds,
the scorecard's forecast at the station, and elevation and time zone when a location is
added. NWS supplies only alerts and the forecast-office lookup; the map's weather layers
read NOAA and ECCC model grids directly; SNOTEL, the BC River Forecast Centre, NWAC and
Avalanche Canada supply observations and ratings.

The public Open-Meteo API allows **10,000 weighted calls a day** (5,000 an hour, 600 a
minute; a call counts more past 10 variables or 14 days). Each location costs about
**316 a day**: 8 runs × ~35 (blend 6.3, multi-model 18.5, upper air 8.1, clouds 2.4),
2 ensemble runs × ~11.8, and the station request ~1.2 per run. So `MAX_LOCATIONS` is 25,
the variable lists are kept lean, runs are 3 hours apart, and the worker waits 20 s
between locations (`site_spacing_s`).

Open-Meteo can be self-hosted: the server reads the public Open-Meteo data on AWS on
demand and caches what it reads (`REMOTE_DATA_DIRECTORY`), so no weather models need to
be downloaded up front. With that, every request except ensembles costs nothing.

### What the test found

| Check | Result |
|---|---|
| Columns we request (blend, multi, upper, clouds, station, elevation) | All present. `gfs_seamless`, `icon_seamless`, `gem_seamless`, HRRR, NBM, HRDPS and pressure levels work. The share of empty values per column matched the public responses in `backend/tests/fixtures/live-20261104/` for Crystal and Whistler; upper air had *fewer* gaps (the server keeps more past hours). |
| **Ensembles** | **Not served.** The public data holds only `precipitation_probability` for GEFS, ECMWF ENS and GEPS (`ncep_gefs025`, `ecmwf_ifs025_ensemble`, `cmc_gem_geps`), not per-member snowfall. Every member comes back empty. Ensembles stay on the public API. |
| First location, empty cache | 116 s, 213 MB downloaded (one-time setup per model and variable) |
| 34 more locations, empty cache | 157 s with 4 parallel requests, **~27 MB per location** |
| Same 36 locations again, cached | **4.8 s for all 36** (blend 0.3 s, multi 0.16 s, upper 0.04 s per request) |
| Slowest single request, empty cache | 52 s (`upper`, the first location) |
| Server memory | 143 MB; the cache is a memory-mapped file, reserved at its full `CACHE_SIZE` on disk |
| Background refresh while idle (36 locations cached) | ~35 MB every 5 min, ~10 GB/day (15 minutes measured; treat as rough) |
| `build_snapshot` | ~0.4 s and ~8 MB peak per location; document ~181 KB of JSON |
| Rows written per run | 132 `forecast_daily` rows per location |
| Raw responses kept for `rebuild` | ~100 KB gzipped per location per run |

**Model run times.** Each model's `https://openmeteo.s3.amazonaws.com/data/<model>/static/meta.json`
has `last_run_initialisation_time` and `last_run_availability_time` (Unix seconds).
HRRR and NBM update hourly; GFS, ECMWF, GEM, HRDPS and ICON every 6 h.

**History in the public data** (earliest data for `precipitation`): HRRR since
2017-12, GFS 0.11° since 2021-03, HRDPS since 2023-05, ECMWF 0.25° since 2024-01,
NBM since 2024-09. This is the start of each model run stitched together (short range).

**Hardware and licence.**
- Open-Meteo's docs ask for a CPU with AVX2 (x86) or ARM64, 8 GB RAM (16 recommended) and
  100 GB+ NVMe. Those figures are for downloading whole models; our on-demand use is far
  lighter.
- The server code is AGPL-3.0. We run it unmodified, which needs nothing from us. The
  data is CC BY 4.0, and our existing attribution covers it.

## Decisions at a glance

| Question | Decision |
|---|---|
| Self-host? | **Yes**: forecasts and elevation (M1), then ensembles too (M1b), with the public API as the fallback for both |
| Ensembles | **Downloaded by our own server** (M1b): GEFS, ECMWF ENS and GEPS, every run, 16 days, snowfall only. Opt-in like M1, and one setting returns to public ensembles |
| Where | **The mini PC** (`docs/deploy-notes-home.md`): Debian Docker VM, 4 cores, AVX2 enabled (CPU type `host`), 10 GB RAM, 60 GB disk (it can't grow: Home Assistant OS holds the rest of the 128 GB, and its disk can't shrink) |
| If the local server is down | Saved locations fall back to the public API within the daily budget; spots return 503 |
| Which upgrades | All six: forecast anywhere, model bias learning, more variables, faster refresh, more locations, richer ensembles; plus no delay between locations |
| Saved locations | **~50** (ensembles at all three bands, 4×/day) |
| Forecast for any clicked point | **Every visitor, rate-limited**, with a daily ensemble allowance |
| Turning it on | Opt-in (compose profile + `OPEN_METEO_URL`), so installs without AVX2 keep working and M1 can merge first |
| Bias correction | Scored live first; applied only when the scorecard shows it's closer |

## Hosting: the mini PC

- The Docker VM exposes AVX2 and has 4 cores and 10 GB RAM. Its 60 GB disk was **full** on
  27 Nov 2026 (293 MB free): M1's server had reserved its then-default 30 GB cache (the
  cache is reserved in full when the server starts), and Docker's build cache had grown
  to 16.8 GB because `deploy/deploy.sh` never cleared it. The cache default is now 10 GB
  (~27 MB per location was measured, so plenty for 50) and the deploy prunes build cache
  older than a week. After recreating the server with a 10 GB cache, 14 GB was used and
  44 GB free.
- **Disk budget with M1b (60 GB, can't grow):** ~14 GB today (images 3.7, `data/` 5.9,
  some build cache), up to 10 GB of server cache, ~1.5–2 GB of downloaded ensembles
  (measured in PR 1: 1.3 GB after one run of each, once the downloader deletes what the
  server doesn't read): about 26 GB used, ~34 GB free. Keep at least 15 GB free; M1b's
  `openmeteo status` warns under 10 GB and the downloader pauses under 5 GB.
- **Bandwidth:** ~300–450 GB/month for M1's forecasts, plus ~250–470 GB/month for M1b's
  ensembles. The owner confirmed the data cap isn't a concern.
- The `openmeteo` compose service is **opt-in**, behind the compose profile `openmeteo`. A
  machine without AVX2 never starts it (it would crash-loop with "Illegal instruction"),
  and merging milestone 1 changes nothing until it's turned on.
- **The owner's only manual step, once milestone 1 has deployed**, is two lines in `.env`:
  ```
  COMPOSE_PROFILES=openmeteo
  OPEN_METEO_URL=http://openmeteo:8080
  ```
  Then run `docker compose up -d`; `docker compose run --rm worker snowwatch openmeteo status`
  should report OK. The deploy timer (`deploy/deploy.sh`) handles everything after that.
- Everything new in milestones 2–4 switches on only when `OPEN_METEO_URL` is set:
  - spots ("Full forecast here" is hidden otherwise)
  - the extra variables (the public API keeps today's lean list)
  - data-driven refresh, no spacing, and the 50-location cap (otherwise the fixed 3-hour
    schedule and 25 locations)

  The repo keeps working for installs without the server.
- If the mini PC ever can't host it, set `OPEN_METEO_URL` to another machine instead. A
  small cloud VM in AWS us-west-2 (where the data lives) or in Oregon, reached over
  Tailscale, needs no other change.

---

## Milestone 1: Hybrid foundation

**Goal:** every forecast and elevation request goes to the local server, ensembles go to
the public API, and the app keeps working if the local server is down. **One PR.**

### Compose and settings
- [x] `docker-compose.yml`: an `openmeteo` service with `profiles: [openmeteo]`:
  - image `ghcr.io/open-meteo/open-meteo` pinned by digest. The one tested here was
    `sha256:bf94e8b39761b59a91bd04bb926b3834cad00eaf71f1aa64b2fd17fbe987846a`. Bumping it
    is a deliberate PR; say so in DEPLOYMENT.md.
  - `REMOTE_DATA_DIRECTORY=https://openmeteo.s3.amazonaws.com/data/`,
    `CACHE_SIZE=${OPEN_METEO_CACHE_SIZE:-30GB}`
  - a **named volume** `openmeteo-data:/app/data`. The image runs as a non-root user, and a
    root-owned bind mount failed with `cannotCreateFile ... cache.bin, errno 13`.
  - no published port; reachable only by `api` and `worker` on the compose network. The
    server listens on `0.0.0.0:8080` inside the container (`API_BIND` didn't change that
    in the test).
  - `mem_limit: 1g`, `restart: unless-stopped`
  - try `read_only`, `cap_drop: [ALL]` and `no-new-privileges` like the other services
    (`x-hardening`); keep what the image tolerates
  - add a healthcheck only if the image has a tool for one; otherwise
    `snowwatch openmeteo status` is the check
- [x] Raise the `api` service's `mem_limit` from 384m to 768m (spot builds, milestone 2).
- [x] `backend/snowwatch/settings.py`, `.env.example`, README configuration table:
  - `open_meteo_url: str = ""` (empty = public only)
  - `open_meteo_fallback: bool = True`
  - a property `local_open_meteo` (true when the URL is set) for the switches in
    milestones 2–4
  - `site_spacing_s` defaults to 0 when `local_open_meteo`, 20 otherwise
  - `max_locations` defaults to 50 when `local_open_meteo`, 25 otherwise (an explicit
    `MAX_LOCATIONS` wins). At today's ensemble schedule (mid only, 2 runs) 50 locations
    use ~1,200 public calls a day, well within the limit; milestone 4's planner takes over
    when ensembles get richer.

### Routing in the Fetcher (request builders unchanged)
- [x] `backend/snowwatch/http.py` `Fetcher`:
  - A rewrite map, applied in one place, swaps `https://api.open-meteo.com/v1/` for
    `{open_meteo_url}/v1/` (forecast and elevation). `https://ensemble-api.open-meteo.com/`
    is never rewritten.
  - **Fallback:** on a connection error, timeout or 5xx from the local server, retry once
    against the original public URL, only when `open_meteo_fallback` is on, the caller
    allows it (saved-location runs do; spots don't), and the public ledger has room. Count
    fallbacks per run and log them.
  - Timeouts: local requests 120 s (a cold `upper` took 52 s); public stays 40 s.
  - Per-host minimum spacing (~0.5 s) for api.weather.gov, NRCS AWDB
    (wcc.sc.egov.usda.gov) and the BC RFC, now that the 20 s pause per location is gone.
    The existing 429 handling stays.
  - `total_weight` counts only requests that reached a public Open-Meteo host; local
    requests are counted separately (requests, seconds) for the status page.
- [x] Construct the Fetcher with the settings in both places: `cli.py:_fetcher` and
  `scheduler.py:Worker._fetcher`. `sources/openmeteo.py`, `locations/resolve.py`,
  `checks.py`, `capture.py` and the fixtures stay untouched.

### Public usage ledger and budget
- [x] Migration `backend/snowwatch/store/migrations/009_api_usage.sql`:
  `api_usage(day TEXT, host TEXT, weight REAL, requests INTEGER, PRIMARY KEY (day, host))`,
  where day is the UTC date (the public limit resets daily).
- [x] `store/repo.py`: `add_usage(conn, day, host, weight, requests)` and
  `usage_today(conn)`. The worker adds its public weight when a run finishes
  (`pipeline.run_all`, next to `repo.finish_run`). The API adds its own for spots
  (milestone 2). Everything that spends public calls checks `usage_today` first.
- [x] Budget split:
  - `sources/openmeteo.py:daily_weight` → `public_daily_weight` (ensembles) and
    `local_daily_weight` (the rest)
  - `cli.py:cmd_budget` prints both plus today's actual public use
  - `api/admin.py` `/budget` (`BudgetOut`) returns both
  - the Manage budget panel in `frontend/src/lib/manage/` shows both

### Tools and status
- [x] `snowwatch check-sources --local` (`checks.py`): every model and variable on the
  local server, plus the empty-value comparison against the public API (when it answers)
  or the saved fixtures ([Appendix B](#appendix-b-how-the-server-was-checked)). Writes a
  section in `docs/SOURCES.md` like the existing check.
- [x] `snowwatch openmeteo status`: AVX2 present (`/proc/cpuinfo`), local latency for one
  small request, each model's last run from `meta.json`, today's fallbacks and public use.
- [x] `/api/status` (`api/public.py:status`, `StatusOut`) and
  `frontend/src/routes/status/+page.svelte`: local server OK and latency, fallbacks today,
  public ensemble use against 10,000.
- [x] `/api/meta` (`MetaOut`): `local_forecasts: bool`, which the frontend uses to show
  spots (milestone 2).

### Docs
- [x] `docs/DEPLOYMENT.md`:
  - the server and why it's opt-in
  - the two `.env` lines
  - hardware (AVX2, RAM, disk) and bandwidth
  - bumping the image
  - troubleshooting (`snowwatch openmeteo status`; "Illegal instruction" means no AVX2)
- [x] `docs/deploy-notes-home.md`: VM CPU type `host` (needed for AVX2), 10 GB RAM,
  60 GB disk.
- [x] `docs/ARCHITECTURE.md` (moving parts, a forecast run), `docs/SOURCES.md`,
  `THIRD_PARTY_NOTICES.md` (the AGPL server image, used unmodified), `CHANGELOG.md`.

### Tests (`backend/tests/`)
- [x] Rewrite only for api.open-meteo.com; ensembles untouched.
- [x] Fallback: local down → public. Budget spent → no fallback and an error. Fallback
  refused when the caller forbids it.
- [x] Weight counts only public calls; the ledger adds up across runs; per-host spacing.
- [x] Budget split; settings defaults with and without `OPEN_METEO_URL`.

**Done when:**
- Profile off: the site behaves exactly as today and CI passes.
- Profile on (mini PC):
  - a run logs public weight only for ensembles
  - stopping the `openmeteo` container makes the next run fall back and still succeed
  - `snowwatch budget` shows ~24 public calls per location per day

### What was built and found (27 Nov 2026)

Checked end to end in a cloud sandbox with the pinned image and the six seed locations
(`OPEN_METEO_URL=http://127.0.0.1:8080`), the same way as [Appendix A](#appendix-a-running-the-server-in-a-cloud-sandbox):
- **Cold run** (empty cache, `pull --ensembles`): 6/6 ok in 355 s (Crystal 150 s, the
  rest 29–66 s). Public weight 71: the 18 ensemble requests only. `snowwatch budget`:
  ~141 public calls a day for 6 locations, ~24 per location; ~1,620 self-hosted.
- **Warm run:** 6/6 ok in 17 s (0.4–4.4 s per location), no public calls.
- **Server stopped:** one refused connection, then all 27 forecast requests went to the
  public API and the run finished 6/6 ok (366 s from the sandbox's shared address);
  `openmeteo status` said NOT OK; the ledger showed 27 fallbacks.
- **Hardening:** the image runs with `read_only` (plus `/tmp` as tmpfs), `cap_drop: [ALL]`
  and `no-new-privileges`, so the service uses `x-hardening` like the others. The image
  has `curl`, so the service has a healthcheck (any HTTP answer from `/`, which is a 404).
- **GEM's folders moved:** `cmc_gem_gdps` and `cmc_gem_rdps` stopped in May 2026; the
  current ones are `cmc_gem_gdps_15km` and `cmc_gem_rdps_10km` (`checks.MODEL_FOLDERS`).
  Milestone 4's watcher list below is updated.

Choices made while building, beyond the checklist:
- `api_usage` also has `fallbacks` and `seconds`; the server is the host `local`, so the
  Status page's latency and fallbacks come from the same table.
- The server's own successes and errors are the source `open-meteo-local` in
  `source_status`, so it shows as its own row on the Status page.
- The server gets one try per request; after a connection error or timeout it's skipped
  for 5 minutes (`LOCAL_RETRY_AFTER_S`), so a stopped container costs one failed
  connection per run, not one per request. A 4xx from it is an error, not a fallback.
- With a server configured, every public Open-Meteo request (ensembles, fallbacks)
  checks the ledger first. Without one nothing is checked, so the site behaves as before.
- While a run is falling back, locations are 20 s apart again
  (`pipeline.FALLBACK_SPACING_S`): at 50 locations a full fallback would otherwise hit the
  public per-minute limit.
- Manage's auto-detect (`api/app.py`'s fetcher) uses the server too, with a 30 s timeout,
  and records its public calls in the ledger.
- The Manage budget panel is in `frontend/src/routes/admin/+page.svelte`.
- `.env.example` no longer sets `MAX_LOCATIONS=25`; an `.env` copied from the old one keeps
  25 until that line is removed (DEPLOYMENT.md says so).

## Milestone 1b: Self-hosted ensembles

**Goal:** ensembles come from our own server too, so neither saved locations nor spots
(milestone 2) depend on the public API's daily limit. The public API stays as the
fallback, and one setting returns to milestone 1's setup. **Two PRs: the downloader, then
the app.** Between them the owner runs the downloader alone for a few days on the mini
PC, then the app in shadow mode for about a week, before switching (see "Rollout").

### What the test found (27 Nov 2026)

Tested in a cloud sandbox with the pinned image ([Appendix D](#appendix-d-how-the-ensembles-were-tested)):
- **The public data can't do it, but the server can download ensembles itself.** Every
  ensemble folder in `openmeteo.s3.amazonaws.com/data/` holds only
  `precipitation_probability` (checked: GEFS, ECMWF ENS, GEPS, ICON-EPS, UKMO, BOM, AIFS,
  WeatherNext). The image's `download-gfs`, `download-ecmwf` and `download-gem` fetch a run
  straight from NOAA (AWS), ECMWF and Environment Canada and write per-member files
  (`rolling.om`), which the same server then serves at `/v1/ensemble`.
- **Same numbers as the public API.** For Crystal's mid band (46.935, −121.475, 1,800 m),
  every member's 16-day snowfall total against the public API for the same run: GEFS
  (`gfs_seamless`, 31 members, 384 h) max difference 1.5 cm, mean 0.5 cm; GEPS
  (`gem_global`, 21 members, 384 h) max 1.8 cm, mean 0.9 cm. Most of the difference is one
  missing first hour locally (383 h vs 384 h).
- **One server does both:** with `REMOTE_DATA_DIRECTORY` set it kept reading forecasts from
  the public data while serving the downloaded ensembles.
- **Only snowfall's inputs are needed**, which halves GEFS and cuts GEPS by 80 %:
  GEFS `precipitation,frozen_precipitation_percent` (the server works out
  `snowfall_water_equivalent`), ECMWF `snowfall_water_equivalent`, GEPS
  `snowfall_water_equivalent`. Results were identical without temperature.

| System (domain) | Download per run | Time | Peak memory | Source |
|---|---|---|---|---|
| GEFS 0.25° to 240 h (`gfs025_ens`) | 2.19 GB | 290 s | 586 MiB | measured |
| GEFS 0.5° to 384 h (`gfs05_ens`) | 1.06 GB | 219 s | 178 MiB | measured |
| ECMWF ENS 00z/12z to 360 h (`ifs025_ensemble`) | ~0.6 GB | ? | ? | from ECMWF's index files (6.9 MB of `sf` per step, 85 steps) |
| ECMWF ENS 06z/18z to 144 h | ~0.35 GB | ? | ? | same |
| GEPS to 384 h (`gem_global_ensemble`) | 0.26 GB | 115 s | ≤ 330 MiB | measured |

- **Disk:** 3.0 GB for one run of GEFS and GEPS, including ensemble-mean files the
  downloader also writes. Whether the folders grow from run to run wasn't measurable in
  one session.
- **CPU:** GEFS kept ~1.6 cores busy (of 4 in the sandbox) for its 8.5 minutes.
- **Two problems found:**
  - **ECMWF couldn't be downloaded from the sandbox.** `data.ecmwf.int` wasn't reachable,
    and the AWS mirror (`--source aws`) answered `SlowDown: Please reduce your request
    rate` even at one connection, probably because the sandbox shares its address. It
    must be tried from the mini PC before relying on it. (PR 1's sandbox downloaded it
    from `data.ecmwf.int` without trouble.)
  - **GEPS needed a workaround.** Environment Canada no longer publishes the
    `CMC_geps-raw_LAND_SFC_…` file this image expects, so the downloader retried forever.
    Copying `data/cmc_gem_geps/static/HSURF.om` from the public bucket into the volume
    first fixed it.

### What the app reads from ensembles (all of it must still come through)

`ensemble_request` asks each system for `hourly=snowfall` at the mid band's lat/lon/
elevation for 16 days, and that's all the app uses (`analysis/series.py:ensemble_members`
reads `snowfall` and `snowfall_memberNN`; `parse_point` reads `time`, `timezone` and
`utc_offset_seconds`). From those come: the ensemble range per period and running totals,
the pooled 10–90 % band, exceedance chances, the consensus after 48 h (ensemble mean),
`_scaled_ens_mean`, member totals, the Calendar's and Confidence tab's ensemble figures,
member counts shown in the app (GEFS 31, ECMWF 51, GEPS 21; `ensemble_min_members: 10`),
and `forecast_daily`'s `ens_p10`, `ens_p50` and `ens_p90` rows (the scorecard scores
`ens_p50`, so its record carries straight on across the switch). `snowfall` must stay
Open-Meteo's 7:1 conversion of snow water, since `build._swe` divides by
`snowfall_cm_per_mm`. `precipitation_probability` in the blend comes from the forecast
API (milestone 1, from the public data's folders), not from ensembles, so it isn't
affected. Milestone 4's ensembles at all three bands use the same variable. The checks
below compare whole snapshots, so nothing is missed by this list.

### PR 1: the downloader
- [ ] Prerequisite (owner, before adding the profile): at least 15 GB free on the Docker VM (`df -h /`); the 60 GB
  disk is enough (Hosting, "Disk budget").
- [x] `docker-compose.yml`: a service `openmeteo-ensembles`, compose profile `ensembles`:
  - the same pinned image as `openmeteo` (one digest, bumped together), `x-hardening`
  - the `openmeteo-data` volume, shared with the server, which serves what it writes
  - `mem_limit: 1g`, `cpus: 2` (half the mini PC, so forecast runs and the map's jobs
    keep their share), `restart: unless-stopped`. Built with 1536m: GEFS 0.25° peaked
    at 722 MiB with 2 CPUs.
  - entrypoint: `docker/ensembles.sh`, mounted read-only
- [x] `docker/ensembles.sh` (the image has `sh` and `curl`, no Python):
  - every 10 minutes, for each system, find the newest **complete** upstream run (GEFS:
    the last 0.5° file's `.idx` on `noaa-gefs-pds`; ECMWF: the last step's index; GEPS:
    hour 384 on `hpfx.collab.science.gc.ca`) and download it if it's newer than the last
    one done, one system at a time, with `--run`, `--concurrent 2` and the variables
    above
  - schedule: GEFS 4×/day (00/06/12/18z, both resolutions to 384 h), ECMWF ENS 4×/day
    (00/12z to 360 h, 06/18z to 144 h), GEPS 2×/day (00/12z: it only runs then)
  - ECMWF from `data.ecmwf.int` by default, `--source aws` if that fails; low
    concurrency, and back off for an hour after `SlowDown` or 503s
  - before the first GEPS download, copy `HSURF.om` from the public bucket if missing
  - a status file in the volume (`ensembles/status.json`): per system, the last run done,
    when, how long, ok or the last error
  - prune what grows (ensemble-mean and chunk files older than a few days; never the
    `rolling.om` files being served), once that growth is measured
- [ ] Verify on the mini PC (the owner, during the first few days; see "What PR 1 built
  and found" for what the sandbox already showed):
  - [x] the **running** `openmeteo` server picks up a new run written while it runs, with
    no restart (shown in the PR 1 sandbox)
  - [x] ECMWF ENS downloads cleanly, with all 51 members (50 perturbed plus the control)
    (shown in the PR 1 sandbox, from `data.ecmwf.int`; confirm from the mini PC)
  - [ ] a week's disk growth (`ensembles/disk.log` in the volume, a line a day) and
    bandwidth (the router's counter)
  - [ ] memory and CPU next to a forecast run and the map's jobs (`docker stats`)
- [x] `snowwatch openmeteo status`: each system's last downloaded run and its age (from the
  volume's `<domain>/static/meta.json` and `status.json`, read through a read-only mount
  of the volume at `/openmeteo` in `worker` and `api`), the downloader's last error, and
  free disk with a warning under 10 GB.
- [x] Docs: DEPLOYMENT (the profile, the disk, the bandwidth, turning it off),
  deploy-notes-home, ARCHITECTURE, THIRD_PARTY_NOTICES (NOAA, ECMWF open data under CC BY
  4.0, ECCC), CHANGELOG.

### What PR 1 built and found (27 Nov 2026)

Run end to end in a cloud sandbox (4 cores, the pinned image, `docker/ensembles.sh` in a
container hardened like the compose service: `read_only`, `cap_drop: [ALL]`,
`no-new-privileges`, 2 CPUs), next to the server with `REMOTE_DATA_DIRECTORY` set:
- **One pass, all four downloads** of the 00z runs, one at a time, in 20 minutes:

  | Download | Time | Downloaded | On disk as written | On disk kept |
  |---|---|---|---|---|
  | GEFS 0.25° (`gfs025_ens`) | 205 s | ~2.2 GB | 1.5 GB | 0.34 GB |
  | GEFS 0.5° (`gfs05_ens`) | 187 s | ~1.1 GB | 0.54 GB | 0.12 GB |
  | ECMWF ENS (`ifs025_ensemble`, `data.ecmwf.int`) | 689 s | 0.92 GB | 0.79 GB | 0.77 GB |
  | GEPS (`gem_global_ensemble`) | 77 s | 0.25 GB | 0.08 GB | 0.07 GB |

  Peak memory 722 MiB (GEFS 0.25°, both CPUs busy while converting).
- **A second pass on top** (GEFS 06z, ECMWF 06z, GEPS 12z, 17:25 UTC): 324, 229, 499 and
  116 s, and the kept files grew by 18 MB in all (1.30 → 1.32 GB). After ECMWF's 06z run
  (144 h) its `meta.json` said the data ends ~140 h ahead, yet the server's answer still
  reached 342 h: the rolling file keeps the 00z run's later hours.
- **ECMWF works from `data.ecmwf.int`** this time (no `SlowDown`), with all 51 members,
  reaching 351 h ahead at 09:30 UTC.
- **The running server picks up each new run**: it answered GEPS with empty members, then
  with the 12z run as soon as that download finished, then with the 00z run, without a
  restart. It rereads its folders every few seconds (`OmFileSystemLocal`, by inode).
- **Same numbers as the public API again** for Crystal's mid band, same runs: GEFS mean
  0.50 cm, max 1.50 cm; GEPS mean 0.83 cm, max 1.82 cm (member 16-day totals).
- **What grows, and what's kept.** Members go into one `rolling.om` per variable, which
  each run rewrites keeping 3 past days (`useRollingDays`): GEPS grew 1 MB from the 12z to
  the 00z run. But the downloaders also write files the server never reads for
  `snowfall` (which is `snowfall_water_equivalent` × 0.7 alone): GEFS's `precipitation`
  input (1.3 GB for both resolutions), GEFS `precipitation_probability` chunks, and
  every `*_ensemble_mean` folder, whose time chunks (18–60 days each) would pile up. The
  script deletes those after each run; the server's answers for all three systems were
  byte-for-byte the same before and after. That keeps 1.3 GB instead of 2.9.
- **The forecast API's `precipitation_probability`** reads the GEFS folders' probability
  files; a local copy (from our first run on, no past days) would hide the public one.
  Deleting it keeps milestone 1's blend exactly as it was (checked: 3 past days, no gaps).
- **GEPS** still needs `HSURF.om` copied from the public data first; the script does it.

Choices made while building, beyond the checklist:
- ECMWF uses `--concurrent 1 --download-concurrent 2`; it alternates between ECMWF's own
  server and the AWS mirror after each failure.
- A download is stopped after 2 hours (`timeout`; the GEPS land-file problem made the
  downloader retry forever). A failure is retried after 30 minutes, after an hour when
  the output says `SlowDown`, 429 or 503.
- `GENERATE_PREVIOUS_DAY=false`: no "previous day" copies of time chunks.
- Below `ENSEMBLES_MIN_FREE_GB` (5) free, runs are skipped and the status file says so;
  `openmeteo status` says NOT OK under 10 GB free (only for disk: a stalled downloader
  costs nothing while the app uses public ensembles).
- The downloaders' verbose output goes to `ensembles/<system>.log` in the volume (the
  last run's only), with one line per download in `docker logs`, which is also capped
  (`json-file`, 2 × 5 MB). `ensembles/disk.log` keeps a line a day for 90 days.
- `deploy/deploy.sh` restarts the downloader when `docker/ensembles.sh` changes (it's a
  bind mount, so `up -d` doesn't see a new script).
- `snowwatch/ensembles.py` reads the volume (`OPEN_METEO_DATA_DIR`, default `/openmeteo`)
  and holds the system list PR 2's freshness check uses: the app's `models` name →
  folders (`gfs_seamless` → `ncep_gefs025` + `ncep_gefs05`, `ecmwf_ifs025` →
  `ecmwf_ifs025_ensemble`, `gem_global` → `cmc_gem_geps`).

### PR 2: the app uses them
- [x] `settings.py`: `OPEN_METEO_ENSEMBLES` = `public` (default: milestone 1, unchanged) |
  `shadow` | `local`, used only when `OPEN_METEO_URL` is set.
- [x] **Freshness per system**, so a stalled downloader can't serve old runs as new:
  - a system is *fresh* when its local run is no older than two of its cycles (GEFS
    14 h, ECMWF ENS 14 h for any run and 26 h for a 00z/12z run, GEPS 26 h), read from
    the volume's `meta.json`
  - and its response reaches at least as far ahead as expected (GEFS and GEPS ≥ 360 h,
    ECMWF ≥ 336 h from now); a shorter reach counts as a failure
- [x] **Routing** (`http.py`): in `local` mode, `ensemble-api.open-meteo.com/v1/ensemble`
  is rewritten to the server only for fresh systems (the system is the request's
  `models`); otherwise, or on a failure, the public URL, under the ledger, as in
  milestone 1. Each system falls back on its own.
- [x] **What happens when ensembles fall back** (written down, and tested):
  1. the cached ensembles (`ensemble_cache`, up to `ensemble_max_age_h`, 13 h) cover a
     short outage at no cost
  2. then the public API, on the public schedule (`ensemble_runs_utc`, mid band only):
     50 saved locations × ~24 = ~1,200 calls a day, well within the limit on its own.
     If the whole server is down, forecasts fall back too (~316 per location a day,
     ~15,800 at 50 locations), which is more than the limit allows, so the ledger
     **reserves** for the required forecasts (blend and multi-model) first: ensembles are
     asked for only while today's public use is under the limit minus what the remaining
     runs' forecasts need (~35 per location per run). Past that, runs use the cached
     ensembles or none, and a run's optional requests (upper air, clouds, station) are
     skipped before the required ones. The budget planner (milestone 4) does the same
     sums when it exists.
  3. spots (milestone 2) get public ensembles only within the spot allowance (2,000 a day,
     ≈ 170 new points, each cached 6 h per cell), then build without them and say so
  4. a forecast without ensembles still builds (they're optional today)

  The Status page and `openmeteo status` say which systems are falling back and since
  when, and the worker logs it once per run.
- [x] **Schedule:** while a system is fresh, every run reads it (free); `ensemble_runs_utc`
  applies only to public ensembles.
- [x] **Budget:** systems served locally cost 0 in `public_daily_weight`, `snowwatch
  budget`, Manage and `/api/status` ("Ensembles: self-hosted").
- [x] **Shadow mode** (`shadow`): the app keeps using public ensembles as today, and each
  run also asks the server and records the comparison per location and system in a new
  table `ensemble_shadow` (migration `010_ensemble_shadow.sql`; milestone 2's
  `spot_ensembles` becomes 011): members (local / public), reach, and the mean and largest
  difference of member 16-day totals. The Status page summarises the last 7 days.
- [x] **Whole-snapshot check:** `snowwatch check-ensembles` builds each location's snapshot
  twice from one run's responses, once with local ensembles and once with public ones,
  and lists every ensemble-derived field that differs (ranges, bands, exceedance, member
  totals, the consensus after 48 h, Calendar and Confidence figures), with how much.
- [x] `snowwatch check-sources --local` gains the ensemble comparison (members, reach,
  differences against the public API or saved fixtures) in its SOURCES.md section.
- [x] Tests: routing only for fresh systems; one stale system falls back alone; a short
  reach counts as a failure; the fallback order above, including the reserve when the
  whole server is down; the budget with local ensembles;
  shadow records; `public` mode is exactly milestone 1 (the existing tests pass
  unchanged).

### What PR 2 built and found (27 Nov 2026)

Run against the sandbox's server and downloaded runs with two seed locations:
- **`local`:** Crystal and Whistler built with every system from the server (GEFS 31,
  ECMWF 51, GEPS 21 members through to the Calendar's running totals), **0 public
  calls**; `snowwatch budget` "about 0 of 10000", "ensembles: self-hosted (GEFS, ECMWF
  ENS, GEPS)"; `openmeteo status` lists each system as self-hosted since the run.
- **`shadow`:** each public ensemble the run fetched was also asked of the server and
  recorded. It showed why runs must match: the public API was still on ECMWF's 26 Nov
  12z long run (18z short run) while the server had 27 Nov 00z, and the members' totals
  differed by up to 95 cm. So each record also carries the public data's run (the public
  bucket's `<folder>/static/meta.json`; it named ECMWF 18z and GEFS and GEPS 00z here,
  matching what the API served), and the Status page counts differences only over
  comparisons of the same run ("Same run"). Ends of the answers can't stand in for the
  run: the public API's GEFS and GEPS went 7 h past the 16-day horizon for the same run.
- **`check-ensembles`** on Crystal listed every field that moved; with ECMWF on different
  runs it flagged the 6–10 day ensemble figures (up to 2 cm) and the sorted member
  totals (up to 6.6 cm), as expected. Its report now names both runs per system.
- The public API answered this sandbox with 429 after a few calls, so a week-long shadow
  comparison can only happen on the mini PC.

Choices made while building, beyond the checklist:
- Freshness reads only the run's age from `meta.json`; the reach is checked on each
  answer instead, because ECMWF's `data_end_time` follows its latest run, which at 06/18z
  stops at 144 h while the rolling file still holds the 00/12z run's later hours. An
  answer reaching 336 h also means a 00/12z run no older than ~24 h, which covers the
  "26 h for a 00z/12z run" rule.
- An unusable answer from the server (missing members, short reach, a 4xx) falls back
  like a failed connection, without skipping the server for 5 minutes. Ensembles fall
  back whatever `OPEN_METEO_FALLBACK` says (public is their usual source); their public
  retries count as fallbacks in the ledger but don't trigger the 20 s spacing, which is
  for forecasts falling back.
- The reserve is the rest of today's runs' blend and multi-model weight (this run
  included), held back only while forecasts are falling back and only in `shadow` and
  `local`, so `public` stays exactly milestone 1. It applies to every optional request.
- `ensemble_state` (in migration 010 with `ensemble_shadow`) records each system's
  source after each run and since when; `ensemble_shadow` is pruned after 90 days.
- To keep one system public (e.g. ECMWF if it fails the checks), leave it out of
  `ENSEMBLES_SYSTEMS`; its run goes old and it falls back on its own.
- Step 3 of the fallback order (spots and their allowance) arrives with milestone 2,
  which has no spots to route yet; its `spots.py` should call `Fetcher.local_ensemble`
  per system and use the allowance only for the rest.

### Switching on, and when to switch
- **Accurate means**, from a week of shadow mode on the mini PC, over comparisons of the
  same run (the Status page's "Same run"): the same member count for every system; reach no shorter than the public API's by more than 6 h; member
  16-day totals within 1 cm on average and 3 cm at most (the test gave 0.5–0.9 and 1.8);
  `check-ensembles` shows no ensemble field in a snapshot moving by more than 1 cm or 2
  percentage points. If ECMWF fails these, switch the other two and keep ECMWF public
  (about half of today's ensemble calls) until it passes.
- **Rollout:**
  1. PR 1 deploys; owner adds `ensembles` to `COMPOSE_PROFILES`; a few days of downloads
     only; check disk, bandwidth, memory, ECMWF and the running server picking up runs
  2. PR 2 deploys; `OPEN_METEO_ENSEMBLES=shadow` for about a week
  3. if the numbers above hold, `OPEN_METEO_ENSEMBLES=local`
- **Turning it back** (any time, nothing lost): `OPEN_METEO_ENSEMBLES=public` and take
  `ensembles` out of `COMPOSE_PROFILES`, then `docker compose up -d --remove-orphans`.
  That is milestone 1 exactly: public ensembles on their schedule, under the ledger.
  Nothing in this milestone removes or changes the public-ensemble code: the request
  builders, `ensemble_cache`, the ledger, the schedule and their tests stay, `public`
  stays the default, and the new tables are only added to. The downloaded runs can be
  deleted from the volume, or left.

### Extended forecasts and more runs
- Keep 16 days: GEFS 0.25° to 240 h plus 0.5° to 384 h, ECMWF ENS to 360 h, GEPS to
  384 h, as the public API gives today.
- Download every run each system makes (above). At that schedule ensembles cost ~15 GB a
  day (GEFS 13, ECMWF 1.9, GEPS 0.5), ~470 GB a month, fixed however many locations or
  spots there are.
- To revisit once it runs: whether days 11–16 are used anywhere (milestone 4's question;
  GEFS 0.5° is a third of the download), and GEFS 4× vs 2× a day.

**Done when:** a week in `local` mode on the mini PC with ensembles from the server for
every system that passed, `snowwatch budget` showing ~0 public ensemble calls, disk steady,
and a stopped downloader making the stale systems fall back to the public API with every
run still succeeding.

## Milestone 2: Forecast anywhere

**Goal:** tap any point in the US or Canada on the map and get the same forecast page a
saved location has, built on demand. **Two PRs: backend, then frontend.**

### Backend: `backend/snowwatch/spots.py` (new)
- [x] **Bands from the terrain:** one request to the local `/v1/elevation` gets the point
  plus 24 samples on rings at 1 km and 2.5 km (12 bearings each). With h = the point's
  elevation and lo/hi = the ring's lowest and highest:
  - near the top (h ≥ hi − 100 m): summit = h, base = lo, mid = base + 60 % of the vertical
    (`MID_SHARE`, `locations/resolve.py`)
  - near the bottom (h ≤ lo + 100 m): base = h, summit = hi, mid = 60 % up
  - otherwise: base = lo, mid = h, summit = hi
  - Keep bands at least 150 m apart; on flat ground use h − 300, h, h + 300.
  - The band holding the click is "this spot" and opens by default. All three bands share
    the clicked lat/lon; only elevation differs, as a resort's single pin does today.
- [x] **Country:** point-in-polygon against a bundled, simplified US/Canada border
  (`config/borders.geojson`, from Natural Earth admin-0 at 1:50m, public domain, a few
  hundred KB at most), using `geo.contains`. Outside both: 422 "Forecasts anywhere cover
  the US and Canada". `Location.country` stays `Literal["US", "CA"]`, and it picks the
  short-range models (`cfg.models_for`).
- [x] **Transient `Location`:**
  - `id = "spot-" + geohash(7)` (fits the id pattern), `kind = "backcountry"`, `tz = None`
    (the build takes the time zone from the response, as it does for a new location)
  - Name, first that applies:
    1. the nearest named peak within 2 km from `data/osm/ski.geojson`, which only covers
       areas around saved locations
    2. "6 km NE of Crystal Mountain" from the nearest saved location within 40 km
    3. the coordinates
- [x] **Fetch:** factor the Open-Meteo part of `pipeline.fetch_responses` into a helper.
  Spots reuse `blend_request`, `multimodel_request`, `upper_air_request` and
  `clouds_request` against the local server (no fallback), and skip the station request,
  SNOTEL, BC data and the ensemble cache table. US spots get NWS alerts
  (`nws.alerts_request`), cached 10 min per 0.1° cell.
- [x] **Ensembles:**
  - With milestone 1b in `local` mode and a system fresh: from the server, at all three
    bands, with no allowance.
  - Otherwise mid band only, from the public API (`ensemble_request` for each of
    `cfg.ensembles`), under a daily **spot allowance** checked against the ledger
    (default 2,000 weighted calls/day ≈ 170 new point ensembles, set in
    `config/forecast.yaml`).
  - Cached 6 h per 0.25° cell and 100 m elevation step in a new table `spot_ensembles`
    (migration `011_spot_ensembles.sql`, after milestone 1b's 010), which also bounds the
    server's CPU.
  - When the allowance is spent, build without ensembles (they are already optional) and
    say so in `Snapshot.spot`.
- [x] **Build:** `inputs_from_responses` then `build_snapshot`, unchanged; neither touches
  the database.
- [x] `backend/snowwatch/doc.py`: a new optional `Snapshot.spot` (`SpotInfo`) with:
  - the clicked lat/lon/elevation and `band` (which band is "this spot")
  - how the bands were chosen (`top` / `bottom` / `slope` / `flat`)
  - `ensembles`: `fresh` / `cached` / `allowance_spent`
  - the nearest saved location (id, name, km)
- [x] **Endpoints** (`api/public.py`):
  - `GET /api/spot?lat=&lon=`: the snapshot, gzipped like `/locations/{id}`, with an ETag;
    422 outside the US/Canada; 503 when the local server isn't configured or is down
  - `GET /api/spot/nearby?lat=&lon=`: refactor the body of `nearby(location_id)` into
    `nearby_at(lat, lon, elev_m)`, shared by both routes; add the avalanche zone and its
    current rating via `zone_at` + `avalanche_views`
- [x] **Limits and cache** (patterns from `api/ratelimit.py` and `api/app.py`):
  - an in-process LRU (~300 entries) of gzipped documents keyed by lat/lon rounded to 3
    decimal places (~100 m), valid until the next model update (milestone 4's watcher
    stamp; 60 min until then)
  - uncached builds: per visitor `RateLimiter(rate=1/15, burst=8)`, at most 2 at once
    (a semaphore), at most ~600 an hour site-wide; cached hits use a lighter limiter
  - builds run in FastAPI's thread pool (sync endpoint)
  - the API makes outbound requests here for the first time: to `openmeteo`, NWS alerts
    and the public ensemble API. Note it in `docs/ARCHITECTURE.md` ("Public endpoints are
    bounded") and `SECURITY.md`.

### Frontend (SvelteKit)
- [ ] Extract `frontend/src/lib/components/LocationView.svelte` from
  `frontend/src/routes/location/[id]/+page.svelte` (1,420 lines):
  - props: `snap`, plus optional loaders for trend, verification, nearby and avalanche
  - sections a spot can't have (trend, scorecard, webcams) are hidden
  - the location route becomes a thin wrapper
- [ ] New route `frontend/src/routes/spot/+page.svelte` at `/spot?lat=..&lon=..`
  (shareable):
  - header with name, coordinates and elevation; a "This spot" badge on the matching band
    (default band = the spot's)
  - a one-line note: "Forecast for this spot, made now. No snow station history or forecast
    trend here."
  - tabs: Forecast; Confidence (no scorecard or trend); Backcountry (the zone's rating when
    inside one); Observed (nearest stations from `/api/spot/nearby`; model snowpack after
    milestone 3)
  - loading skeletons while a cold area takes up to ~10 s
- [ ] Map: a **"Full forecast here"** button in `frontend/src/lib/map/Inspector.svelte`
  (the "This spot" panel), and a long-press / right-click action in
  `frontend/src/lib/components/MapView.svelte`. Hidden unless `/api/meta` says
  `local_forecasts`.
- [ ] `frontend/src/lib/api.ts`: `getSpot(lat, lon)`, `getSpotNearby(lat, lon)`.
- [ ] Owner only: **"Save as location"** opens Manage with a pin prefilled (the existing
  `resolveLocation` flow in `frontend/src/lib/manage/`).
- [ ] **Recent spots:** the last 10 in localStorage (wrapped in try/catch), on the
  Overview (`frontend/src/routes/+page.svelte`) and in `LocationPalette.svelte`.
- [ ] Service worker (`frontend/src/service-worker.ts`, `frontend/src/lib/swRoute.ts`):
  network-first for `/api/spot`, keeping the last 10 for offline use.
- [x] Regenerate types: `uv run snowwatch schema --out ../frontend/src/lib/api-schema.json`,
  then `npm run types`.

### Tests
- [x] Band rule (top, bottom, slope, flat), border lookup (inside, outside, near the
  border), naming fallbacks, cache keys, rate limits, allowance spent, and a spot built
  from the saved fixtures (`tests/helpers.py`).
- [ ] Playwright (`frontend/e2e/`): map tap → "Full forecast here" → spot page at 380 px
  and desktop, in light and dark themes. The e2e API serves `/api/spot` from fixtures.

**Done when:** on the mini PC, tapping any point in the US or Canada opens a full forecast
in ≤ 3 s warm (≤ 10 s in a cold area), and repeat taps nearby are instant.

### What the backend PR built and found (27 Nov 2026)

Run against the pinned server in a cloud sandbox ([Appendix A](#appendix-a-running-the-server-in-a-cloud-sandbox),
empty cache to start, `OPEN_METEO_ENSEMBLES=public`), with `curl` on `/api/spot`:
- **Snoqualmie Pass** (47.42, −121.41): "Near Snoqualmie Pass", slope, bands 766 / 916 /
  1,429 m, all three ensembles. **Mount Rainier** (46.85, −121.76): "24 km SW of Crystal
  Mountain", top, summit 4,366 m (the peak is 4,392 m), bands 2,871 / 3,768 / 4,366 m.
  Sonora (31, −110): 422 in 50 ms.
- **Cold:** the server's very first requests (empty cache, every model and variable to
  set up) took 133 s, 159 s for the next area and 325 s for Rogers Pass (Canada's models
  for the first time); one cold `upper` passed 60 s and was dropped as optional. That is
  the one-time setup measured in "What the test found"; on the mini PC the saved
  locations keep the models warm, and only a new area's ~27 MB is cold.
- **Warm areas, new points:** 1.3–5.9 s here (Rogers Pass again 1.3 s, Snoqualmie
  neighbours 2.4–4.9 s, Rainier's west flank 5.9 s); this sandbox is far from the data in
  us-west-2. **Repeat taps** within ~100 m: 2 ms, from the cache.
- **The public ensemble API answered 429** to this sandbox's shared address after a few
  calls. With 2 tries a 429 held a build for over a minute, so spots try public hosts
  once (`tries=1`): the spot then builds without them ("unavailable"), as it should.
- The document is 25–33 KB gzipped, like a saved location's.

Choices made while building, beyond the checklist:
- **Ensembles at the mid band only**, from the server too: `build_snapshot` reads one
  ensemble point per system and scales it to the other bands. Milestone 4 makes each
  band use its own ensembles; spots should ask for all three bands then.
- A spot is built at the point rounded to 3 decimals (~100 m), which is also its cache
  key, so the coordinates it reports are those. Ensembles are asked for at the 0.25°
  cell's centre and the 100 m step of the mid band, so the cached answer is the same for
  every spot that shares it. `spot_ensembles` drops rows past 6 h whenever it writes.
- `SpotInfo.ensembles` has a fourth value, `unavailable` (none could be had, e.g.
  the public API failed), beside
  `fresh`, `cached` and `allowance_spent`; `nearest` is the nearest saved location
  within 100 km.
- Band labels: "Lower", "Middle", "Upper", with the point's band labelled "This spot".
  Within 1 km of a saved location the name is "Near Crystal Mountain".
- The US/Canada outline counts points within 3 km of it as inside (its coastline is
  simplified); `backend/scripts/make_borders.py` remakes `config/borders.geojson` (278 KB).
- Spots' public calls go in `api_usage` as the host `spots`: counted in the public
  total like any host, and read on their own for the allowance.
- The server gets one try per request with a 60 s timeout (a cold summit request took
  52 s); after a failure the service answers 503 at once for 30 s.
- `NearbyOut` gains `zone_id` and `avalanche` (the zone's forecast with expiry applied
  now, from the map's zones file), filled for spots only; `location_id` is the spot's id.
- Limits as planned: per visitor 8 new spots then one every 15 s, cached ones 60 then 2 a
  second, 2 builds at once (others wait up to 20 s, then 503), ~600 an hour site-wide
  (bursts of 100), one build per point at a time.

## Milestone 3: Richer weather variables and better physics

**Goal:** use the variables we couldn't afford before, so rain/snow, snow ratio, freezing
rain, sun and ridge wind improve for saved locations and spots alike. **Two PRs: data and
analysis, then UI.**

### Data
- [ ] First run `snowwatch check-sources --local` to get the exact API names and which
  models have each variable; record the answers in `docs/SOURCES.md`.
- [ ] `backend/snowwatch/sources/openmeteo.py`: extend the lists only when
  `local_open_meteo` (the public API keeps today's):
  - `BLEND_HOURLY` and `MULTI_HOURLY` add: `relative_humidity_2m`, `dew_point_2m`,
    `wet_bulb_temperature_2m`, `shortwave_radiation`, `direct_radiation`,
    `diffuse_radiation`, `snow_depth`, `cape`
  - `UPPER_HOURLY`: levels 850, 800, 750, 700, 650, 600, 500, each with temperature, wind,
    geopotential height and `relative_humidity`
  - model-specific fields where present: NBM snow level and snowfall/freezing-rain
    probabilities, GFS/HRRR freezing-rain flag, ECMWF precipitation type
  - Missing variables are tolerated, as today.
- [ ] Capture new fixtures from the local server:
  `snowwatch capture-fixtures --out backend/tests/fixtures/live-<date>/`. The old fixtures
  must keep passing, since every new field is optional.

### Analysis (`backend/snowwatch/analysis/`)
- [ ] **Snow level from wet-bulb** (new `snowlevel.py`):
  - the height where wet-bulb temperature crosses 0 °C per model, from pressure-level
    temperature and humidity (surface wet-bulb as the bottom)
  - snow level = that height − ~150 m (config)
  - used instead of "freezing level − 305 m" where the data allow, falling back to it
    otherwise (`freezing.py`, `snow_level_offset_m`)
  - hourly precipitation type uses surface wet-bulb (snow ≤ 0.5 °C, rain ≥ 2 °C, mix
    between) instead of `slr.SNOW_MAX_C`; thresholds in config
- [ ] **Column snow ratio** (`slr.py`):
  - a ratio from the warmest temperature between the surface and 500 hPa while it snows
    (the ratio bands as today), lowered for strong wind at the surface (config)
  - a new `depth_method: column` and a new scored source `cons_col` beside `cons` and
    `cons_slr` in `verify.py` and `forecast_daily`
  - the owner switches the headline method once the scorecard shows it's closer
- [ ] **Freezing rain and sleet:** a layer above 0 °C aloft over a sub-freezing surface,
  plus the models' freezing-rain flags. Adds a `freezing_rain` flag in `flags.py` and a
  push alert type in `push.py` (with `push_log` dedup).
- [ ] **Sun on slopes:**
  - a small solar-geometry function (sun position from time and lat/lon; no new
    dependency) plus the direct and diffuse radiation give the sun on N/E/S/W slopes
    at ~35°
  - a "sun" factor line in the avalanche-weather outlook (`backcountry.py`
    `factor_levels`, labelled an estimate like the others; thresholds in
    `BackcountryConfig`)
  - a spring "corn window" in touring weather: when sunny aspects soften after a good
    refreeze
- [ ] **Ridge wind** (`ridge.py`): interpolate between the two levels that bracket the
  ridge height, out of six.
- [ ] **Model snowpack:** model `snow_depth` on the Observed tab where there's no station
  (every spot), and as a line next to the station's depth where there is one.
- [ ] **Humidity in touring weather** (`backcountry.sky`): rime/icing (high humidity
  between −10 and 0 °C at the ridge) and fog/flat light (humidity with low cloud and
  visibility).

### UI
- [ ] New rows in `frontend/src/lib/components/BandTable.svelte`,
  `frontend/src/lib/charts/PeriodSheet.svelte` and `DaySheet.svelte` (wet-bulb, how the
  snow level was found, freezing rain).
- [ ] A snow-level line on `frontend/src/lib/charts/ForecastChart.svelte`.
- [ ] The sun factor in `frontend/src/lib/backcountry/`; model snowpack in
  `frontend/src/lib/observed/`.
- [ ] Regenerate types.

### Tests
- [ ] Unit tests: wet-bulb zero height, the warm layer, column ratio, solar geometry
  (against known sun positions), ridge interpolation, the freezing-rain flag on a crafted
  case.
- [ ] The snapshot stays under ~300 KB of JSON (test on the new fixtures).

**Done when:** snapshots carry the new fields; the scorecard lists `cons_col`; the
freezing-rain flag fires on the crafted case; the outlook shows sun on aspects.

## Milestone 4: Fresher and wider

**Goal:** refresh as soon as models update, grow to ~50 locations, and run ensembles at
every band. **Three PRs: refresh + retention; ensembles + budget planner; locations + UI.**

### Refresh when new data lands
- [ ] New `backend/snowwatch/modelwatch.py`:
  - every 5 min, read `meta.json` for each model in use (bucket names: `ncep_hrrr_conus`,
    `ncep_nbm_conus`, `ncep_gfs013`, `ncep_gfs025`, `ecmwf_ifs025`, `dwd_icon`,
    `cmc_gem_gdps_15km`, `cmc_gem_rdps_10km`, `cmc_gem_hrdps`; `checks.MODEL_FOLDERS`
    has them. The older `cmc_gem_gdps` and `cmc_gem_rdps` stopped in May 2026)
  - when a model's `last_run_availability_time` advances, schedule a run ~5 min later
    (time for the local server to preload) for the locations that use it (the US set or
    the CA set, from `cfg.models_for`)
  - at most one run per 40 min per location; at least one every 3 h
- [ ] `scheduler.py`:
  - config `schedule.refresh: data | fixed` in `config/forecast.yaml`; `data` only when
    `local_open_meteo`
  - `runs_utc` stays as the `fixed` schedule
  - the spot cache (milestone 2) expires on the watcher's stamp
- [ ] New `Snapshot.model_runs` (model → initialisation time): "GFS 18z · ECMWF 12z ·
  HRRR 22z" on the Confidence tab and status page.

### Faster runs
- [ ] `pipeline.run_all`: fetch locations in a pool of 4 threads; database writes stay on
  the calling thread.
- [ ] A refresh interval per source: SNOTEL daily every 6 h; SNOTEL hourly, NWS alerts and
  the BC CSV each run.
- [ ] Split runs into per-location steps so queued Manage jobs (`process_jobs`) don't wait
  behind the whole run's lock; revisit `RUN_TIME_BUDGET_S`.
- [ ] Target: 50 locations in under 5 minutes.

### Retention
- [ ] `store/repo.py`: `SNAPSHOTS_KEPT` from 8 to 24.
- [ ] `store/retention.py`: after 48 h, keep `forecast_daily` runs at least 6 h apart, plus
  the last run before each local midnight (the scorecard's run, `verify.py`). Otherwise
  hourly runs add ~150k rows a day at 50 locations. The trend already picks runs 6 h apart
  (`api/public.py:_spaced_runs`).
- [ ] `http.py:prune_raw`: raw responses from 24 h to 6 h.
- [ ] `push.py`: test digest frequency with hourly runs; add a 3 h minimum per device for
  non-urgent digests if repeats show up.

### Richer ensembles
With milestone 1b in `local` mode these cost nothing; the budget planner below applies
only to systems on the public API (milestone 1b off, or falling back).
- [ ] `sources/openmeteo.py:ensemble_request` takes all three bands as one request with
  three coordinates (weight × 3).
- [ ] `analysis/build.py`: each band uses its own ensemble statistics; `_scaled_ens_mean`
  (mid scaled by the deterministic models) stays as the fallback.
- [ ] Schedule per system in `config/forecast.yaml` (`ensemble_runs`): GEFS and ECMWF ENS
  4×/day, GEPS 2×/day (it runs 00/12z only), each timed after it usually becomes
  available. Replaces `ensemble_runs_utc`.
- [ ] Check whether ensemble days 11–16 show anywhere (Calendar, Confidence). If not,
  request 11 days instead of 16 (−12 % weight).

### Budget planner
- [ ] New `backend/snowwatch/budget.py`. For the systems on the public API (all of them
  without milestone 1b), it picks the richest ensemble tier that fits 90 % of 10,000 minus
  the spot allowance:
  1. 3 bands, runs 4/4/2 (GEFS/ECMWF/GEPS)
  2. 3 bands, 2 runs each
  3. mid only, 4 runs
  4. mid only, 2 runs
- [ ] Shown on the Manage budget panel; drops a tier automatically when locations are
  added.
- [ ] Arithmetic at 50 locations, tier 1: 50 × 3 × ((3.54 + 5.83) × 4 + 2.4 × 2) ≈ 6,340/day,
  plus 2,000 for spots, leaving ~660 margin.

### ~50 locations
- [ ] Manage, "Add from catalog": multi-select over `catalog_ski_areas`
  (`searchCatalog`), each resolved via `locations/resolve.py` as a queued job.
- [ ] Overview (`frontend/src/routes/+page.svelte`) and Calendar grouped by region, with a
  filter and browser-saved favourites.
- [ ] Check at 50: the Compare picker (`CompareAdd.svelte`), push-digest length, the
  location palette.
- [ ] A new location's first satellite pass (4–5 min each, `scheduler.satellite`) runs in
  the background, at most 2 an hour.
- [ ] The map box is fixed to the West (`maps/region.py`, `map.region`), so map jobs don't
  grow with locations in the West.

**Done when:**
- US locations refresh within ~70 min of each HRRR run
- 50 locations finish a run in under 5 minutes
- Manage shows tier 1 within budget
- database size is steady after two weeks

## Milestone 5: Learning from history

**Goal:** use years of model history plus station records to weight and correct the
models at each location, and give new locations a scorecard on day one. **A spike, then
two PRs.**

### Spike
- [ ] Confirm the local server answers `start_date`/`end_date` requests for past seasons,
  per model (2021–2026).
- [ ] Check whether `*_previous_day1` variables work self-hosted (true 1-day-ahead
  forecasts for the last ~3 months, from the per-run data the bucket keeps 3 months). If
  they do, prefer them for the metrics.
- [ ] Write what was found into this section.

### Calibration
- [ ] New `backend/snowwatch/calibrate.py`, CLI `snowwatch calibrate [--location] [--report]`,
  and a weekly worker job.
- [ ] Station history: SNOTEL daily (precipitation increment, snow water, depth;
  `sources/snotel.py`) and BC snow-pillow history (`sources/bc_asws.py`), Nov–Apr of each
  available season. Stored in a new `obs_history` table that the 400-day pruning in
  `store/retention.py` leaves alone.
- [ ] Each model's daily precipitation and snow water at the station's own spot and
  elevation (as `station_request` does), from the local archive: one small request per
  model per season.
- [ ] Metrics per (location, model, month band): wet-day multiplicative bias, MAE, hit
  rate, sample size. Stored in a new `model_skill` table (migration).
- [ ] Weights from inverse MAE, pulled toward equal weights while the sample is small.

### Use it
- [ ] `analysis/consensus.py`: a weighted median, with each model's snow water scaled by
  its bias factor (clamped 0.6–1.6), gives a new source `cons_cal`, stored in
  `forecast_daily` and scored live by `verify.py` next to the others.
- [ ] Config `calibration: off | score | apply`. Ship in `score`; the owner switches to
  `apply` when the live scorecard shows `cons_cal` is closer over ≥ 30 snow days.
- [ ] `snowwatch calibrate --report`: trains on the earlier seasons, tests on the last one,
  and prints corrected vs uncorrected.
- [ ] "How it has done here" (`frontend/src/lib/confidence/`): until live scores build up,
  show the historical per-model bias from day one, labelled "from past seasons,
  short-range model data".
- [ ] Spots (behind a flag): use the nearest calibrated location's factors only within
  15 km and ± 300 m, labelled with its station's name.
- [ ] Docs: the history is the start of each model run (short range), so it shows
  consistent bias in amounts, not day-5 skill; the live scorecard stays the judge.

**Done when:** the report exists for the seed locations, `cons_cal` is scored live, and a
new location shows historical skill immediately.

---

## Files

| Milestone | New | Changed |
|---|---|---|
| 1 | `store/migrations/009_api_usage.sql`, `tests/test_openmeteo_local.py` | `docker-compose.yml`, `settings.py`, `http.py`, `cli.py`, `scheduler.py`, `pipeline.py`, `store/repo.py`, `store/retention.py`, `sources/openmeteo.py` (budget only), `checks.py`, `api/admin.py`, `api/app.py`, `api/public.py`, `api/models.py`, Manage budget panel (`routes/admin/+page.svelte`), status page, `.env.example`, README, DEPLOYMENT, deploy-notes-home, ARCHITECTURE, SOURCES, THIRD_PARTY_NOTICES, CHANGELOG |
| 1b | `docker/ensembles.sh`, `ensembles.py`, `store/migrations/010_ensemble_shadow.sql`, `tests/test_ensembles.py`, `tests/test_ensembles_local.py` | `docker-compose.yml`, `deploy/deploy.sh`, `settings.py`, `http.py`, `pipeline.py`, `checks.py`, `cli.py`, `sources/base.py`, `sources/openmeteo.py` (budget), `store/repo.py`, `store/retention.py`, `api/public.py`, `api/admin.py`, `api/models.py`, status page, Manage budget, README, `.env.example`, DEPLOYMENT, deploy-notes-home, ARCHITECTURE, THIRD_PARTY_NOTICES, CHANGELOG |
| 2 | `spots.py`, `config/borders.geojson`, `store/migrations/011_spot_ensembles.sql`, `frontend/src/lib/components/LocationView.svelte`, `frontend/src/routes/spot/+page.svelte` | `pipeline.py` (shared fetch helper), `doc.py`, `api/public.py`, `api/app.py`, `config/forecast.yaml`, `routes/location/[id]/+page.svelte`, `map/Inspector.svelte`, `components/MapView.svelte`, `api.ts`, `LocationPalette.svelte`, `routes/+page.svelte`, `service-worker.ts`, `swRoute.ts`, ARCHITECTURE, SECURITY |
| 3 | `analysis/snowlevel.py`, new fixtures folder | `sources/openmeteo.py`, `analysis/slr.py`, `freezing.py`, `ridge.py`, `backcountry.py`, `flags.py`, `build.py`, `verify.py`, `push.py`, `doc.py`, `config/forecast.yaml`, BandTable, PeriodSheet, DaySheet, ForecastChart, backcountry and observed components, SOURCES |
| 4 | `modelwatch.py`, `budget.py` | `scheduler.py`, `pipeline.py`, `store/retention.py`, `store/repo.py`, `http.py`, `sources/openmeteo.py`, `analysis/build.py`, `config/forecast.yaml`, `push.py`, Manage (catalog add, budget), Overview, Calendar, Confidence tab, status page |
| 5 | `calibrate.py`, migrations for `obs_history` and `model_skill` | `analysis/consensus.py`, `verify.py`, `store/retention.py`, `sources/snotel.py`, `sources/bc_asws.py`, `scheduler.py`, `cli.py`, Confidence tab |

(Backend paths are under `backend/snowwatch/`, frontend paths under `frontend/src/lib/`
unless written in full.)

## Tests and verification

Every PR passes CI (`.github/workflows/ci.yml`), with the commands in `CONTRIBUTING.md`:

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy snowwatch && uv run pytest --cov
```
```bash
cd frontend && npm run lint && npm run check && npm test && npm run build && npm run e2e
```

Each PR also regenerates types after model changes, adds a `CHANGELOG.md` entry under
[Unreleased], updates docs, and ticks its checklist here. CI and development never need
the local server: with `OPEN_METEO_URL` empty the Fetcher doesn't rewrite, and tests use
fixtures.

End to end, per milestone:
- **M1:**
  - run the pinned image ([Appendix A](#appendix-a-running-the-server-in-a-cloud-sandbox))
    with `OPEN_METEO_URL=http://127.0.0.1:8080`
  - `snowwatch pull` for the seed locations, then `snowwatch check-sources --local`
  - stop the container → the next run falls back
  - with `OPEN_METEO_URL` empty, nothing changes; `snowwatch budget` shows the split
- **M1b:**
  - PR 1, on the mini PC: a week of downloads; the running server serves each new run;
    ECMWF with 51 members; disk and bandwidth logged daily
  - PR 2: a week of `shadow`, against the thresholds in "Switching on"; `check-ensembles`
    on every location; stop `openmeteo-ensembles` → stale systems fall back, runs succeed;
    `OPEN_METEO_ENSEMBLES=public` → milestone 1's behaviour and `budget` output
- **M2:**
  - `curl 'http://localhost:8000/api/spot?lat=47.42&lon=-121.41'` returns a snapshot;
    a point in Mexico gives 422; a burst of requests gives 429
  - Playwright: map tap → "Full forecast here" → spot page at 380 px and desktop, light
    and dark
- **M3:**
  - a snapshot rebuilt from the new fixtures has the new fields; the scorecard lists
    `cons_col`
  - a manual check on a known east-wind freezing-rain day at Snoqualmie
- **M4:**
  - a unit test with a fake clock: `meta.json` changes trigger runs, and limits hold
  - 50-location run time on the mini PC
  - database size before and after retention; planner tests for each tier
- **M5:**
  - `snowwatch calibrate --report` for the seed locations shows held-out results
  - `cons_cal` rows appear in `forecast_daily` and on the scorecard

## Risks and open questions

- **Remote-data mode is new**, and Open-Meteo maintains the server. Pinning by digest and
  the public fallback limit the damage if an update breaks something.
- **Cold caches after each model update** make the first requests slower. The 5 min delay
  in data-driven refresh and the 120 s local timeout cover it.
- **Public point forecasts**: per-visitor limits, the site-wide cap, the concurrency limit
  and the cache bound the CPU; the spot allowance bounds public ensemble use.
- **Bandwidth** on the home connection (~300–450 GB/month, plus ~250–470 GB/month with
  M1b; the owner says the cap is fine).
- **Disk:** the 60 GB VM disk filled on 27 Nov 2026 (the 30 GB cache and 16.8 GB of
  build cache) and can't grow. Fixed with a 10 GB cache and the deploy's build-cache
  prune; M1b keeps ~1.5–2 GB of ensembles, pauses its downloads under 5 GB free, and its
  `openmeteo status` warns under 10 GB free.
- **Downloads depend on three upstreams** (NOAA on AWS, ECMWF, Environment Canada), which
  change file names (the GEPS land file) and throttle (ECMWF's AWS mirror). Each system
  falls back to the public API on its own, and the freshness check catches a downloader
  that stalls quietly.
- **Bias learning is research.** It ships in `score` mode and is applied only when the live
  scorecard shows it helps.
- Open questions, to settle while building:
  - The column snow ratio's wind adjustment and the wet-bulb thresholds need tuning
    against the scorecard.
  - Are ensemble days 11–16 used anywhere? (M4)
  - Do `*_previous_day1` variables work self-hosted? (M5)
  - Does ECMWF ENS download cleanly from the mini PC? (M1b; it did from PR 1's sandbox.)
  - ~~Does the running server pick up new runs without a restart? (M1b)~~ Yes (PR 1).
  - How much do the ensemble folders grow per week? (M1b; within a day, ~1 MB a run,
    once the unused files are deleted, which PR 1 does after each run.)
  - ~~Does the image tolerate `read_only` and cap-drop? (M1)~~ Yes, with `/tmp` as tmpfs.

---

## Appendix A: running the server in a cloud sandbox

What worked on 26 Nov 2026 in a Claude Code cloud sandbox: Docker installed but not
running, and outbound HTTPS through an agent proxy with its own CA bundle at
`/root/.ccr/ca-bundle.crt`. Elsewhere, drop the proxy and CA lines.

```bash
dockerd > /tmp/dockerd.log 2>&1 &
```
```bash
docker pull ghcr.io/open-meteo/open-meteo
```
```bash
mkdir -p /tmp/omdata && chmod 777 /tmp/omdata
```
```bash
docker run -d --name om --network host \
  -v /tmp/omdata:/app/data \
  -v /root/.ccr/ca-bundle.crt:/etc/ssl/certs/ca-certificates.crt:ro \
  -e SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
  -e HTTPS_PROXY="$HTTPS_PROXY" -e https_proxy="$HTTPS_PROXY" -e NO_PROXY=localhost,127.0.0.1 \
  -e REMOTE_DATA_DIRECTORY=https://openmeteo.s3.amazonaws.com/data/ \
  -e CACHE_SIZE=8GB \
  ghcr.io/open-meteo/open-meteo
```
```bash
curl "http://127.0.0.1:8080/v1/forecast?latitude=46.93&longitude=-121.5&models=ecmwf_ifs025&hourly=temperature_2m&forecast_days=2"
```

Things that cost time:
- **Permissions:** the image runs as a non-root user. A root-owned bind mount crashes the
  first request with `cannotCreateFile(filename: "./data//cache.bin", errno: 13)`. Use a
  writable directory or a named volume.
- **Disk:** `CACHE_SIZE` is reserved on disk at once; 20 GB showed as 21 GB used. Delete
  the directory afterwards.
- **First request** in an area takes seconds (1.9 s for one variable, up to 52 s for a full
  `upper` request); repeats take milliseconds.
- **The public API answers 429** ("Daily API request limit exceeded") from shared sandbox
  IPs, so compare against the saved fixtures instead.
- **No AVX2** on a machine shows up as "Illegal instruction" crashes.
- To measure download volume, read the `eth0` receive counter in `/proc/net/dev` before and
  after.

## Appendix B: how the server was checked

**Same columns, same gaps.**
- For each request in `location_requests(loc, cfg, ensembles=False)` (blend, multi, upper,
  clouds), send the same parameters to the local server. Take the saved public answer
  from `backend/tests/fixtures/live-20261104/<location>/<name>.json.gz`; that request's
  parameters are in `meta.json` under `requests["<location>/<name>"]`.
- For every hourly column at every point, compare the share of null values. Flag a
  missing column, or a share that differs by more than 5 points.
- Values aren't compared, because the fixtures are from another day.
- Result: Crystal (US) and Whistler (CA): blend 18/18, multi 54/54 (US) and 45/45 (CA),
  upper 60/60 columns present. Only Whistler's upper air differed, with fewer gaps locally
  (GEM 30 % vs 35 %, ICON 43 % vs 52 %, HRDPS 71 % vs 86 %).
- Ensemble requests answered, but every member was null.

**Timing and volume.** Replay one run's requests (`location_requests` plus
`station_request`) for 36 locations: the 6 seed locations and 30 western ski areas, built
as `Location` objects with base/mid/summit at one point. Use 4 threads against the local
server, and record wall time per request kind and the `eth0` bytes received. Run it twice:
once with an empty cache, once cached. Results are in the table under
[What the test found](#what-the-test-found).

**Elevation:** `GET /v1/elevation?latitude=46.935,47.424&longitude=-121.475,-121.418`
returned `[1336.0, 928.0]`, read on demand from the Copernicus DEM in the public data.

Milestone 1 turns the first check into `snowwatch check-sources --local`.

## Appendix C: starting a milestone in a new session

Start each in a fresh session on an up-to-date `main`. Prompt:

> Implement milestone N of `docs/OPEN-METEO-PLAN.md` (N can be 1b). Read the whole plan first,
> including the appendices. Work through that milestone's checklist, split into the PRs it
> names. When done, tick the items in the plan and update its status line in the same PR.

| Milestone | Needs first | Owner action after it deploys |
|---|---|---|
| 1 Hybrid foundation | nothing | Add `COMPOSE_PROFILES=openmeteo` and `OPEN_METEO_URL=http://openmeteo:8080` to `.env`, run `docker compose up -d`, check `snowwatch openmeteo status` |
| 1b Self-hosted ensembles | M1, 15 GB free on the VM | after PR 1: add `ensembles` to `COMPOSE_PROFILES` and watch a few days; after PR 2: `OPEN_METEO_ENSEMBLES=shadow` for a week, then `local` |
| 2 Forecast anywhere | M1 (M1b helpful: spot ensembles without an allowance) | none |
| 3 Richer variables | M1 (M2 helpful: spots get the new fields too) | after a few weeks, compare `cons_col` on the scorecard and choose the headline method |
| 4 Fresher and wider | M1 | add locations up to ~50 (Manage → Add from catalog) |
| 5 Learning from history | M1 (M4 helpful: more locations to learn from) | switch `calibration` to `apply` when the scorecard shows it helps |

## Appendix D: how the ensembles were tested

27 Nov 2026, in the same sandbox as [Appendix A](#appendix-a-running-the-server-in-a-cloud-sandbox)
(4 cores, the pinned image, the proxy and CA lines as there). A named volume, and one
download at a time, each in its own container, as the downloader service would:

```bash
docker run --rm -v ens:/app/data <proxy and CA lines> $IMG download-gfs gfs025_ens --only-variables precipitation,frozen_precipitation_percent --download-from-aws --concurrent 4
```
```bash
docker run --rm -v ens:/app/data <proxy and CA lines> $IMG download-gfs gfs05_ens --only-variables precipitation,frozen_precipitation_percent --download-from-aws --concurrent 4
```
```bash
docker run --rm -v ens:/app/data <proxy and CA lines> $IMG download-gem gem_global_ensemble --only-variables snowfall_water_equivalent --concurrent 4
```
```bash
docker run --rm -v ens:/app/data <proxy and CA lines> $IMG download-ecmwf --domain ifs025_ensemble --only-variables snowfall_water_equivalent --source aws --concurrent 1 --download-concurrent 1
```

GEPS first needs `HSURF.om` from `https://openmeteo.s3.amazonaws.com/data/cmc_gem_geps/static/`
copied to `/app/data/cmc_gem_geps/static/`. Without `--run`, each downloader took the
newest run it could find (the 00z run, at about 07:40 UTC). Time and peak memory came from
`docker stats`, downloads from the `eth0` counter in `/proc/net/dev`, disk from `du` in the
volume. Then the server ran on the volume (`$IMG`, its default command, with and without
`REMOTE_DATA_DIRECTORY`) and each system was compared with the public API: the same
`/v1/ensemble` query to both (Crystal's mid band, `hourly=snowfall`, 16 days, GMT), every
member's total. ECMWF's size came from one `…-24h-enfo-ef.index` file: the sum of
`_length` for `param` `sf` over the members, times 85 steps.

