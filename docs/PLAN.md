# Snow Watch: build plan

Draft v1, 17 Oct 2026. Builds on `docs/SPEC-draft.md` and the prototype in `docs/reference/`. Where this plan and the draft spec disagree, this plan wins; section 2 lists every change and why.

---

## 0. In one paragraph

A self-hosted, OpenSnow-style forecast app for a short list of ski resorts and touring zones. A Python worker on the mini PC pulls free model data (Open-Meteo, NWS, SNOTEL, avalanche centers) four times a day, computes a model consensus with honest uncertainty ranges, and stores a ready-to-render document per location in SQLite. A FastAPI service serves those documents plus a Svelte single-page app whose charts are hand-built SVG: day/night snowfall bars, a stacked hourly meteogram with one shared crosshair, model-agreement and probability charts, and a backcountry panel. Cloudflare Tunnel publishes it; Cloudflare Access controls who can open it. It installs on a phone as a PWA.

## 1. Product

### 1.1 Two jobs

| Job | Question it answers | What it needs most |
|---|---|---|
| **Resort day** | Where and when is the best ski day in the next 10 days? | Overnight and daytime snow, snow quality, rain risk, summit wind (lift holds), visibility, temperature |
| **Backcountry tour** | Is the snowpack and weather right for this zone on this day? | Official avalanche danger, storm snow in the last 72 h, wind speed and direction at ridge height (loading), warming and freezing level, rain on snow, visibility above treeline, daylight, overnight refreeze |

Each location in the config has `kind: resort` or `kind: backcountry`. Both kinds get the same data; `kind` changes the order of the location page and which badges appear.

### 1.2 Design principles

1. **Charts first, numbers labelled.** Every chart works at 380 px and with a thumb.
2. **One story.** The day/night bars, the hourly charts, the tables and the overview must agree with each other (section 4.2 fixes a prototype bug where they did not).
3. **Honest uncertainty.** Show the consensus, its basis, the ensemble range and model disagreement side by side. Outliers are called out, never silently averaged in.
4. **Glance, then drill down.** Overview, then location, then period detail, then hourly.
5. **No prose, no AI.** Short rule-based badges only.
6. **Never imply safety.** The app shows avalanche danger from the official center and the weather inputs. It never computes a "safe to tour" score.

### 1.3 Pages

**Overview**
- One row per location: name, region, kind icon, alert and avalanche-danger chips, *Last 24 h*, *Next 5 days* (large, with ensemble range), *Days 6–10*, a 10-day day/night bar sparkline, flag badges.
- Sort by next 5 days, days 6–10, last 24 h or name. Filter: all, resorts, backcountry.
- **Calendar view** (toggle): a heatmap with locations as rows and the 20 day/night periods as columns, shaded by snowfall, inches printed in cells of 1 in or more. Answers "when and where" in one glance. Tap a cell to open that location at that period.

**Location** (order shown is for a resort; backcountry moves the backcountry panel to second)
1. Header: name, region, forecast elevation, **elevation switch (Base / Mid / Summit)** that drives the tiles and hourly charts, NWS alert banner.
2. Tiles: Last 24 h · Next 5 days (range) · Days 6–10 (range) · Now (temperature, snow level, wind).
3. Badges (flags, ski-day rating for the next good day).
4. **Day/night snowfall bars**, 10 days, with weather icon and high/low under each day. Tap a bar for a detail sheet.
5. **Hourly stack** (5 or 10 days), section 5.2.
6. Backcountry panel (section 4.6).
7. Day-by-day table (20 periods).
8. Base / mid / summit table.
9. **Chance of snow**: exceedance curves for the next 5 days and days 6–10.
10. **Do the models agree?** 15-day running totals.
11. **How the forecast changed**: the next-5-day consensus over the last runs.
12. Observed: SNOTEL depth and SWE (30 days) and the verification scorecard.
13. Links (radar, NWS, avalanche center, roads), optional webcam images.

**Plan a day** (replaces the draft's Compare page)
- Pick a date. One row per location for that day: overnight and daytime snow, ski-day rating, summit gusts, high/low, sky, avalanche danger.
- Secondary mode: pick 2–4 locations and see their day/night bars stacked on one scale (the draft's Compare).

**Status**: last runs, errors, data age per source, Open-Meteo usage against the daily budget.

**Settings**: units, theme, default elevation band, location order and hidden locations (stored in the browser).

## 2. Changes from the draft spec

| # | Change | Why |
|---|---|---|
| 1 | Hourly charts and the elevation table use consensus data, not the high-res blend alone | In the 17 Oct sample, Crystal's hourly chart adds up to **14.8 in** for days 6–10 and the elevation table says 15.2 in, while the consensus is **0.9 in**. The blend tracks GFS past day 5 (GFS 14.7, ECMWF 0.3, GEM 1.5, ICON 0). The bars and the charts told two different stories. |
| 2 | The multi-model call fetches more variables (temperature, precipitation, freezing level, wind, cloud) at all three elevations | Gives a consensus per elevation band and model-spread bands on the temperature and snow-level charts. |
| 3 | Short-range regional models added for the first 48 h: HRRR and NBM (US), HRDPS (Canada) | Better terrain detail in the window that matters most for "tomorrow". The model list lives in config. |
| 4 | New backcountry layer: avalanche danger (avalanche.org for US centers, Avalanche Canada), free-air ridge wind, wind-loading rose, low/mid/high cloud, visibility, daylight, refreeze and warming indicators | The draft covered resorts well and touring barely. |
| 5 | Storage is one precomputed document per site per run, plus a few history tables, instead of twelve normalized tables | The UI needs nested documents. Building them once per run keeps the API tiny and fast. History tables exist only where queries over time are needed (trend, verification). |
| 6 | The API serves metric only; the browser converts units | The unit toggle is instant, works offline, and each resource has one cache key. |
| 7 | Probabilities computed from member totals in the browser | The snapshot carries the sorted member totals per window (82 numbers). The UI can draw an exceedance curve and use 1/6/12 in or 2/15/30 cm without new server code. |
| 8 | No dual-axis charts | The prototype put the running total and the precipitation chance on second y-axes. The running total moves into the chart header readout; the chance becomes its own strip. Two scales on one plot invite false comparisons. |
| 9 | Charts are hand-built SVG components, not uPlot | Section 6.2. |
| 10 | Compare becomes "Plan a day" | Choosing between places for one date is the decision you actually make. |
| 11 | One container image, two services (api, worker), plus cloudflared | One build. The scheduler can't stall the API. |
| 12 | Images built by GitHub Actions for both CPU types | The mini PC only pulls images; no Node toolchain on the box. Local builds still work. |

Everything else in the draft stands: goals, non-goals, sources, rate-limit handling, schedule, the derived metrics in 6.3, the flags in 6.4, verification in 6.5, the UX requirements in 9.2, hosting in 10 and quality in 11.

## 3. Data sources

### 3.1 Calls per site per run

| # | Call | Elevations | Content | When |
|---|---|---|---|---|
| 1 | Open-Meteo forecast, default blend | base, mid, summit (one call) | Hourly: temperature_2m, apparent_temperature, precipitation, rain, showers, snowfall, precipitation_probability, freezing_level_height, weather_code, cloud_cover, cloud_cover_low/mid/high, visibility, wind_speed_10m, wind_gusts_10m, wind_direction_10m, wind speed and direction at the pressure level nearest the summit (850/700 hPa), snow_depth, is_day. Daily: sunrise, sunset, daylight_duration. `past_days=3`, `forecast_days=11`, `timezone=auto`. | every run |
| 2 | Open-Meteo forecast, multi-model | base, mid, summit | Per model: snowfall, precipitation, rain, temperature_2m, freezing_level_height, wind_speed_10m, wind_gusts_10m, cloud_cover. Models: GFS, ECMWF IFS 0.25°, GEM, ICON, plus HRRR and NBM for US sites or HRDPS for Canadian sites. 16 days. | every run |
| 3 | Open-Meteo ensemble | mid | snowfall for GEFS (~31 members), ECMWF ENS (51), optionally GEPS (21). 16 days. | 2×/day (after 00Z and 12Z) |
| 4 | NWS alerts | point | active watches and warnings | every run, US |
| 5 | NRCS SNOTEL (AWDB REST) | station | daily SNWD, WTEQ, TOBS, PREC for 45 days; hourly SNWD and TOBS for 4 days | every run, if configured |
| 6 | Avalanche danger | zone | US: avalanche.org public API (zone map layer, then the zone's forecast product: danger by elevation band, problems, issue and expiry times). Canada: Avalanche Canada forecast API (areas, then products). | 2×/day, backcountry and opted-in resorts |
| 7 | NWS AFD | office | link only | daily |

Exact Open-Meteo model identifiers (for example `ncep_hrrr_conus`, `ncep_nbm_conus`, `gem_hrdps_continental`) and which variables each model provides must be checked against the live docs in milestone 0; this sandbox could not reach open-meteo.com. The pipeline treats missing variables per model as normal, and the model list is config.

### 3.2 Budget

Open-Meteo's free tier is about 10,000 weighted calls per day (also per-hour and per-minute caps). Weight ≈ locations × (days ÷ 14) × (variables ÷ 10), where variables multiply by models and ensemble members.

| Call | Rough weight |
|---|---|
| Blend, 3 elevations, ~25 variables | ~8 |
| Multi-model, 3 elevations, 8 variables × 6 models, 16 days | ~16 |
| Ensembles, 1 elevation, ~100 members, 16 days | ~12 |
| **Per site per day** (4 full runs, ensembles twice) | **~120** |
| **10 sites per day** | **~1,200** (12% of the free tier) |

The worker records the estimated weight of every call so the Status page can show usage. The 429s the prototype hit were most likely caused by its shared cloud IP address; a home IP should see far fewer. The throttling rules from the draft (20 s between sites, 65 s wait on 429, backoff) stay.

### 3.3 Later sources (not in v1)

NWAC telemetry stations, BC River Forecast Centre snow pillows and Avalanche Canada stations (observations for the Canadian sites), Synoptic/MesoWest, a radar layer, resort webcams (image URLs in config).

## 4. Analysis

### 4.1 Ported from `pull.py` unchanged in spirit

Day/night periods (06–18, 18–06, night belongs to the evening's date, partial first period, drop a trailing fragment under 6 h, 20 periods), consensus with basis (median of models while ≥ 3 run, high-res blend added for the first 4 periods, ensemble mean after), ensemble percentiles and running totals (skip windows with < 10 members), next-5-day and days 6–10 windows, precipitation type, snow quality bands, period extras, "stop series where data ends instead of plotting zeros".

One fix while porting: in the prototype the 15-day running-total percentiles silently switch member sets when the ECMWF ensemble ends a day before GEFS. In the 17 Oct sample, Crystal's 90th percentile drops from 6.0 in to 4.8 in on the last day because only GEFS members remain. Running totals must be computed per ensemble, or the band must stop where the full member set ends.

### 4.2 Consensus-consistent hourly series (new)

The charts must add up to the bars.

- **Snowfall and water, per hour.** Within each period, take the *shape* of the hourly series from the short-range models (first 48 h) or the ensemble-mean hourly series (after 48 h), then scale it so the period sums to the period consensus. If the shape is all zero but the consensus is not, spread the consensus over the hours where the model median shows precipitation, or evenly.
- **Continuous variables** (temperature, freezing level, wind, gusts, cloud): the hourly median across models, with the model min–max as a band. In the first 48 h the line follows the short-range models.
- **Precipitation type per hour** from the consensus snow fraction (consensus snow vs consensus water), thresholds as in the prototype.
- A vertical marker shows where the consensus basis switches from models to ensemble.

### 4.3 Per elevation

The period consensus, windows and hourly series are computed for base, mid and summit. The elevation switch on the location page picks one. Ensembles are fetched at mid only; their percentiles at base and summit are scaled by the ratio of model-consensus totals between elevations, and labelled as estimated.

### 4.4 Wind at ridge height and loading

- **Free-air wind:** speed and direction at the pressure level closest to the summit elevation, shown as a second line on the wind chart for backcountry sites and summits.
- **Loading rose:** an 8-sector histogram of wind direction weighted by snowfall × wind speed, for the last 72 h and next 48 h. Labels name the likely loaded aspects ("SW wind, loading NE aspects").

### 4.5 Ski-day rating (resorts)

Per day, using lift hours (09:00–16:00, configurable): new snow (overnight + day consensus), snow quality, rain at mid, maximum summit gust, low cloud and visibility at mid, temperature. Output is one of *Powder, Great, Good, Fair, Poor* plus the 1–3 reasons that decided it ("9 in overnight", "gusts 55 mph at the summit: lift holds likely"). Thresholds are config, and every rule is unit-tested.

### 4.6 Backcountry panel (touring)

No score. Shown side by side:
- Avalanche danger today and tomorrow by elevation band (alpine, treeline, below treeline), using the standard North American colors with the number and word, the avalanche problems, issue and expiry times, and a prominent link to the full forecast. An expired forecast is shown as expired, never as current.
- Storm snow in the last 72 h and the next 48 h at summit.
- Loading rose (4.4).
- Warming: freezing-level rise and temperature change over 24 h; rain on snow.
- Overnight refreeze at each elevation (overnight low below freezing, sky clear enough to radiate).
- Sky above treeline: low/mid/high cloud and visibility during the day.
- Sunrise, sunset and daylight.

### 4.7 Flags

All flags from draft section 6.4, plus `wind_loading` (sustained free-air wind ≥ 25 mph with ≥ 4 in snow in 24 h), `rapid_warming` (freezing level up ≥ 3,000 ft in 24 h, or temperature up ≥ 15 °F), `refreeze` (spring: good overnight refreeze after a warm day), and `avalanche_danger` (official rating ≥ 4 in any band; text quotes the center). Each flag is `{site, type, severity, period_key?, value, text}`.

### 4.8 Forecast trend (new)

Every run stores per-day consensus and per-model totals per site. The location page shows how the next-5-day total and each upcoming day's forecast changed over the last 10 runs. This is cheap and answers "is the storm trending up or down?"

### 4.9 Verification

As in draft 6.5: compare each run's next-day forecast with the observed SNOTEL depth change (and SWE × ratio), scorecard per site for the consensus, each model and the ensemble median.

## 5. Visual design

### 5.1 Color

Colorblind-safe, checked with a palette validator in both themes. Snow, mix and rain follow radar convention, which skiers already read without a legend.

| Role | Light | Dark |
|---|---|---|
| Snow (day bars, snowfall) | `#2a78d6` | `#5598e7` |
| Snow, night bars | `#184f95` | `#256abf` |
| Mixed precipitation | `#e87ba4` | `#d55181` |
| Rain | `#008300` | `#008300` |
| Temperature | `#eb6834` | `#d95926` |
| Snow level | `#6250d6` | `#9085e9` |
| Wind | `#1baf7a` | `#199e70` |
| Cloud and chance strips | single-hue sequential ramps | same, re-stepped for dark |
| Avalanche danger | North American danger scale colors, always with number and word | same |

Night bars also sit on a shaded night band, so day/night never depends on color alone.

### 5.2 Hourly stack

One shared time axis, night shading, midnight separators, 5/10-day toggle, elevation switch.

1. **Snowfall**: hourly bars. The header shows the value at the crosshair and the running total since now. No second axis.
2. **Precipitation**: water per hour, bars colored snow/mix/rain. Under it, a thin *chance* strip shaded 0–100%.
3. **Temperature**: consensus line, model range as a light band, dashed 32 °F threshold.
4. **Snow level**: consensus line and band, with base, mid and summit as labelled reference lines.
5. **Wind**: sustained line with a gust band up to the gust value; direction arrows every 3 h; free-air ridge wind as a second line on backcountry sites.
6. **Sky**: three strips for low, mid and high cloud.

**Crosshair:** one crosshair across all charts. Instead of a floating tooltip, every chart's header shows its value at the crosshair hour, so a finger never covers the data. At rest the crosshair sits on the current hour, so the headers read as "now". Dragging horizontally scrubs; vertical swipes still scroll the page.

### 5.3 Other charts

- **Day/night bars**: day bar, darker night bar on a shaded band, ensemble 10–90% whisker, value on the cap when ≥ 0.5 in, weather icon and high/low under each day, a star on powder days. Tap opens a detail sheet (bottom sheet on phones).
- **Model agreement**: ensemble 10–90% band and median, thin model lines that stop where each model's data ends, end labels with leader lines, outlier model highlighted.
- **Chance of snow**: exceedance curve ("chance of at least X") per window, with 1/6/12 in marked.
- **Overview sparkline** and **calendar heatmap** share the bar colors and a single sequential ramp.
- Every chart has a table equivalent (the day-by-day and elevation tables, or a "show as table" toggle).

### 5.4 Type and layout

A characterful display face for numbers and headings, a plain UI sans for body text, tabular figures in tables and axes. Self-hosted fonts and icons (Meteocons, MIT licensed) so the PWA works offline. Phone: single column, bottom tab bar, sticky location header with the elevation switch. Desktop (≥ 1100 px): wider charts and two-column grids for the tables and side panels.

## 6. Architecture and stack

### 6.1 Runtime

```
 phone / browser ──► Cloudflare (Access + cache) ──► cloudflared ──► api (FastAPI, static SPA + /api)
                                                                       │ reads
                                                                       ▼
                                                    SQLite (WAL) on ./data volume
                                                                       ▲ writes
                       Open-Meteo, NWS, SNOTEL, avalanche APIs ◄── worker (APScheduler + CLI)
```

| Service | Image | Notes |
|---|---|---|
| `api` | `snowwatch` | `uvicorn snowwatch.api:app`, read-only DB connection, serves `/` and `/api`, healthcheck on `/api/health` |
| `worker` | `snowwatch` | scheduler (4 runs/day, ensembles and avalanche 2×/day, backups nightly, VACUUM weekly); CLI via `docker compose run worker snowwatch …` |
| `cloudflared` | `cloudflare/cloudflared` | tunnel token from `.env` |

Target: under 300 MB of RAM idle for all three, x86_64 or ARM64.

### 6.2 Stack choices

| Layer | Choice | Reason |
|---|---|---|
| Pipeline | Python 3.12, httpx, pydantic v2, APScheduler, stdlib sqlite3, uv | Direct port of the prototype; small dependency set; no ORM needed for a handful of tables |
| API | FastAPI + Uvicorn | Typed models double as the JSON contract; also serves the static build |
| Database | SQLite, WAL mode | One file, no server, trivial backups |
| Frontend | SvelteKit with the static adapter, TypeScript | Small bundles, reactive SVG is natural in Svelte, file-based routes |
| Charts | Own SVG components on d3-scale, d3-shape, d3-array, d3-time-format | The charts are the product: full control of look, theming and touch, easy to test for out-of-bounds marks. 240 points × 6 charts is tiny for SVG. uPlot (canvas) is faster for tens of thousands of points but harder to style, theme and test, and we don't need the speed. |
| PWA | vite-plugin-pwa (Workbox) | App-shell precache, network-first API cache with offline fallback |
| Types | Pydantic → JSON Schema → TypeScript types, generated and checked in CI | Front and back can't drift |
| CI | GitHub Actions: lint, tests, build, multi-arch image to GHCR | The mini PC runs `docker compose pull && docker compose up -d` |

### 6.3 Repository layout

```
backend/
  pyproject.toml
  snowwatch/
    config.py            # pydantic models for locations.yaml and settings
    http.py              # client, retries, 429 handling, raw-response cache, call-weight tracking
    sources/             # openmeteo.py, nws.py, snotel.py, avalanche_us.py, avalanche_ca.py
    analysis/            # periods, consensus, hourly, ensemble, elevations, wind, skiday, flags, trend, verification
    pipeline.py          # one site, one run → snapshot document + history rows
    store/               # db.py, migrations/*.sql, backups
    api/                 # app, routes, response models
    scheduler.py
    cli.py               # pull, capture-fixtures, rebuild, backup, budget
  tests/
    fixtures/            # captured real API responses (gzipped)
frontend/
  src/lib/charts/        # Frame, TimeAxis, NightBands, Bars, Line, RangeBand, Strip, Arrows, Crosshair, …
  src/lib/               # api.ts, units.ts, time.ts, format.ts, stores.ts, types.gen.ts
  src/routes/            # +page (overview), site/[id], plan, status, settings
  static/                # manifest, icons, fonts, meteocons
config/locations.yaml
docker/Dockerfile        # node build stage → python runtime stage
docker-compose.yml
.env.example
docs/                    # PLAN.md, SPEC-draft.md, reference/
```

## 7. Storage

| Table | Purpose | Retention |
|---|---|---|
| `runs(id, started_at, finished_at, status, kind, errors_json, api_weight)` | run log | season |
| `snapshots(site_id, run_id, created_at, doc_gz)` | the precomputed location document the UI renders | last 8 per site |
| `forecast_daily(site_id, run_id, issued_at, target_date, band, source, snow_cm, water_mm)` | trend and verification; `source` is cons, each model, ens_p10/p50/p90 | season |
| `obs_daily(site_id, station, date, depth_cm, swe_mm, tmin_c, tmax_c, precip_mm)` | SNOTEL | season |
| `obs_hourly(site_id, station, t, depth_cm, temp_c)` | 24/72 h change | 7 days |
| `alerts(site_id, run_id, event, headline, severity, onset, ends, url)` | NWS | season |
| `avalanche(site_id, fetched_at, issued_at, expires_at, center, zone, ratings_json, problems_json, url)` | danger | season |
| `flag_log(site_id, type, key, first_run, last_run)` | "first fired" for push alerts | season |

Raw responses go to `data/raw/` gzipped for 24 h. Backups: nightly `VACUUM INTO data/backups/snowwatch-YYYYMMDD.db`, keep 14. A failed site or run never replaces the last good snapshot.

## 8. API

All JSON, metric units, with `run_id` and `generated_at`. `ETag` is the run id. `Cache-Control: public, max-age=300, stale-while-revalidate=3600`. Snapshot bodies are stored gzipped and sent as-is.

| Endpoint | Returns |
|---|---|
| `GET /api/health` | last good run, age, errors per source |
| `GET /api/overview` | config list plus overview rows: windows, member totals, 20 period totals, flags, alert and danger chips, station depth |
| `GET /api/sites/{id}` | the full snapshot: periods, hourly for all three bands, elevations, windows, flags, alerts, avalanche, links, SNOTEL 30 days |
| `GET /api/sites/{id}/trend` | forecast history for the last 10 runs |
| `GET /api/sites/{id}/verification` | season scorecard and daily pairs |
| `GET /api/plan?date=` | Plan-a-day rows |
| `GET /api/runs?limit=20` | run history and API usage |

Target sizes: overview under 15 KB and a location document under 60 KB, both gzipped.

## 9. Hosting and access

1. Domain on Cloudflare, for example `snow.<domain>`.
2. Cloudflare Tunnel, token in `.env` as `TUNNEL_TOKEN`, public hostname → `http://api:8000`.
3. Cloudflare Access: self-hosted app for the hostname, policy allowing listed emails with one-time PIN, session length 1 month so phones rarely log in again.
4. PWA behind Access: `<link rel="manifest" crossorigin="use-credentials">`; the service worker caches the shell and API responses but never serves a cached page when Access wants a login. If an API call comes back as a login redirect, the app shows "Sign in again", which reloads the page.
5. `docker compose up -d`. No port forwarding.
6. Updates: push to GitHub → Actions builds the image → `docker compose pull && docker compose up -d` on the mini PC (or Watchtower).

README covers first setup, adding a location, adding a friend, backups and restore, updating, and troubleshooting (429s, tunnel down, stale data, Access loops).

## 10. Quality

- **Fixtures first.** `docs/reference/sample/raw/` holds `pull.py` *output*, not raw API responses. Milestone 0 adds `snowwatch capture-fixtures`, run once wherever Open-Meteo is reachable, to save real responses for all six sites.
- **Parity test.** Run the prototype logic and the new pipeline on the same captured responses; periods, consensus and windows must match before the intentional changes in section 4 are layered on.
- **Unit tests (pytest):** period bucketing including the partial first period, midnight, and **daylight-saving changes** (1 Nov 2026 and 14 Mar 2027 fall inside the season, giving 11 h and 13 h periods); the consensus basis switch; percentiles and probabilities; ptype and quality bands; consensus-shaped hourly sums equal period totals; every flag and ski-day rule; unit conversion.
- **Resilience:** one site failing doesn't block others; a partial ensemble failure still produces deterministic output; a missing model variable is tolerated.
- **Frontend:** Vitest component tests render every chart with fixtures and assert every rect, line and path coordinate is inside the plot area (the prototype once drew every line off-chart); empty states for no snow, no alerts, no SNOTEL, no avalanche product.
- **Visual checks:** Playwright screenshots of Overview and Location at 380, 768 and 1280 px in light and dark, plus a check that the page never scrolls sideways.
- **Lint:** ruff, mypy, svelte-check, eslint, prettier. Structured JSON logs.

## 11. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Foundations: repo layout, tooling, CI, config schema with the 6 sites, fixture capture CLI, model IDs checked | CI is green and real responses are captured for all sites |
| M1 | Pipeline: sources, analysis port plus sections 4.2–4.3, SQLite, scheduler, CLI | A run fills the DB for all sites, tests and the parity test pass |
| M2 | API and Location page: tiles, day/night bars with detail sheet, hourly stack with crosshair, tables, model agreement, chance of snow | It beats the prototype on your phone (screenshots for review) |
| M3 | Overview, PWA, Docker, Tunnel and Access, README | You and a friend open it from your phones |
| M4 | Ski and tour layer: ski-day rating, avalanche danger, ridge wind and loading rose, sky strips, daylight, warming and refreeze, Plan a day | Both kinds of location read well on a phone |
| M5 | Analysis: flags, forecast trend, SNOTEL panel, verification, Status page | Scorecard shows after a week of runs |
| M6 | Optional: ntfy push alerts, radar map, webcams, Canadian observations, NWAC stations | as chosen |

M0–M3 is the first useful release.

## 12. Open questions

1. Mini PC CPU (x86_64 or ARM64), OS and RAM.
2. Domain and subdomain to use.
3. Locations: keep the six? Which resorts and touring zones to add? For a touring zone: trailhead, typical high point, and its avalanche forecast zone.
4. Access: just you, or friends through Cloudflare Access?
5. Allow this cloud environment to reach the data hosts so the build can use live data here? Otherwise everything runs on fixtures until it's on the mini PC.
6. Push alerts (ntfy) for powder days and incoming storms?
7. Keep the Claude-hosted prototype running until M3? (Recommended.)

## 13. Risks

- **Open-Meteo** is free for non-commercial use with no uptime promise, and model IDs change occasionally. Mitigation: config-driven model list, Status page flags missing models, last good data is kept.
- **Avalanche APIs**: confirm the terms of avalanche.org and Avalanche Canada before sharing with friends; fall back to links if needed.
- **Model snowfall is derived, not measured.** Label it everywhere; the verification scorecard shows each model's bias per site over time.
- **Cloudflare Access with a PWA** has known login-loop issues; handled as in section 9.
- **Daylight-saving changes** in period bucketing; covered by tests.
- **Mini PC offline**: the stale banner appears after 12 h and the PWA still opens with the last data.
