# Snow Watch — self-hosted snow forecast app

Spec and requirements for a personal, shareable snow forecasting web app, hosted on a home mini PC and published through a Cloudflare Tunnel. Written to be handed to Claude Code.

A working prototype exists (a Claude-hosted dashboard plus two Python scripts). They are in `reference/` and are the ground truth for data sources, derived metrics and chart designs. Port their logic; don't reinvent it.

---

## 1. Goals

1. Show snow forecasts for a configurable list of ski areas and backcountry zones, in the style of OpenSnow: **day and overnight snowfall in inches**, plus hourly charts for precipitation, temperature, snow level, wind and cloud cover.
2. Be honest about uncertainty: show model consensus, individual models and ensemble ranges side by side, and make outlier models obvious.
3. Run entirely on a home mini PC with **no paid APIs and no LLM**. All analysis is deterministic code.
4. Be reachable from anywhere and shareable with friends at a real URL (Cloudflare Tunnel plus Cloudflare Access), with no inbound ports open on the home network.
5. Feel like an app on a phone: installable PWA, fast, readable at 380 px wide, dark and light themes.

## 2. Non-goals

- No AI-written summaries or forecast prose. Short rule-based flags (section 6.4) are in scope; paragraphs are not.
- No user accounts inside the app. Cloudflare Access handles who can open it.
- No commercial use. Open-Meteo's free tier is non-commercial only.
- No native iOS or Android app. A PWA is enough.

## 3. Users and access

- **Owner:** edits the location list and runs the server.
- **Friends:** read-only, invited by email through Cloudflare Access (one-time PIN to their inbox). The free plan covers up to 50 users.
- **Public demo:** optional later; out of scope for v1.

## 4. Architecture

```
            ┌─────────────── mini PC (Docker Compose) ───────────────┐
 Internet → │ cloudflared ──► web (Caddy or FastAPI static + /api)   │
 (CF Access)│                       │ reads                          │
            │                       ▼                                │
            │                   SQLite (volume)  ◄── worker (Python) │──► Open-Meteo, NWS, SNOTEL
            │                                        scheduler       │
            └────────────────────────────────────────────────────────┘
```

Services, all in one `docker-compose.yml`:

| Service | Role |
|---|---|
| `worker` | Python 3.12. Runs the pull and analysis on a schedule (APScheduler or a cron loop inside the container). Writes to SQLite. Also exposes a CLI (`python -m snowwatch.pull --site crystal`). |
| `api` | FastAPI plus Uvicorn. Read-only JSON endpoints, and serves the built frontend. |
| `cloudflared` | Cloudflare Tunnel connector, token supplied through `.env`. |
| `ntfy` (optional, phase 3) | Push alerts. Can be the public ntfy.sh instead of self-hosting. |

Storage is a single SQLite file on a named volume, in WAL mode, with a nightly backup copy kept for 14 days.

Configuration lives in `config/locations.yaml` (section 5) and `.env`: tunnel token, timezone, schedule, contact email for the NWS User-Agent.

Target hardware is any x86_64 or ARM64 mini PC running Linux with Docker. Idle memory should stay under 300 MB in total.

## 5. Locations (config)

`config/locations.yaml`. Adding a location must require only editing this file and restarting.

```yaml
- id: crystal
  name: Crystal Mountain
  region: WA Cascades
  country: US            # US enables NWS alerts + SNOTEL
  lat: 46.935
  lon: -121.475
  elevations:            # meters; mid is the headline forecast point
    base:   {label: Base,         m: 1341}
    mid:    {label: Mid-mountain, m: 1800}
    summit: {label: Summit,       m: 2095}
  snotel: "642:WA:SNTL"  # optional
  nws_afd_office: SEW    # optional, links only
  links:
    Radar: https://radar.weather.gov/station/katx/standard
    Avalanche (NWAC): https://nwac.us/avalanche-forecast/#/west-slopes-central
```

Initial list (values in `reference/pull.py`, `LOCATIONS`): Crystal Mountain, Snoqualmie Pass, Heather–Maple / Rainy Pass, Whistler, Revelstoke and Banff Sunshine.

## 6. Data pipeline

### 6.1 Sources

| Source | Endpoint | Used for | Notes |
|---|---|---|---|
| Open-Meteo Forecast | `api.open-meteo.com/v1/forecast` | High-res blend at base, mid and summit (one call with comma-separated lat/lon/elevation). Hourly: temperature_2m, snowfall, rain, showers, precipitation, precipitation_probability, freezing_level_height, wind_speed_10m, wind_gusts_10m, wind_direction_10m, cloud_cover, weather_code. `past_days=1`, `forecast_days=11`, `timezone=auto`. | Free and non-commercial; attribution required (CC BY 4.0). |
| Open-Meteo Forecast (multi-model) | same, with `models=gfs_seamless,ecmwf_ifs025,gem_seamless,icon_seamless` | Per-model hourly snowfall at mid, 16 days | Keys come back as `snowfall_<model>`. GEM and ICON end around days 7–10. |
| Open-Meteo Ensemble | `ensemble-api.open-meteo.com/v1/ensemble`, `models=gfs_seamless` and `ecmwf_ifs025` (two calls) | Hourly snowfall per member (about 31 + 51 = 82 members), 16 days | Heavy against the rate limit. Keys are `snowfall`, `snowfall_member01` and so on. |
| NWS alerts | `api.weather.gov/alerts/active?point=lat,lon` | Active watches and warnings, US sites | A User-Agent with contact info is required. |
| NWS AFD | `api.weather.gov/products/types/AFD/locations/{office}` | Optional "Read the NWS discussion" link only | No parsing needed. |
| NRCS SNOTEL (AWDB REST) | `wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data` | Observed snow depth (SNWD) and SWE (WTEQ), daily for 45 days plus hourly for 4 days | Used for the "observed" panel and for verification. |

**Rate limits.** Open-Meteo's free tier limits calls per minute, hour and day, and ensemble requests count heavily. The prototype got HTTP 429s when pulling six sites back to back. Requirements:
- Space site pulls about 20 s apart.
- On 429, wait 65 s and retry, up to 6 tries; on other errors use exponential backoff.
- Run on a schedule aligned to model runs, not on every page load. The frontend never calls upstream APIs.
- Cache raw responses to disk (gzipped) for 24 h for debugging and reprocessing.

**Schedule.** Default is 4 runs a day, at 03:30, 09:30, 15:30 and 21:30 UTC (about 3–4 h after each 00/06/12/18Z cycle lands on Open-Meteo). Make it configurable. Ensembles can be pulled 2× a day to save quota.

### 6.2 Units and conventions

- Store metric (as received). Convert at the API layer with `?units=imperial|metric`. Imperial is the default: inches, °F, ft, mph.
- All period and day boundaries use the **location's local time** (Open-Meteo `timezone=auto`). Treat timestamps as local wall time throughout. The prototype handles this in the browser by parsing as UTC and formatting with UTC formatters; keep that approach or do it properly server-side.
- **Snow level = freezing level − 1,000 ft** (a configurable constant).

### 6.3 Derived metrics

Port these from `reference/pull.py`. They are the core of the product.

1. **Day/night periods:** 12 h periods, day 06:00–18:00 and night 18:00–06:00 local (a night belongs to the evening's date). Label them "Today / Tonight / Sun / Sun night…". The first period may be partial. Drop a trailing fragment shorter than 6 h. Show 20 periods (10 days).
2. **Consensus snowfall per period:**
   - While at least 3 deterministic models are available: the **median** of GFS, ECMWF, GEM and ICON period totals, plus the high-res blend for the first 4 periods.
   - When fewer than 3 models remain: the **ensemble mean**.
   - Store which basis was used and show it in the UI.
   - Do not use Open-Meteo `best_match` alone past about day 5. In the prototype it tracked the GFS alone and showed a 50 in storm that no other model supported.
3. **Ensemble statistics:** per period and per day, the 10th, 50th and 90th percentile and mean of member totals, plus running-total percentiles over 15 days. Skip a window if fewer than 10 members cover it.
4. **Windows:** "Next 5 days" is periods 0–9 and "Days 6–10" is periods 10–19. For each, store the consensus total, ensemble p10/p50/p90, and **probability of ≥ 1, 6 and 12 in**, defined as the share of members meeting the threshold.
5. **Precipitation type per hour and period:** snow, rain, mix or none, from snowfall vs rain plus showers (thresholds in the reference).
6. **Snow quality:** a snow-to-liquid ratio and label from the median temperature during snowing hours: ≥ 31°F "Heavy & wet" (8:1), 26–31 "Average" (11:1), 19–26 "Light" (14:1), < 19 "Dry & fluffy" (17:1). Make the bands configurable.
7. **Elevation bands:** for base, mid and summit, store the current temperature, 24 h low and high, and snow for the last 24 h, next 24 h and next 5 days.
8. **Period extras:** water equivalent, rain, high and low temperature, lowest snow level, maximum sustained wind and gust, mean cloud cover, maximum precipitation probability.

### 6.4 Rule-based flags (replaces AI summaries)

Deterministic and unit-tested. Each flag is `{site, type, severity, period_key?, value, text}`, where `text` is a short template string. They show as badges, never as paragraphs.

| Flag | Rule (defaults, all configurable) |
|---|---|
| `powder_day` | A day+night pair with consensus ≥ 6 in and quality not "Heavy & wet" → badge on the overview row and the period bar |
| `storm_incoming` | Any 48 h window in the next 5 days with consensus ≥ 12 in, or P(≥ 12 in) ≥ 40% |
| `model_outlier` | A model's 10-day total > max(2 × ensemble p90, ensemble p90 + 6 in) → "GFS far above ensemble (50 in vs 5 in)" |
| `low_confidence` | (p90 − p10) / max(p50, 1) > 3 for the next-5-day window |
| `rain_on_snow` | ptype rain or mix at mid with ≥ 0.25 in water while station depth > 0 |
| `snow_level_crossing` | Snow level drops below the base elevation (snow to base) or rises above mid (rain at mid) within 72 h |
| `wind_hold` | Gusts ≥ 45 mph at summit during 09:00–16:00 |
| `nws_alert` | Any active NWS alert (event name) |
| `best_day` | Per site, the next-10-day day period with the highest consensus × quality weight |

### 6.5 Verification (forecast vs observed)

For SNOTEL sites:
- Store each run's 24 h consensus forecast for the next day.
- When the day passes, compare it to the observed change in SNOTEL snow depth (and SWE × the quality ratio as a second estimate).
- Show a season scorecard per site: bias, mean absolute error and hit rate for ≥ 3 in days, for the consensus, each model and the ensemble median.

This is the "really good scripts" payoff: over time it tells you which model to trust at which location.

## 7. Database schema (SQLite)

```
runs(id, started_at, finished_at, status, errors_json)
sites(id, name, region, country, lat, lon, tz, config_json)
periods(run_id, site_id, idx, key, date, kind, label, hours, cons, basis,
        hr, gfs, ecmwf, gem, icon, ens_mean, ens_p10, ens_p50, ens_p90,
        liq, rain, tmin, tmax, snowlvl_min, wind_max, gust_max, cloud,
        pop_max, ptype, quality)
hourly(run_id, site_id, t, snow, liq, rain, temp, snowlvl, pop, wind, gust,
       wdir, cloud, ptype, quality)              -- keep latest 2 runs only
daily_models(run_id, site_id, date, gfs, ecmwf, gem, icon, *_cum,
             ens_p10, ens_p50, ens_p90, ens_cum_p10, ens_cum_p50, ens_cum_p90,
             snowlvl_min)
elevations(run_id, site_id, band, label, elev_m, temp_now, tmin24, tmax24,
           last24, next24, next5)
windows(run_id, site_id, window, cons, p10, p50, p90, prob1, prob6, prob12)
flags(run_id, site_id, type, severity, period_key, value, text)
obs_snotel(site_id, date, depth_in, swe_in)       -- upsert daily
verification(site_id, date, source, forecast_in, observed_in)
alerts(run_id, site_id, event, headline, severity, onset, ends)
```

Retention: keep `periods`, `windows`, `flags` and `verification` for the whole season, and `hourly` and `daily_models` for the last 2 runs only. VACUUM weekly.

## 8. API (FastAPI, read-only)

All responses are JSON with `?units=` support and carry `run_id` and `generated_at`. Send `Cache-Control: public, max-age=300` so Cloudflare can cache.

| Endpoint | Returns |
|---|---|
| `GET /api/health` | Last successful run, age, errors |
| `GET /api/sites` | Config list plus the overview row per site (now, last 24 h, windows, flags, alert count, station depth) |
| `GET /api/sites/{id}` | Everything for the location page: periods, elevations, windows, flags, alerts, links, SNOTEL 30 days |
| `GET /api/sites/{id}/hourly?hours=120\|240` | Hourly rows |
| `GET /api/sites/{id}/models` | 15-day per-model and ensemble daily plus running totals |
| `GET /api/sites/{id}/verification` | Season scorecard plus the daily pairs |
| `GET /api/runs?limit=20` | Run history (for a small status page) |

## 9. Frontend

Recommended stack: Vite + TypeScript + Svelte (or Preact) as a static build served by `api`. Use **uPlot** for the hourly charts (fast with 240 points × 6 charts on a phone) and d3 or hand-rolled SVG for the period bars and model chart. Claude Code may choose otherwise, but it must be a static bundle with no server-side rendering.

### 9.1 Pages

1. **Overview**
   - A ranked table of locations: last 24 h, next 5 days (big number), ensemble range, chance of ≥ 6 in, days 6–10, a 10-day day/night bar sparkline, and flag badges.
   - Sort by next 5 days, days 6–10 or last 24 h.
   - Tap a row to open the location.
2. **Location**
   - Header: name, region, forecast elevation, alert banner.
   - Tiles: last 24 h, next 5 days (with range), days 6–10 (with range), and now (temperature, snow level, gusts).
   - Flag badges.
   - **Day/night snowfall bars** for 10 days, labelled in inches, with night bars visually distinct and ensemble p10–p90 whiskers. Tap a bar for a detail panel: each model, high-res, water, rain, type, quality, high and low, snow level, wind and gust, cloud, precipitation chance.
   - **Stacked hourly charts** on one shared time axis, with night shading and day separators, in this order: snowfall (per-hour bars plus running total), precipitation (water, colored by snow/mix/rain, plus probability line), temperature (with 32°F line), snow level (with base, mid and summit reference lines), wind (sustained plus gust band) and cloud cover. **Synced crosshair:** hovering or dragging on any chart shows values on all of them. Toggle between 5 and 10 days.
   - **Day-by-day table** of the 20 periods with all period metrics; secondary columns hide on narrow screens.
   - **Base / mid / summit table.**
   - **Probability bars:** ≥ 1, 6 and 12 in for both windows.
   - **Model agreement chart:** 15-day running totals, ensemble band, median line, thin model lines with end labels.
   - **Observed snow depth** (SNOTEL, 30 days) and the **verification scorecard** (section 6.5).
   - Links: radar, NWS forecast, avalanche center, roads.
3. **Compare:** pick 2–4 locations and see their day/night bars stacked on the same scale.
4. **Status** (small): last runs, errors and data age.

### 9.2 UX requirements

- Mobile first, readable at 380 px, with no horizontal page scroll (tables scroll inside their card).
- PWA: manifest, icons, a service worker that caches the app shell and the last API responses so the app opens offline and shows data with a "stale" note.
- Dark and light themes from `prefers-color-scheme`, plus a manual toggle. Use a colorblind-safe palette.
- Unit toggle (imperial/metric), saved in localStorage.
- Every chart has accessible tooltips that stay inside the viewport and work with touch.
- A stale-data banner if the last successful run is more than 12 h old.
- Attribution footer: "Weather data by Open-Meteo.com (CC BY 4.0), NWS, NRCS SNOTEL."

## 10. Deployment and access

1. Buy or use a domain on Cloudflare (for example `snow.<domain>`).
2. Create a Cloudflare Tunnel (Zero Trust → Networks → Tunnels), copy its token into `.env` as `TUNNEL_TOKEN`, and route the hostname to `http://api:8000`.
3. Set up Cloudflare Access: create a self-hosted application for the hostname, with a policy that allows listed emails (one-time PIN login). Add friends by email.
4. `docker compose up -d`. No router port forwarding.
5. Optional: a Cloudflare cache rule for `/api/*`, honoring origin headers.

README must include: first-time setup, adding a location, adding a friend, backups, updating (`git pull && docker compose up -d --build`), and troubleshooting (429s, tunnel down, stale data).

## 11. Quality requirements

- **Tests (pytest):** period bucketing (including the partial first period and the midnight boundary), the consensus basis switch, percentiles and probabilities, ptype and quality bands, each flag rule, and unit conversion. Use fixtures built from saved real Open-Meteo responses.
- **Resilience:** one site failing must not block others. A failed run keeps the previous good data and records the error. Partial ensemble failure still produces deterministic output.
- **Frontend chart tests:** a smoke test renders each chart with fixture data and checks that every path and point stays inside the chart's bounds. The prototype once drew all lines off-chart because a d3 scale was built as `scaleLinear([a,b])`, which sets the range, not the domain.
- **Empty data:** no alerts, no SNOTEL, or no snow in the forecast must render as clean empty states, not errors.
- **Logging:** structured JSON logs. `/api/health` is used by Docker's healthcheck.

## 12. Milestones

1. **Pipeline:** config, worker, SQLite schema, port of `reference/pull.py` logic, tests, CLI. Done when a run for all 6 sites populates the DB and tests pass.
2. **API plus core UI:** Overview and Location pages with period bars, hourly stack and tables. Done when it matches or beats the prototype on a phone.
3. **Hosting:** Docker Compose, Cloudflare Tunnel plus Access, PWA, README. Done when a friend can open it from their phone.
4. **Analysis:** flags, verification scorecard, Compare page.
5. **Alerts (optional):** ntfy push when `powder_day` or `storm_incoming` first fires for a followed site.

## 13. Known pitfalls from the prototype

- The Open-Meteo `best_match` long range follows one model; always compute consensus from individual models plus ensembles.
- Ensemble API responses are large (82 members × 384 h). Request only `snowfall` and parse incrementally if memory matters.
- The ECMWF ensemble ends around day 15 and GFS deterministic runs to 16, so stop drawing each series where its data ends rather than plotting zeros.
- Open-Meteo `snowfall` is in cm and derived from precipitation; label it as model snowfall, not measured depth.
- TLS handshakes to Open-Meteo occasionally time out, so retries are required.
- Canadian sites have no SNOTEL or NWS. Possible later sources: BC snow pillows (BC River Forecast Centre) and Avalanche Canada weather stations.

## 14. Open questions for the owner

- Mini PC OS and CPU architecture (affects base images).
- Domain name to use.
- Whether to keep the Claude-hosted dashboard and its scheduled task running in parallel during the build (recommended until milestone 3).

## Appendix: reference files

- `reference/pull.py`: working data pull and all derived metrics (v2).
- `reference/build_datasets.py`: flattening into row tables (mirrors the proposed schema).
- `reference/dashboard.html`: the prototype UI (d3). Chart designs, colors, layout and interactions to replicate. It depends on the Claude dashboard runtime (`dash.data`, `dash.onData`), which must be replaced with fetches to `/api`.
- `reference/sample/raw/`: one real run of `pull.py` (per-site JSON) for test fixtures. `reference/sample/datasets/`: the same run flattened by `build_datasets.py` (summaries.json and posts.json are from the Claude-written prototype and are not needed).
