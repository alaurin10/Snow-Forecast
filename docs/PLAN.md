# Snow Watch: build plan

Draft v2, 4 Nov 2026. Replaces v1 (17 Oct 2026, in git history). Builds on `docs/SPEC-draft.md` and the prototype in `docs/reference/`. Where this plan and the draft spec disagree, this plan wins; section 1.3 lists every change.

---

## 0. In one paragraph

Snow Watch is a self-hosted, OpenSnow-style forecast dashboard for ski resorts and backcountry zones, used from phones and desktops by the owner and invited friends. The owner picks the locations inside the app; everyone else sees the same list, read-only. A Python worker on the mini PC pulls free model data four times a day: Open-Meteo, NWS, SNOTEL and the avalanche centers. It computes a model consensus with honest uncertainty ranges and stores a ready-to-render document per location in SQLite. A FastAPI service serves those documents plus a SvelteKit single-page app with hand-built SVG charts. Everything runs on the Proxmox Docker VM at home and is reached at `https://snow.andrewlaurin.com` through the existing Cloudflare Tunnel, behind Cloudflare Access. It installs on a phone as a PWA.

## 1. Product

### 1.1 Settled decisions

| Decision | How this plan implements it |
|---|---|
| Hourly charts follow the consensus | Per-period scaling of the hourly series (4.2), with a test that hourly sums equal the period totals |
| Ensemble range fix | Running totals computed per ensemble; the pooled band stops where the shortest ensemble ends (4.3) |
| Backcountry layer | Avalanche danger, wind at ridge height with a loading rose, warming, refreeze, cloud layers, daylight. **The app never scores whether a tour is safe** (4.6) |
| Chart rules | One y-axis per chart, enforced by the shared `Frame` component. One crosshair across the hourly charts, with each value shown in its chart's header (2.4) |
| Stack | Python worker, FastAPI, SQLite, SvelteKit with hand-built SVG charts, Docker Compose, Cloudflare Tunnel and Access (5) |
| Locations | One list, managed by the owner in the app, visible to all invited viewers (2.3) |
| Hosting | Everything on the mini PC: app, database, backups and builds. No Railway, no cloud builds, no image registry (6) |
| Address | `snow.andrewlaurin.com`, one more hostname on the Home Assistant Cloudflared app's tunnel (6) |

### 1.2 Two jobs

| Job | Question it answers | What it needs most |
|---|---|---|
| **Resort day** | Where and when is the best ski day in the next 10 days? | Overnight and daytime snow, snow quality, rain risk, summit wind (lift holds), visibility, temperature |
| **Backcountry tour** | Is the snowpack and weather right for this zone on this day? | Official avalanche danger, storm snow in the last 72 h, wind speed and direction at ridge height (loading), warming and freezing level, rain on snow, visibility above treeline, daylight, overnight refreeze |

Each location has `kind: resort` or `kind: backcountry`. Both kinds get the same data. `kind` changes the order of the location page and which badges appear.

Design principles:
1. **Charts first, numbers labelled.** Every chart works at 380 px and with a thumb.
2. **One story.** The day/night bars, hourly charts, tables and overview must agree with each other.
3. **Honest uncertainty.** Show the consensus, its basis, the ensemble range and model disagreement side by side. Outliers are called out, never silently averaged in.
4. **Glance, then drill down.** Overview, then location, then period detail, then hourly.
5. **No prose, no AI.** Only short, rule-based badges.
6. **Never imply safety.** Show the official avalanche danger and the weather inputs, never a "safe to tour" verdict.

### 1.3 Changes from the draft spec

| # | Change | Why |
|---|---|---|
| 1 | Hourly charts and the elevation table use consensus data, not the high-res blend alone | In the 17 Oct sample, Crystal's hourly blend showed 15.2 in for days 6–10 while the consensus was 0.9 in. Past day 5 the blend follows GFS (GFS 14.7, ECMWF 0.3, GEM 1.5, ICON 0) |
| 2 | The multi-model call fetches temperature, precipitation, freezing level, wind and cloud at all three elevations | A consensus per elevation band, and model-spread bands on the temperature and snow-level charts |
| 3 | Short-range regional models for the first 48 h: HRRR and NBM (US), HRDPS (Canada) | Better terrain detail for "tomorrow". The model list is config |
| 4 | Backcountry layer (4.6) | The draft covered resorts well and touring barely |
| 5 | Storage is one precomputed document per location per run, plus a few history tables | The UI needs nested documents. Building them once per run keeps the API small and fast |
| 6 | The API serves metric only; the browser converts units | The unit toggle is instant and works offline, and each resource has one cache key |
| 7 | Probabilities are computed in the browser from sorted member totals per window | Exceedance curves and any threshold (1/6/12 in or 2/15/30 cm) without new server code |
| 8 | No charts with two y-axes | Two scales on one plot invite false comparisons. The running total moves to the chart header; the precipitation chance gets its own strip |
| 9 | Hand-built SVG charts instead of uPlot | Full control of look, theming and touch, and easy to test for out-of-bounds marks. 240 points × 6 charts is small for SVG |
| 10 | Compare becomes "Plan a day" | Choosing between places for one date is the decision you actually make |
| 11 | Locations live in the database and are managed in the app by the owner | The draft used a config file, which meant SSH and a restart for every new location |
| 12 | Owner and viewer roles from the Cloudflare Access identity | The owner edits the list; viewers can't. There is still no separate login inside the app |
| 13 | One image built on the mini PC, two services (api, worker). No `cloudflared` container; the existing HA tunnel is reused | Keeps everything at home and reuses what is already running |
| 14 | Snow depth from snow water and a temperature-based snow-to-liquid ratio, checked against SNOTEL (4.4) | Open-Meteo's snowfall uses a fixed 7:1 ratio, which under-reads cold, dry snow |

## 2. App design

### 2.1 Navigation and layout

- **Phone (< 768 px):** a bottom tab bar with **Overview · Calendar · Plan · More** (More holds Status, Settings, and Manage for the owner). Single column. Tables scroll inside their own card, so the page never scrolls sideways.
- **Tablet (768–1099 px):** same navigation; cards go two-up where they fit.
- **Desktop (≥ 1100 px):** a left rail with the nav plus the location list (name, next-5-day total, danger chip). Picking a location opens it in the main pane, like a mail client. The Overview becomes a dense table, with the calendar heatmap one click away.
- **Style:**
  - Quiet neutral surfaces with a single snow-blue accent.
  - A characterful display face for numbers and headings, and a plain UI sans for body text.
  - Tabular figures in tables and axes. 12 px card radius, no heavy shadows. Light and dark themes.
  - Self-hosted fonts and Meteocons icons (MIT licensed), so the PWA works offline.
  - Skeleton loading states, a stale banner after 12 h, and a footer like "Run 09:30 · next 15:30".
- **Viewer preferences** (units, theme, default elevation band, hidden locations, favourites first) are stored per device in the browser. The location list itself belongs to the owner.

### 2.2 Pages

**Overview**
- One row or card per location: name, region, kind icon, NWS alert and avalanche-danger chips, *Last 24 h*, a large *Next 5 days* with its ensemble range, *Days 6–10*, a 10-day day/night sparkline and flag badges.
- Sort by next 5 days, days 6–10, last 24 h or name. Filter by all, resorts or backcountry.

**Calendar**
- A heatmap with locations as rows and the 20 day/night periods as columns. Cells are shaded by snowfall, with inches printed in cells of 1 in or more.
- Answers "when and where" at a glance. Tapping a cell opens that location at that period.

**Plan a day**
- Pick a date and get one row per location: overnight and daytime snow, ski-day rating, summit gusts, high and low, sky, avalanche danger.
- Secondary mode: stack the day/night bars of 2–4 locations on one scale.

**Location**
- A sticky header holds the name, the region, and the **Base / Mid / Summit** switch, which drives the tiles and hourly charts. Labels are set per location, e.g. "Trailhead / Mid / High point". An NWS alert banner shows when there is one.
- Four sub-tabs. Resorts order them Forecast, Models, Backcountry, Observed; backcountry locations order them Forecast, Backcountry, Models, Observed.
  - **Forecast:**
    - Tiles: Last 24 h · Next 5 days (with range) · Days 6–10 (with range) · Now (temperature, snow level, wind).
    - Badges, and the ski-day rating for the next good day.
    - **Day/night bars** for 10 days. Tapping a bar opens a detail sheet (a bottom sheet on phones).
    - The **hourly stack** (2.4) and the 20-period table.
    - Backcountry locations get a compact danger strip at the top.
    - On desktop the hourly stack sits beside a side column that shows the crosshair day's detail, alerts and links.
  - **Backcountry:** section 4.6.
  - **Models:** model agreement (15-day running totals), chance of snow (exceedance curves for the next 5 days and days 6–10), how the forecast changed (last 10 runs), and the base/mid/summit table.
  - **Observed:** SNOTEL depth and SWE for 30 days, the verification scorecard, and links (radar, NWS, avalanche center, roads).

**Manage** (owner only): section 2.3.

**Status:** the last runs, errors, data age per source, and Open-Meteo usage against the daily budget.

**Settings:** the per-device preferences in 2.1.

### 2.3 Managing locations (owner only)

- **Location list:**
  - Drag to reorder; this sets the default order for everyone.
  - Pause and resume. A paused location is neither fetched nor shown.
  - Edit, archive (history is kept), and **Refresh now**.
- **Add a resort:**
  - Search the ski-area catalog (section 3) by name. Picking a result auto-fills its name, region, country, coordinates, and base and summit elevations.
  - Mid defaults to base + 60% of the vertical, which matches the prototype's Crystal values. It stays editable.
- **Add a backcountry zone:**
  - On a topo map (Leaflet with OpenTopoMap tiles), drop a **trailhead** pin and a **high point** pin, plus an optional mid pin.
  - Each elevation band keeps its own coordinates. The Open-Meteo multi-point call already takes comma-separated lat/lon/elevation lists, and the prototype relies on that.
  - Elevations come from the Open-Meteo elevation API (a terrain model).
- **Auto-detect** (`POST /api/admin/locations/resolve`) fills in:
  - the timezone and country;
  - the NWS office and radar station (from NWS `/points`, US only);
  - the 3 best SNOTEL stations within 25 km, ranked by distance plus elevation difference (50 m counts like 1 km), so a station across a crest doesn't beat one beside the lifts;
  - the avalanche center and zone, found by point-in-polygon on the zone polygons;
  - default links (NWS forecast, radar, avalanche center, ECCC for Canada).

  The owner reviews and edits everything before saving.
- **Budget guard:** the form shows "adds ~120 of 10,000 daily Open-Meteo calls (total N)". The default cap is 25 active locations (`MAX_LOCATIONS`).
- **On save:** the API queues a `pull` job, the worker picks it up within about 15 s, and the forecast appears in about 1–2 minutes.
- **CLI fallback:** `docker compose run --rm worker snowwatch locations add|import|export`. The 6 prototype locations (`LOCATIONS` in `docs/reference/pull.py`) seed `config/seed-locations.yaml`.

### 2.4 Charts

The charts are hand-built SVG on `d3-scale`, `d3-shape`, `d3-array` and `d3-time-format`. Every chart:
- works at 380 px and with a thumb;
- has a table equivalent;
- has **only one y-axis**. `Frame.svelte` accepts exactly one y scale and has no prop for a second, so a dual-axis chart can't be built by accident.

**Hourly stack.** One shared time axis, night shading, midnight separators, a 5/10-day toggle and the elevation switch.
1. **Snowfall:** hourly bars. The header shows the value at the crosshair and the running total since now.
2. **Precipitation:** water per hour, with bars colored snow/mix/rain. Below it, a thin *chance* strip shaded from 0 to 100%.
3. **Temperature:** the consensus line, the model min–max as a light band, and a dashed 32 °F line.
4. **Snow level:** the consensus line and band, with base, mid and summit as labelled reference lines.
5. **Wind:** sustained wind as a line, with a gust band up to the gust value. Direction arrows every 3 h. Free-air ridge wind is a second line for backcountry locations and summits.
6. **Sky:** three strips for low, mid and high cloud.

**Crosshair.** One crosshair runs across every chart. Instead of a floating tooltip, every chart's header shows its value at the crosshair hour, so a finger never covers the data. At rest the crosshair sits on the current hour, so the headers read as "now". Horizontal drag scrubs; vertical swipes still scroll the page. A vertical marker shows where the consensus basis switches from models to ensemble.

**Other charts.**
- **Day/night bars:**
  - A day bar, and a darker night bar on a shaded band.
  - An ensemble 10–90% whisker, and the value on the cap when it is 0.5 in or more.
  - The weather icon and high/low under each day, and a star on powder days.
- **Model agreement:** the ensemble 10–90% band and median, thin model lines that stop where each model's data ends, end labels with leader lines, and the outlier model highlighted.
- **Chance of snow:** an exceedance curve ("chance of at least X") per window, with 1/6/12 in marked.
- **Overview sparkline and calendar heatmap:** share the bar colors and one sequential ramp.
- **Wind rose and danger pyramid:** section 4.6.

**Color.** Colorblind-safe, checked with a palette validator in both themes. Snow, mix and rain follow radar convention, which skiers already read without a legend. Night bars also sit on a shaded band, so telling day from night never depends on color alone.

| Role | Light | Dark |
|---|---|---|
| Snow (day bars, snowfall) | `#2a78d6` | `#3987e5` |
| Snow, night bars | `#184f95` | `#256abf` |
| Mixed precipitation | `#e87ba4` | `#d55181` |
| Rain | `#008300` | `#008300` |
| Temperature | `#eb6834` | `#d95926` |
| Snow level | `#6250d6` | `#9085e9` |
| Wind | `#1baf7a` | `#199e70` |
| Cloud and chance strips | single-hue sequential ramps | same, re-stepped for dark |
| Avalanche danger | North American danger scale colors, always with the number and the word | same |

## 3. Data sources

### 3.1 Calls

| Source | Used for | When |
|---|---|---|
| Open-Meteo forecast, default blend, 3 points (one per band) | Hourly: temperature_2m, apparent_temperature, precipitation, rain, showers, snowfall, precipitation_probability, freezing_level_height, weather_code, cloud_cover (total, low, mid, high), visibility, wind_speed_10m, wind_gusts_10m, wind_direction_10m, is_day. Daily: sunrise, sunset, daylight_duration. `past_days=3`, `forecast_days=11` | every run |
| Open-Meteo multi-model, 3 points | Per model: snowfall, precipitation, rain, temperature_2m, freezing_level_height, wind_speed_10m, wind_gusts_10m, wind_direction_10m, cloud_cover. Models: `gfs_seamless`, `ecmwf_ifs025`, `gem_seamless`, `icon_seamless`, plus `ncep_hrrr_conus` and `ncep_nbm_conus` (US) or `gem_hrdps_continental` (Canada). 16 days | every run |
| Open-Meteo upper air, 1 point (summit), all models except NBM | Wind speed and direction at 850 and 700 hPa; temperature and geopotential height at 850, 700, 600 and 500 hPa. Pressure-level values don't depend on the requested elevation, so one point serves all three bands. 16 days | every run |
| Open-Meteo ensemble, mid only | Snowfall per member: GEFS `gfs_seamless` (31), ECMWF ENS `ecmwf_ifs025` (51), GEPS `gem_global` (21). 16 days | 2×/day, after 00Z and 12Z |
| Open-Meteo elevation and geocoding | Terrain elevation for map pins; place search | Manage only |
| NWS `/points/{lat},{lon}` and `/alerts/active?point=` | Forecast office and radar station; active watches and warnings (US). A User-Agent with contact info is required | when adding a location; every run |
| NWS AFD | Link to the forecast discussion | daily |
| NRCS SNOTEL (AWDB REST) | Station list (nearest SNOTEL). Daily SNWD, WTEQ, TOBS and PREC for 45 days; hourly SNWD and TOBS for 4 days | weekly (stations); every run |
| avalanche.org `v2/public/products/map-layer` | US zone polygons with `danger_level` (1–5, −1 = no rating), `danger`, `start_date`, `end_date`, `link`, `center_id`, `travel_advice`. The zone forecast product gives danger by elevation band, the problems, and issue and expiry times | zones weekly; forecasts 2×/day plus about 07:30 PT (centers publish 6–10 am MT) |
| Avalanche Canada | Zone polygons from `avalanche-canada/forecast-polygons` (`canadian_subregions.geojson`) and the forecast products API | zones weekly; forecasts 2×/day |
| OpenSkiMap / openskidata.org ski-area GeoJSON | Resort catalog for search; the US and Canada subset is imported into SQLite | monthly |
| OpenTopoMap tiles (loaded by the browser, with attribution) | Map in the Manage wizard and the location mini-map | on view |

**Verified live on 4 Nov 2026.** `snowwatch check-sources` regenerates `docs/SOURCES.md` with the full details. In short:

| Item | Result |
|---|---|
| Model reach | GFS 16 d, ECMWF IFS ~15 d, GEM ~10 d, ICON ~7.5 d, NBM ~11 d, HRRR and HRDPS ~2 d |
| `freezing_level_height` | Only GFS, ICON and HRRR. Derived from pressure-level temperatures for the others (4.5) |
| Pressure levels | GFS, ECMWF, GEM, ICON, HRRR and HRDPS; NBM has none |
| `visibility` | GFS and HRRR only |
| Snowfall ratio | Fixed 0.7 cm of snow per mm of water (7:1) for every model |
| Ensembles | GEFS 31 members × 16 d, ECMWF ENS 51 × ~14 d, GEPS 21 × 16 d |
| Elevation API | Several points per call |
| NWS `/points` | `cwa`, `gridId/X/Y`, `radarStation`, `timeZone`, `forecastZone` |
| SNOTEL stations | `stations?stationTriplets=*:WA:SNTL` returns every station with lat/lon/elevation (ft) |
| avalanche.org | Map layer: 93 zones. `product?type=forecast&center_id=&zone_id=` returns `danger[{lower, middle, upper, valid_day}]` for today and tomorrow, `forecast_avalanche_problems`, `published_time`, `expires_time` |
| Avalanche Canada | `forecasts/en/areas` (GeoJSON) and `forecasts/en/products` (`report.dangerRatings[{date, ratings{alp, tln, btl}}]`, `problems`, `dateIssued`, `validUntil`). Area ids change through the season, so zones are found by point |
| OpenSkiMap | 21 MB GeoJSON, updated daily. 845 named, operating downhill areas in the US and Canada, 784 with min/max elevation (Crystal: 1,344 / 2,072 m) |

The avalanche.org terms say danger displays "must be published and expired accordingly", and third-party use must not change the intent of the information.

The pipeline treats a missing model or variable as normal, and the model list is config (`config/forecast.yaml`).

### 3.2 Budget

Open-Meteo's free tier is about 10,000 weighted calls per day, with per-hour and per-minute caps as well. A call's weight is roughly locations × (days ÷ 14) × (variables ÷ 10), where variables multiply by models and by ensemble members.

| Call | Weight (US location) |
|---|---|
| Blend, 3 points, 21 variables, 14 days | 6.3 |
| Multi-model, 3 points, 9 variables × 6 models, 16 days | 18.5 |
| Upper air, 1 point, 12 variables × 5 models, 3 past + 16 days | 8.1 |
| Ensembles, 1 point, 103 members, 16 days | 11.8 |
| **Per location per day** (4 full runs, ensembles twice) | **~150** |
| **25 locations per day** (the default cap) | **~3,750** (37% of the free tier) |

`snowwatch budget` prints the current estimate.

The worker records the estimated weight of every call, and the Status page and the Manage budget guard show the total.

Throttling from the prototype stays:
- Locations are spaced 20 s apart.
- A 429 waits 65 s and retries, up to 6 tries; other errors back off exponentially.
- A home IP should see far fewer 429s than the prototype's shared cloud IP did.

Runs are at 03:30, 09:30, 15:30 and 21:30 UTC, about 3–4 h after each model cycle lands.

### 3.3 Later sources (not in v1)

NWAC telemetry stations, BC River Forecast Centre snow pillows, Avalanche Canada weather stations, Synoptic/MesoWest, a radar layer, and resort webcams.

## 4. Analysis

### 4.1 Ported from `docs/reference/pull.py`

Reuse `period_key`, `period_label`, `pct`/`median`, `ptype`, `quality`, the consensus block in `build()`, `window()`, `pull_snotel`, `pull_alerts`, and the retry logic in `get()`.

- **Periods:** day 06–18 and night 18–06, local time; a night belongs to its evening's date. The first period may be partial, a trailing fragment under 6 h is dropped, and 20 periods are shown.
- **Consensus:**
  - While at least 3 deterministic models cover the period: their median.
  - In the first 4 periods, the short-range models and the high-res blend join that median.
  - After that: the ensemble mean.
  - The basis is stored per period and shown in the UI.
- **Windows:** "Next 5 days" is periods 0–9 and "Days 6–10" is periods 10–19. Each stores the consensus total, ensemble p10/p50/p90, and the sorted member totals for probabilities. A window with fewer than 10 members is skipped.
- **Other:** precipitation type and quality bands, period extras (water, rain, high and low, lowest snow level, maximum wind and gust, mean cloud, maximum precipitation chance), and series that stop where their data ends instead of dropping to zero.

A **parity test** runs the prototype logic and the new pipeline on the same captured responses. Periods, consensus and windows must match before the intentional changes below are layered on.

### 4.2 Hourly series that add up to the bars

The charts must add up to the bars. For each band and each period:
- **Snow and water:**
  - Take the hourly *shape* from the short-range model median (first 48 h) or the deterministic model median (after that).
  - Scale it so the period sum equals the period consensus.
  - If the shape is all zero but the consensus isn't, spread the amount over the hours where any model shows precipitation, weighted by how many models agree, or evenly as a last resort.
- **Continuous variables** (temperature, freezing level, wind, gusts, cloud): the hourly median across models, with the model min–max as a band. In the first 48 h the line follows the short-range models.
- **Precipitation type per hour:** from the consensus snow fraction (snow water ÷ total water): ≥ 0.9 is snow, ≤ 0.1 is rain, anything between is mix.
- **Tests:**
  - Within each period, the hourly values sum to the consensus (±0.01).
  - A regression test on the 17 Oct Crystal sample expects days 6–10 to come out at about 0.9 in, not 15.2 in.

### 4.3 Ensemble running totals per system

In the prototype, the 15-day running-total percentiles silently switch member sets when the ECMWF ensemble ends a day before GEFS. In the 17 Oct sample, Crystal's 90th percentile drops from 6.0 in to 4.8 in on the last day because only GEFS members remain.

- **Per system:** compute member running totals separately for each ensemble (GEFS, ECMWF ENS, GEPS), and store per-system percentiles.
- **Pooled band:** the 10–90% band covers only the days where every system has data, and stops there. Each system's own band is kept for every day it covers, so the chart draws the GEFS band (dashed, labelled) all the way to day 16. Nothing is spliced, so no line dips.
- **Test:** every running-total percentile is non-decreasing over time, because it is an order statistic of non-decreasing sequences.

### 4.4 Snow-to-liquid ratio

Open-Meteo's `snowfall` is snow water times a fixed 0.7 cm per mm (7:1), confirmed for every model. That under-reads cold, dry snow, which typically falls at 12–20:1.
- **Method:** build the consensus on **snow water**, then convert to depth with the period's snow-to-liquid ratio, taken from the median temperature during snowing hours:

  | Temperature | Ratio | Label |
  |---|---|---|
  | ≥ 31 °F | 8:1 | "Heavy & wet" |
  | 26–31 °F | 11:1 | "Average" |
  | 19–26 °F | 14:1 | "Light" |
  | < 19 °F | 17:1 | "Dry & fluffy" |

  The bands are configurable.
- **Consistency:** the hourly series uses the same period ratio, so sums still match the bars. The period detail sheet shows the method.
- **Default:** the verification scorecard (4.8) compares raw model snowfall and ratio-adjusted depth against SNOTEL. Raw snowfall stays the default until a few weeks of scores exist; then the better method becomes the default per location.

### 4.5 Per elevation band

- The period consensus, windows and hourly series are computed for base, mid and summit, each at its own coordinates.
- Ensembles are fetched at mid only. Their percentiles at base and summit are scaled by the ratio of model-consensus totals between bands and labelled "estimated".
- **Freezing level** comes from the model where it exists (GFS, ICON, HRRR). For the others it is found from the upper-air call: the 0 °C crossing between pressure levels, interpolated against geopotential height, or extrapolated down from `temperature_2m` with a 6.5 °C/km lapse rate when the whole column is below freezing.
- Snow level = freezing level − 1,000 ft (305 m, configurable).

### 4.6 Backcountry layer (no safety score anywhere)

Shown side by side:
- **Avalanche danger:**
  - Today and tomorrow, by alpine, treeline and below treeline, drawn as a danger pyramid in the standard North American colors with the number and the word.
  - The avalanche problems, the issue and expiry times, the center's name, and a prominent link to the full forecast.
  - An expired forecast shows as **Expired** and is never presented as current. Off-season shows **No rating**. The center's text is shown as published, never reinterpreted.
- **Ridge-height wind:** 850 and 700 hPa wind interpolated to summit elevation using geopotential height. It appears as a second line on the wind chart.
- **Loading rose:** an 8-sector histogram of wind direction weighted by snowfall × wind speed, for the last 72 h and the next 48 h. Its label names the likely loaded aspects, e.g. "SW wind, loading NE aspects".
- **Warming:** freezing-level rise and temperature change over 24 h, and rain on snow.
- **Refreeze** per band: Good, Partial or None, from the overnight low and clear-sky hours.
- **Sky above treeline:** low, mid and high cloud plus daytime visibility.
- **Daylight:** sunrise, sunset and daylight duration.
- **Storm snow:** the last 72 h and the next 48 h at summit.

### 4.7 Ski-day rating and flags

**Ski-day rating** (resorts), per day during lift hours (09:00–16:00, configurable).
- It weighs new snow (overnight plus day consensus), snow quality, rain at mid, the maximum summit gust, low cloud and visibility at mid, and temperature.
- The result is one of *Powder, Great, Good, Fair, Poor*, plus the 1–3 reasons that decided it, e.g. "9 in overnight" or "gusts 55 mph at summit: lift holds likely".
- Thresholds are config, and every rule is unit-tested.

**Flags.** Each flag is `{site, type, severity, period_key?, value, text}`. Defaults are configurable.

| Flag | Rule |
|---|---|
| `powder_day` | A day+night pair with consensus ≥ 6 in, and quality not "Heavy & wet" |
| `storm_incoming` | Any 48 h window in the next 5 days with consensus ≥ 12 in, or P(≥ 12 in) ≥ 40% |
| `model_outlier` | A model's 10-day total > max(2 × ensemble p90, ensemble p90 + 6 in) |
| `low_confidence` | (p90 − p10) / max(p50, 1) > 3 for the next-5-day window |
| `rain_on_snow` | Rain or mix at mid with ≥ 0.25 in water while the station depth > 0 |
| `snow_level_crossing` | Snow level drops below base, or rises above mid, within 72 h |
| `wind_hold` | Gusts ≥ 45 mph at summit during lift hours |
| `nws_alert` | Any active NWS alert |
| `best_day` | Per location, the day period in the next 10 days with the highest consensus × quality weight |
| `wind_loading` | Sustained free-air wind ≥ 25 mph with ≥ 4 in of snow in 24 h |
| `rapid_warming` | Freezing level up ≥ 3,000 ft in 24 h, or temperature up ≥ 15 °F |
| `refreeze` | Good overnight refreeze after a warm day (spring) |
| `avalanche_danger` | Official rating ≥ 4 in any band; the text quotes the center |

### 4.8 Trend and verification

- **Trend:** every run stores the per-day consensus and per-model totals per location. The Models tab shows how the next-5-day total and each upcoming day changed over the last 10 runs ("is the storm trending up or down?").
- **Verification:** each run's next-day forecast is compared with the observed SNOTEL depth change, and with SWE × ratio as a second estimate. The season scorecard per location shows bias, mean absolute error and the hit rate for days of 3 in or more. It covers the consensus, each model, the ensemble median, and raw vs ratio-adjusted depth.

## 5. Architecture

### 5.1 Runtime

```
browser ─► Cloudflare Access ─► tunnel (HA Cloudflared app) ─► Docker VM :8090
                                                                 api (FastAPI: SPA + /api)
                                                                   │ reads; writes only locations + jobs
                                                                 SQLite (WAL, busy_timeout) on ./data
                                                                   ▲ writes
             Open-Meteo, NWS, SNOTEL, avalanche APIs ◄──────── worker (APScheduler + job poller + CLI)
```

| Service | Notes |
|---|---|
| `api` | `uvicorn snowwatch.api.app:app`. Serves `/` (the SPA) and `/api`. Writes only to `locations` and `jobs`. Docker healthcheck on `/api/health` |
| `worker` | Scheduler: 4 runs a day, ensembles and avalanche forecasts 2× a day, catalog/zones/stations weekly or monthly, a nightly backup, a weekly VACUUM. Polls `jobs` every 15 s. CLI via `docker compose run --rm worker snowwatch …` |

- **Image and resources:** one image (`snowwatch:local`) runs as both services. The Dockerfile is multi-stage: a Node build stage, then a Python 3.12 slim runtime. The target is under 300 MB of RAM idle, with `mem_limit` set on each service.
- **Database:** SQLite in WAL mode with `busy_timeout`, so the API's rare writes and the worker's short transactions don't collide.

### 5.2 Stack choices

| Layer | Choice | Reason |
|---|---|---|
| Pipeline | Python 3.12, uv, httpx, pydantic v2, APScheduler, stdlib sqlite3 | A direct port of the prototype with a small dependency set; no ORM needed |
| API | FastAPI + Uvicorn, PyJWT for Access tokens | Typed models double as the JSON contract; also serves the static build |
| Database | SQLite, WAL mode, plain SQL migrations | One file, no server, trivial backups |
| Frontend | SvelteKit (`adapter-static`, SPA fallback), TypeScript | Small bundles, and reactive SVG is natural in Svelte |
| Charts | Own SVG components on d3 modules | 2.4 |
| Maps | Leaflet with OpenTopoMap tiles | Light, and works with touch; used only in Manage and the location mini-map |
| PWA | `@vite-pwa/sveltekit` (Workbox) | App-shell precache, plus a network-first API cache with offline fallback |
| Types | Pydantic → JSON Schema → TypeScript, generated and checked in CI | Front and back can't drift |
| CI | GitHub Actions for lint and tests only | Deploys don't depend on it (6.3) |

### 5.3 Roles

- **Token check:** Cloudflare Access adds `Cf-Access-Jwt-Assertion` to every request that passes it. `auth.py` verifies the token against `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`, checking that the audience is one of `CF_ACCESS_AUDS`.
- **Roles:** an email in `ADMIN_EMAILS` gets the owner role; any other valid token gets the viewer role.
- **No token** (someone on the LAN using `http://<vm>:8090`): the viewer role, so admin routes return 403.
- **Edge block:** a second Access application covers the paths `/admin` and `/api/admin` with an owner-only policy. Cloudflare blocks admin pages at its edge, and the backend check still runs behind it.
- **Dev mode:** `DEV_ADMIN_EMAIL` is honoured only when `ENV=dev`.

### 5.4 Storage

| Table | Purpose | Retention |
|---|---|---|
| `locations(id, name, kind, region, country, tz, active, sort_order, bands_json, snotel_triplet, nws_office, radar_station, avy_center, avy_zone_id, links_json, catalog_ref, created_at, updated_at, archived_at)` | The managed list. `bands_json` is `[{band, label, lat, lon, elev_m}]` | permanent |
| `jobs(id, kind, location_id, status, requested_by, created_at, started_at, finished_at, error)` | On-demand pulls and refreshes | 30 days |
| `runs(id, started_at, finished_at, status, kind, errors_json, api_weight)` | Run log and budget | season |
| `snapshots(location_id, run_id, created_at, doc_gz)` | The precomputed location document the UI renders | last 8 per location |
| `forecast_daily(location_id, run_id, issued_at, target_date, source, snow_cm, water_mm)` | Trend and verification (mid band; consensus, each model, ensemble p10/p50/p90) | season |
| `obs_daily`, `obs_hourly` | SNOTEL | season; 7 days |
| `alerts`, `avalanche` | NWS alerts; danger, problems, issue and expiry times | season |
| `flag_log(location_id, type, key, first_run, last_run)` | When a flag first fired (for push alerts later) | season |
| `catalog_ski_areas`, `snotel_stations`, `avy_zones` | Lookups for Manage (zones stored as geometry JSON plus a bounding box) | refreshed |

- A failed location or run never replaces the last good snapshot.
- Raw responses are cached gzipped in `data/raw/` for 24 h.

### 5.5 API

All JSON, metric units, with `run_id` and `generated_at`. `ETag` is the run id, and responses carry `Cache-Control: public, max-age=300, stale-while-revalidate=3600`. Snapshot bodies are stored gzipped and sent as-is.

| Endpoint | Returns |
|---|---|
| `GET /api/health` | Last good run, its age, errors per source. 503 when data is over 12 h old |
| `GET /api/me` | Email and role |
| `GET /api/overview` | The location list plus overview rows: windows, member totals, the 20 period totals, flags, alert and danger chips, station depth |
| `GET /api/calendar` | Period totals for every location |
| `GET /api/locations/{id}` | The full snapshot: periods, hourly for all three bands, elevations, windows, flags, alerts, avalanche, links, SNOTEL for 30 days |
| `GET /api/locations/{id}/trend`, `/verification` | Forecast history for the last 10 runs; scorecard and daily pairs |
| `GET /api/plan?date=` | Plan-a-day rows |
| `GET /api/avalanche` | Every location's avalanche forecast, with expiry applied at request time (kept apart from the snapshots so an expired rating is never served as current) |
| `GET /api/runs?limit=20` | Run history and API usage |
| `GET /api/admin/catalog/search?q=` | Catalog matches |
| `POST /api/admin/locations/resolve` | Auto-detected fields for pins or a catalog pick |
| `POST`, `PATCH`, `DELETE /api/admin/locations[/{id}]`; `PUT /api/admin/locations/order` | Manage the list (DELETE archives) |
| `POST /api/admin/locations/{id}/refresh`; `GET /api/admin/budget` | Queue a pull; daily usage |

Size targets: the overview under 15 KB and a location document under 60 KB, both gzipped.

### 5.6 Repository layout

```
backend/
  pyproject.toml
  snowwatch/
    config.py auth.py http.py pipeline.py jobs.py scheduler.py cli.py
    sources/    openmeteo.py nws.py snotel.py avalanche_us.py avalanche_ca.py catalog.py elevation.py
    analysis/   periods.py consensus.py hourly.py ensemble.py slr.py elevations.py wind.py
                backcountry.py skiday.py flags.py trend.py verification.py
    locations/  resolve.py service.py
    store/      db.py migrations/*.sql backup.py
    api/        app.py public.py admin.py models.py
  tests/        fixtures/ (captured real responses, gzipped)
frontend/
  src/lib/charts/  Frame Bars Line RangeBand Strip Arrows Crosshair NightBands TimeAxis WindRose DangerPyramid
  src/lib/         api.ts units.ts time.ts format.ts prefs.ts types.gen.ts
  src/routes/      +page (overview) calendar plan location/[id] admin status settings
  static/          manifest, icons, fonts, meteocons
config/seed-locations.yaml
docker/Dockerfile
docker-compose.yml
.env.example
deploy/deploy.sh  deploy/snowwatch-deploy.service  deploy/snowwatch-deploy.timer
docs/PLAN.md  docs/RUNBOOK.md  docs/SPEC-draft.md  docs/reference/
```

## 6. Deployment on the mini PC

### 6.1 What runs where

| Where | What |
|---|---|
| Mini PC (HP EliteDesk 600 G3 Mini, Proxmox), Docker VM (Debian 12) | The app, the database, backups and builds |
| Mini PC, Home Assistant VM | The Cloudflared app that already runs the tunnel for `ha.` and `dash.` |
| Cloudflare (free) | DNS for `andrewlaurin.com`, the tunnel edge, the Access login |
| GitHub | Source code, and test-only CI. Deploys depend on it only for `git fetch` |

There is no Railway, no image registry, and no inbound port on the router. Tailscale stays for SSH and admin.

### 6.2 First-time setup

`docs/RUNBOOK.md` will spell these out step by step.

1. **Proxmox:** raise the Docker VM from 4 to 6 GB of RAM to give the SvelteKit build headroom; the host has about 6 GB unallocated. Confirm at least 5 GB of free disk.
2. **Clone:** clone the repo to `/opt/snow-forecast` on the VM, using a read-only deploy key since the repo is private.
3. **Configure:** copy `.env.example` to `.env` and set `TZ`, `NWS_CONTACT` (used in the NWS User-Agent), `ADMIN_EMAILS`, `CF_ACCESS_TEAM`, `CF_ACCESS_AUDS`, `MAX_LOCATIONS`, and an optional `HEALTHCHECKS_URL`.
4. **Start:** `docker compose up -d --build`. The api listens on LAN port **8090**; Home-Hub's dashboard already uses 8080.
5. **Initialise:** `docker compose run --rm worker snowwatch init`. This runs migrations, imports the catalog, the SNOTEL station list and the avalanche zones, seeds the 6 locations, and runs the first pull.
6. **Tunnel:** in Home Assistant, go to Settings → Apps → Cloudflared and add this to `additional_hosts`:
   ```yaml
   - hostname: "snow.andrewlaurin.com"
     service: "http://<docker-vm-ip>:8090"
   ```
   Restart the app; it creates the DNS record. This is the same step as in Home-Hub `docs/10-remote-access.md`.
7. **Access:** in Zero Trust → Access → Applications, create two applications, then copy both AUD tags into `.env`:
   - (a) `snow.andrewlaurin.com`: allow the owner plus a "snow-viewers" email group. Google login, with one-time PIN as a fallback. 30-day sessions, so phones rarely log in again.
   - (b) the paths `/admin` and `/api/admin`: owner only.

   **Never** leave the hostname without an Access application: a tunnel hostname without one is public.
8. **Auto-deploy:** install the deploy timer (6.3).
9. **Monitoring:**
   - Uptime Kuma: an HTTP monitor on `http://<docker-vm-ip>:8090/api/health`.
   - Healthchecks.io: a check pinged after each successful run and after each nightly backup.
   - Both match Home-Hub roadmap items M1 and M2.
10. **Check on cellular, with WiFi off:**
    - The Access login appears.
    - An incognito window stops at the Access page.
    - A friend's account gets a 403 on `/admin`.
    - The router has zero port-forward rules.

### 6.3 Updates and rollback

- **Auto-deploy:** `deploy/deploy.sh` is copied from Home-Hub `apps/dashboard/scripts/deploy.sh`. A systemd timer runs it every 5 minutes. It fetches `main`, fast-forwards, and runs `docker compose up -d --build` only when something changed. It is outbound-only: no webhook and no open port.
- **Failed builds:** a failed build leaves the running containers untouched, and the failure shows in `journalctl -u snowwatch-deploy`.
- **Rollback:** check out the previous commit and rebuild, or restore the Proxmox snapshot.

### 6.4 PWA behind Access

- **Manifest:** `<link rel="manifest" crossorigin="use-credentials">`.
- **Service worker:** caches the app shell and API responses, but never answers a navigation that Access wants to log in.
- **Expired login:** if an API call comes back as a login redirect, the app shows "Sign in again", which reloads the page.

### 6.5 Friends, backups, monitoring

- **Adding a friend:** add their email to the snow-viewers group in Cloudflare Access (free for up to 50 users).
- **Backups:**
  - Nightly: `VACUUM INTO data/backups/snowwatch-YYYYMMDD.db` (14 kept), plus a `locations.yaml` export as a readable copy of the list.
  - Weekly: the Proxmox backup of the Docker VM covers both.
  - Optional: an rclone copy off-site.
  - Only the location list and forecast history are irreplaceable; the forecasts regenerate on the next run.
- **Stale data:** `/api/health` returns 503 when the last good run is over 12 h old. Uptime Kuma alerts through ntfy or email (never through HA). The app shows a stale banner, and the PWA still opens with the last data.

## 7. Quality

- **Fixtures first:** `docs/reference/sample/raw/` holds `pull.py` *output*, not raw API responses. M0 adds `snowwatch capture-fixtures` to save real responses for all locations.
- **Backend unit tests (pytest):**
  - Period bucketing: the partial first period, midnight, and the DST change on 14 Mar 2027 (13 h and 11 h periods).
  - The consensus basis switch.
  - Hourly sums equal period totals; running-total percentiles never decrease; the Crystal days 6–10 regression.
  - Snow-to-liquid ratio and precipitation-type bands; percentiles and probabilities.
  - Every flag and ski-day rule.
- **Auth and Manage tests:**
  - Tokens signed with a test key: owner, viewer, no token, wrong audience, expired.
  - Resolve with canned NWS, elevation, SNOTEL and avalanche payloads; point-in-polygon lookup.
  - The location cap and the job queue.
  - The pattern from Home-Hub `apps/dashboard/tests/test_weather.py`: a broken upstream yields `None`, never a crash or an invented value.
- **Resilience:**
  - One location failing doesn't block the others.
  - A partial ensemble failure still produces deterministic output.
  - A missing model variable is tolerated.
- **Frontend:**
  - Vitest renders every chart from fixtures and asserts every rect, line and path is inside the plot area. The prototype once drew every line off-chart.
  - Empty states: no snow, no alerts, no SNOTEL, no avalanche product.
  - The Manage wizard, against a mocked API.
- **Visual checks:** Playwright screenshots of Overview, Location (each tab) and Manage at 380, 768 and 1280 px in light and dark, plus a check that the page never scrolls sideways. This follows the pattern in Home-Hub `apps/dashboard/scripts/screenshot.py`.
- **End to end on the VM:**
  - `snowwatch init` succeeds and `/api/health` is green.
  - Adding a location in the UI produces a forecast within 2 minutes.
  - The checklist in 6.2 step 10 passes.
- **Lint:** ruff, mypy, svelte-check, eslint, prettier. Structured JSON logs.

## 8. Milestones

M0–M3 is the first useful release, aimed at early-season use.

| # | Milestone | Done when |
|---|---|---|
| M0 | Foundations: repo layout, tooling, test-only CI, migrations including `locations`, seed file, `snowwatch capture-fixtures`, live checks of the sources in 3.1 | CI is green and real responses are captured for all 6 locations |
| M1 | Pipeline: sources, analysis port, 4.2–4.5, scheduler, job queue, CLI | A run fills the DB for all locations; the parity, hourly-sum and monotonic-band tests pass |
| M2 | API and Location page: Forecast and Models tabs, day/night bars with detail sheet, hourly stack with crosshair, tables | It beats the prototype on a phone (screenshots for review) |
| M3 | Ship it: Overview and Calendar, PWA, Docker, deploy timer, tunnel hostname, Access, health checks, backups, `RUNBOOK.md` | The owner and a friend open `snow.andrewlaurin.com` on cellular |
| M4 | Manage: owner role from the Access token, Manage page, add-resort (catalog) and add-zone (map pins) wizards with auto-detect, budget guard, first pull on save | The owner adds a resort and a tour zone from a phone and sees forecasts within about 2 minutes |
| M5 | Backcountry tab (4.6), ski-day rating, Plan a day | Both kinds of location read well on a phone |
| M6 | Flags, trend, SNOTEL panel, verification and the snow-ratio default, Status page. Optional: ntfy push alerts, a map view, webcams, Canadian observations | The scorecard shows after a week of runs |

## 9. Open items

1. **Data hosts:** the cloud build environment blocks them. Either add `api.open-meteo.com`, `ensemble-api.open-meteo.com`, `geocoding-api.open-meteo.com`, `api.weather.gov`, `wcc.sc.egov.usda.gov`, `api.avalanche.org`, `api.avalanche.ca` and `openskidata.org` to its allowed domains, or run `capture-fixtures` on the VM and commit the fixtures.
2. **Which friends to invite**, and any locations to add beyond the 6 prototype ones. For each tour zone: trailhead, typical high point, and its avalanche forecast zone.
3. **Push alerts:** decided in M6. They use the browser's Web Push API (no third-party app), for flags first raised in a run; setup is RUNBOOK step 10.
4. **The Claude-hosted prototype:** keep it running until M3 (recommended).

## 10. Risks

- **The tunnel rides the Home Assistant VM.** When HA restarts, the site is briefly unreachable from outside the house. If that becomes a problem, add a `cloudflared` service with its own tunnel token to this stack.
- **Avalanche data terms:** show ratings exactly as published and expire them on time. Confirm the terms for avalanche.org and Avalanche Canada before inviting friends; if needed, fall back to the overall rating plus a link.
- **Open-Meteo** is free for non-commercial use only, with no uptime promise, and model IDs change occasionally. Mitigations: a config-driven model list, missing models flagged on Status, and the last good data kept.
- **Model snowfall is derived, not measured.** Label it everywhere; the scorecard shows each model's bias per location over time.
- **Cloudflare Access with a PWA** has known login-loop issues; 6.4 handles them.
- **Daylight-saving changes** in period bucketing; covered by tests.
- **Docker VM headroom:** it already runs the Garmin stacks and the Home-Hub dashboard. Watch RAM during builds, and set `mem_limit` on each service.
