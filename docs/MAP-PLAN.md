# Map upgrade: wider and longer radar/forecast, and deeper terrain mapping

Research findings and an implementation plan for handoff. Every source below was
probed live on 2026-11-10 from a cloud sandbox unless marked "not verified".

## Context

The Map page today draws precipitation on the server (`backend/snowwatch/precip.py`)
as one palette PNG per time step over a box that follows the saved locations, and the
browser swaps pictures on one canvas (`frontend/src/lib/precipOverlay.ts`). Its limits:

- **Radar**: RainViewer free tiles, zoom 7 only, 2 h of history, no nowcast, type guessed from colour.
- **Forecast**: 48 h only. Canada and the northern US from HRDPS; the rest of the US from
  recoloured Iowa State HRRR picture tiles, then untyped NWS 6-hour polygons in tan.
- **Snow totals**: HRDPS only (Canada and northern US), 12/24/48 h, fixed 10:1.
- **Range**: the box follows the locations, so California and the US Rockies are only covered if a location is there.
- **Terrain**: AWS Terrarium tiles (really 10 m in the US, 20–30 m in Canada), satellite is
  Esri's undated mosaic, and there is no slope, aspect, shade, wind or avalanche-terrain layer.

Goal: cover western North America (BC, Alberta Rockies, US Rockies, California) with more
detail and up to 10 days ahead, and add terrain layers (finer elevation, slope/aspect,
sun and shade, wind loading, recent satellite, avalanche terrain), all from free sources,
and smooth on a phone. The owner chose to include an experimental, app-computed per-slope
hazard index in addition to showing bulletins as published.

## What the research found

All free and keyless. "Verified" means fetched and, for data files, decoded.

### Weather

| Need | Source | Coverage, resolution, reach | Access | Verified |
|---|---|---|---|---|
| Radar, past 3 h | ECCC GeoMet `RADAR_1KM_RRAI` (mm/h) and `RADAR_1KM_RSNO` (cm/h) | North American composite incl. US NEXRAD, 1 km, every 6 min, 16.9–67.2°N | WMS + our SLD (same call as HRDPS today) | 3000×3476 px over the whole West in 1.1 s, our colours |
| Radar precipitation type | `Radar_1km_SfcPrecipType` | Same grid; 12 classes (snow, mixed, rain, freezing rain, hail × intensity) | WMS, default style, recolour | Yes |
| Nowcast, next 72 min | `Radar_1km_RainPrecipRate-Extrapolation`, `Radar_1km_SnowPrecipRate-Extrapolation` | Same grid, 6-min steps | WMS + SLD | Time dimension confirmed |
| Forecast 0–48 h, Canada + northern US | HRDPS 2.5 km (in use) | hourly | WMS + SLD, WCS floats | In use |
| Forecast 0–48 h, US | NOAA HRRR 3 km on AWS `noaa-hrrr-bdp-pds` | hourly runs to 18 h, 00/06/12/18Z to 48 h; APCP, CSNOW/CRAIN/CFRZR/CICEP, ASNOW, GUST, UGRD/VGRD, `HGT:0C isotherm` | `.idx` + HTTP byte ranges (0.01–2 MB per field) | Decoded in 20–60 ms with `gribberish` |
| Forecast to 84 h, all of North America at 3 km | NOAA RRFS (operational since about 3 Nov 2026) on AWS `noaa-rrfs-ops-pds`, file `rrfs.tHHz.2dfld_awipsubset.3km.fNNN.na.grib2` | 3-hourly to 60 h, 6-hourly to 84 h; ASNOW, APCP, GUST; polar-stereographic 2830×4680 | byte ranges (ASNOW 2.9 MB) | Decoded in 0.2 s; `metadata.latlng()` gives the grid |
| Forecast 48–84 h, Canada | RDPS 10 km: `RDPS_10km_{Rain,Snow,FreezingRain}-Accum{3h,6h}`, `RDPS_10km_Snow-Accum` | hourly to 84 h, North America | WMS + SLD, WCS | Dimensions confirmed |
| Forecast to 10 days, Canada (global) | GDPS 15 km: `GDPS_15km_{Rain,Snow,FreezingRain}-Accum6h`, `GDPS_15km_Snow-Accum` | hourly to 84 h, 3-hourly to 240 h | WMS + SLD, WCS | Dimensions confirmed |
| Forecast to 11 days, US | NOAA NBM 2.5 km on AWS `noaa-nbm-grib2-pds` (`blend.tHHz.core.fNNN.co.grib2`) | hourly to 48 h, 3-hourly to ~192 h, 6-hourly to 264 h; APCP, ASNOW (variable density), SNOWLVL, SNOWLR, WIND/WDIR/GUST, TMP | byte ranges (0.6–1.5 MB per field) | ASNOW, SNOWLVL, APCP at f120 decoded |
| Snow level | `HRDPS-WEonG_2.5km_SnowLevelHeight` (also RDPS-, GDPS-WEonG); NBM `SNOWLVL`; HRRR `HGT:0C isotherm` | as each model | WMS/WCS; byte ranges | Yes |
| Wind | `HRDPS.CONTINENTAL_WSPD/WD/WGE`, `HRDPS-WEonG_2.5km_Wind{Speed,Dir,Gust}`, `RDPS_10km_Wind{Speed,Dir}_700mb`; HRRR GUST, UGRD/VGRD 10 m and 80 m; NBM WIND/WDIR | as each model | WCS; byte ranges | Coverage ids listed; HRRR GUST decoded |
| Snow on the ground | NOHRSC SNODAS (US + southern Canada, 1 km, daily, 5 MB tar of flat int16) at `noaadata.apps.nsidc.org/NOAA/G02158/masked/`; `CaLDAS-NSRPS_2.5km_SnowDepth` (Canada, 3-hourly) | | HTTPS; WCS | File listing and size; WCS id listed |
| Observed snowfall, last 6/24/48/72 h | NOHRSC National Snowfall Analysis `nohrsc.noaa.gov/snowfall_v2/data/YYYYMM/sfav2_CONUS_{6h,24h,48h,72h}_YYYYMMDDHH.tif` | US | GeoTIFF, 230 KB | Downloaded |
| Observed precipitation | NOAA MRMS on AWS `noaa-mrms-pds` (`MultiSensor_QPE_{01..72}H_Pass2`, `PrecipRate`, `PrecipFlag`), 1 km, 20–55°N, 130–60°W; ECCC `HRDPA_2.5km_Precip-Accum{6h,24h}` | | gz GRIB2; WMS | PrecipRate and PrecipFlag decoded (0.2 s, but 650 MB peak memory at full grid) |
| Cloud imagery | NASA GIBS `GOES-West_ABI_GeoColor` (1 km, every 10 min, zoom 7) and `GOES-West_ABI_Band13_Clean_Infrared` | | WMTS, EPSG:3857 | Tile fetched |

Notes that shape the plan:

- **GRIB decoding**: `gribberish` (Rust, 0.8 MB wheel, needs only numpy ≥ 2) decoded HRRR,
  NBM, RRFS and MRMS messages. No eccodes, GDAL or pyproj needed: it returns the lat/lon of
  every grid point. `eccodeslib` (9 MB wheel) is the fallback if a product fails.
- **ECMWF open data** (`data.ecmwf.int/forecasts/…/ifs/0p25/`) exists but the path and decode
  test failed; treat as optional and unverified.
- **NAM is being retired** (NWS SCN 26-47): do not build on it.
- **Radar is blind in much of the mountain West** (beam blockage). The satellite cloud
  loop and the model forecast are the honest complement; the legend should say so.

### Terrain and imagery

| Need | Source | Detail | Access | Verified |
|---|---|---|---|---|
| Finer elevation | Mapterhorn `tiles.mapterhorn.com/{z}/{x}/{y}.webp` | Terrarium encoding, 512 px tiles. US: 3DEP 1 m lidar where flown (zoom 16 present at Snoqualmie, Alta, Mammoth), 10 m elsewhere. Canada: NRCan HRDEM 2 m where flown (zoom 15 at Whistler and Sunshine), Copernicus 30 m elsewhere. CORS `*`, Cloudflare-hosted, PMTiles extracts for self-hosting | direct from the browser | Coverage per location checked |
| Slope, aspect, elevation bands, shade | Computed from the DEM tiles in the browser | MapLibre 6.17 has `hillshade` (sun direction and altitude settable, 5 methods), `color-relief` (tint by elevation), `addProtocol` (custom tiles), custom layers. It has no slope expression and no `raster-color` | no new data | Style spec and typings read |
| Contours on any base | `maplibre-contour` (BSD-3) | Vector contours from DEM tiles, in ft or m | npm | Package exists; v6 compatibility to confirm |
| Recent satellite, 10 m | Sentinel-2 L2A via Microsoft Planetary Computer: STAC search, per-scene tiles `…/api/data/v1/item/tiles/WebMercatorQuad/{z}/{x}/{y}@2x?collection=sentinel-2-l2a&item=…&assets=visual`, and a cloud-mask crop `…/item/bbox/{w,s,e,n}/64x64.npy?assets=SCL` | Scenes 2–5 days apart; newest clear scene per location picked by local cloud fraction | keyless | Scene found (Nov 4), tile rendered (1 s), SCL crop read |
| Recent satellite, 30 m | NASA GIBS `HLS_S30_Nadir_BRDF_Adjusted_Reflectance`, `HLS_L30_…` | zoom 12, daily, about 6 days behind | WMTS | Tile fetched |
| Daily satellite, 250–375 m | GIBS `VIIRS_NOAA20_CorrectedReflectance_TrueColor`, false colour `…_BandsM11-I2-I1` (snow vs cloud), `VIIRS_NOAA20_NDSI_Snow_Cover` | zoom 8–9, same day | WMTS | Tile fetched |
| Avalanche danger zones | avalanche.org map layer (93 zones) and Avalanche Canada areas + products | already fetched by `backend/snowwatch/avalanche.py` per location | in use | In use |
| ATES terrain ratings | No open bulk feed found. Avalanche Canada offers a per-area KMZ download behind a disclaimer | | owner upload | Web search only |
| Avalanche observations | avalanche.org obs API answers 401 (needs a key). Avalanche Canada MIN endpoint not reachable from the sandbox | | | Not verified |
| Wind-drift terrain index | Winstral Sx (maximum upwind slope), published method, reference implementation in USDA SMRF | computed from the DEM | no new data | Literature |
| Vector base map | OpenFreeMap (`tiles.openfreemap.org`, free, no key) | OpenMapTiles schema | optional | Style fetched |

## Design decisions

1. **Keep "the server draws, the browser swaps pictures"** for anything animated. It is why
   scrubbing is instant and phones stay under ~220 MB. Do not move to per-frame tile pyramids.
2. **A fixed western North America box** instead of one that follows locations:
   31–57°N, 134–102°W (config), widened only if a location lies outside. At 1700 px wide
   this is ~1.5 km a pixel, about today's resolution, 3.3 MP per frame.
3. **GeoMet first where it has the data** (radar, Canadian models): it styles pictures in our
   colours and returns float grids, so no decoding. **NOAA GRIB by byte range** for the US.
4. **Terrain analysis runs in the browser from DEM tiles** (a Web Worker). No server storage,
   works anywhere on the map, and works offline because DEM tiles are already saved offline.
5. **One weather layer and one terrain overlay at a time**, chosen in a new Layers sheet.
   This bounds memory and replaces the growing column of tool buttons.
6. **Everything derived is labelled as an estimate**, with its inputs shown. Published
   avalanche ratings stay exactly as published and keep the official colours; the app's own
   index uses a different palette and name so the two can't be confused.
7. **New dependencies**: backend `gribberish`; frontend `maplibre-contour`. Nothing else.
8. **Mesh sources in data space, not picture space.** The aim is the best available source
   for every pixel with no visible joins. Each source is resampled to the region grid as
   numbers (rate or amount, plus a type code), each gets a per-pixel weight (1 well inside
   its domain and preferred lead time, falling to 0 over ~100 km at its edge), amounts are
   the weighted mean, and the type comes from the highest-weight source. Colours are applied
   once, after blending. Milestones 1–2 may ship with the simpler hard joins described in
   A2 (HRDPS domain mask, 49°N); replacing them with this blend is the last task of
   milestone 2 and uses GeoMet WCS floats instead of styled WMS pictures for the Canadian side.

## Workstream A: radar and forecast

### A0. Foundations (refactor, no behaviour change)

- New package `backend/snowwatch/maps/`; move code out of `precip.py` without changing output:
  - `region.py`: `Region`, `merc_x/merc_y/merc_lat`, `region_for` (now returns the fixed box
    from `config/forecast.yaml` → `map.region`, unioned with locations).
  - `geomet.py`: `Net`, `sld`, `geomet_map`, `capabilities_dims`, `parse_times`, `wcs_grid`, `on_region`.
  - `palette.py`: ramps, `PALETTE`, `snap`, `encode`, `repaint`, `over`.
  - `render.py`: `Renderer`, index writing, pruning. `precip.py` stays as a thin re-export so
    `scheduler.py`, `cli.py` and `tests/test_precip.py` keep working.
- `maps/grib.py`: `parse_idx(text)`, `fetch_message(net, url, pattern)` (range GET),
  `decode(raw) -> (float32 array, metadata)`, and `index_map(metadata, region) -> (rows, cols)`:
  nearest source cell for each region pixel, built once per model grid from
  `metadata.latlng()` and cached as `.npy` in `data/maps/grids/`. Decode one message at a
  time, cast to float32 and resample to the region immediately.
- Index v2 (`data/precip/index.json`, served by `/api/precip`), backward compatible:
  each frame gains `kind: "radar" | "nowcast" | "forecast"`, `span_h` (1, 3 or 6) and
  `src: {north, south}`; `totals[]` gains `source` and `tiles`; new top-level `layers` (A5)
  and `attribution`. Update `frontend/src/lib/radar.ts` types and `toTimeline`.
- `docker-compose.yml`: worker `mem_limit` 1g → 1536m. Add `gribberish` to `backend/pyproject.toml`.
- Split the scheduler's single `precip` job: `radar` every 6 min, `forecast_frames` every
  30 min, `totals_fields` hourly. Each keeps the existing "skip if already running" lock.

### A1. Radar: wider, finer, typed, with a nowcast

- `maps/sources/radar_eccc.py`. For each time in the layer's time dimension (use every
  12 min over the last 3 h, every 6 min for the last 30 min):
  1. GetMap `RADAR_1KM_RRAI` with the `RAIN` ramp SLD, `RADAR_1KM_RSNO` with the `SNOW` ramp
     SLD (its unit is already cm/h), and `Radar_1km_SfcPrecipType` in its default style.
  2. Classify the type picture by colour into snow / mix / rain (12 legend colours; freezing
     rain and hail map to mix and rain). Compose: snow pixels take the RSNO colour, rain
     pixels the RRAI colour, mix pixels the `MIX` ramp by the RRAI rate. Where there is echo
     but no type, fall back to the forecast frame's type for that hour, else rain.
- Nowcast frames (`kind: "nowcast"`, next 72 min, every 12 min) from the two
  `…-Extrapolation` layers, typed by the latest observed type picture.
- Keep `radar_frames` (RainViewer) as the fallback when GeoMet radar returns nothing.
- Frontend: "now" sits at the last radar frame; nowcast frames are labelled
  "nowcast · in 24 min" and drawn on the slider between radar and forecast.
- Legend note: "Radar can't see into many mountain valleys."

### A2. Forecast timeline: US from our own HRRR, then out to 10 days

- `maps/sources/hrrr.py`: for each valid hour 1–48, pick the newest run that reaches it
  (same rule as `hrrr_slots`). Fetch `APCP` (1-hour) and `CSNOW`, `CRAIN`, `CFRZR`, `CICEP`.
  Typed rate → `SNOW` / `MIX` / `RAIN` ramps. This replaces `hrrr_recolor`, the IEM tiles
  and the tan WPC polygons (delete `UNTYPED` once nothing draws it).
- Hours 1–48 stay as today geographically: HRDPS where its domain covers, HRRR elsewhere.
- Hours 49–84 (`span_h: 3`): north from `RDPS_10km_{Rain,Snow,FreezingRain}-Accum3h`
  (WMS + SLD, thresholds × 3 so colours still mean an hourly rate); south from NBM
  (`APCP` and `ASNOW` 3-hour or 6-hour sums; snow where ASNOW > 0, else rain).
- Hours 85–240 (`span_h: 6`): north from `GDPS_15km_…-Accum6h`; south from NBM 6-hour fields.
- North/south seam for these extended frames: 49°N.
- Frontend: frames beyond 48 h load on demand (when the slider enters them, or when the
  page has been idle 5 s), so the first paint still costs ~2 MB. Label them
  "Fri 4–10 AM · 6-hour average". Day ticks already exist; the slider gets a visibly
  coarser section for the extended range.
- Stretch: RRFS North America 3 km as an alternative source for hours 1–84 on both sides of
  the border (`maps/sources/rrfs.py`); it removes the seam.

### A3. Snow totals: more windows, both countries, to 10 days

- Windows: 12 h, 24 h, 48 h, 72 h, 5 days, 7 days, 10 days.
- US side: sum NBM `ASNOW` (already a depth with NBM's own snow ratio) across the window
  from the newest run that reaches 264 h. About 40 messages a cycle (~60 MB); refresh
  twice a day by default (`map.nbm_cycles`).
- Canada side: accumulated water equivalent differenced within each run and chained by
  lead time: `HRDPS.CONTINENTAL_SN` (0–48 h) + `RDPS_10km_Snow-Accum` (48–84 h) +
  `GDPS_15km_Snow-Accum` (84–240 h), via the existing `wcs_grid`/`on_region`. Depth at
  10:1 first; then a temperature-based ratio reusing `analysis/slr.py` bands with
  `HRDPS.CONTINENTAL_TT` / `GDPS_15km_AirTemp_2m`.
- Seam: blend linearly between 48.5 and 49.5°N so totals don't jump at the border.
- Keep float grids (`float16 .npy`, cm) in `data/maps/totals/` for A4 and A6.
- Frontend: window picker becomes a scrolling segmented control; the note names the
  sources actually used and when each run started.

### A4. Terrain-adjusted snow totals (the "more detail" step)

Model grids are 2.5–15 km; mountains aren't. Store totals per elevation, then let terrain pick.

- While accumulating a window, build `S[k]` on a half-resolution region grid for elevation
  bins `z_k` every 250 m from 0 to 4500 m:
  `S[k] += precip_water × ratio × frac(z_k − snow_level)`, where `frac` rises from 0 to 1
  across ±150 m around the snow level. Inputs: NBM `APCP`, `SNOWLVL`, `SNOWLR` (US);
  `…_PR` total precipitation and `…-WEonG_…_SnowLevelHeight` (Canada).
- `maps/tiles_render.py` + `GET /api/snowtiles/{window}/{z}/{x}/{y}.png` (zoom ≤ 11): for
  each tile pixel take the DEM elevation (Mapterhorn tile through `TileCache`), interpolate
  `S` between bins and bilinearly in space, paint on the `TOTAL` ramp, cache under the
  product's hash. The api only reads local files plus cached DEM tiles.
- Frontend: in Snow total mode at zoom ≥ 8 switch from the single picture to this tile
  source (`raster-fade-duration` 0). Caption: "Adjusted to terrain: model precipitation,
  snow above the model's snow level."

### A5. More weather layers (same frame machinery)

Each is a named entry under `layers` in the index, drawn by the same `PrecipLayer`.

| Layer | Data | Form |
|---|---|---|
| Snow level | HRDPS-WEonG / RDPS-WEonG `SnowLevelHeight` north, NBM `SNOWLVL` south | timeline, 3-hourly to 84 h, bands every 250 m |
| Wind and gusts | HRDPS `WSPD`, `WGE` north; HRRR `GUST`, 10 m wind south; "ridge level" from `RDPS_10km_WindSpeed_700mb` | timeline, 3-hourly to 48 h; speed colours first, particles as a stretch |
| Snow on the ground | SNODAS (US) + CaLDAS (Canada) | one picture, daily |
| Snowfall observed | NOHRSC 24/48/72 h (US only) | pictures, refreshed every 6 h |
| Clouds | GIBS GOES-West GeoColor, stitched to frames at zoom 6 like `stitch` does | last 3 h every 30 min, shown under the radar frames |

A cheap extra that needs no new data: a **rain/snow line draped on the 3D terrain** near a
saved location, using a MapLibre `color-relief` layer whose break is that location's
forecast snow level for the selected hour (already in its snapshot).

### A6. Tap anywhere for numbers

- `GET /api/map/point?lat=&lon=` → snow totals per window (and per elevation from A4),
  snow level now, the typed hourly rate series decoded from the frame pictures' palette
  indices, and which model supplied each. Rate limited like the tile endpoints.
- Frontend: part of the Inspector (B8).

### A7. Stretch

- Model picker for snow totals (blend, HRRR, RRFS, HRDPS, GDPS) to see disagreement.
- Probabilities: NBM probability fields and the RRFS ensemble (REFS) for "chance of 6 in+".
- ECMWF IFS open data as a second 10-day source, once its path and decoding are confirmed.
- MRMS `MultiSensor_QPE` "what fell" maps (crop on decode; the full grid peaks at 650 MB).

## Workstream B: terrain

### B1. Finer elevation

- `MapView` DEM source → Mapterhorn (`tileSize: 512`, `encoding: 'terrarium'`, `maxzoom: 16`),
  with the AWS source kept as an automatic fallback after repeated tile errors.
- CSP in `backend/snowwatch/api/app.py`: add `https://tiles.mapterhorn.com` to `connect-src`.
- `offlineMaps.ts` and `service-worker.ts`: save and answer Mapterhorn tiles (512 px tiles
  mean one zoom lower for the same detail; re-measure `AVG_BYTES`, keep ~35–50 MB a location).
- Hardening (optional): `pmtiles extract` per location into `data/dem/` and serve by range,
  so the map doesn't depend on a donation-funded host.

### B2. Terrain engine in the browser

New `frontend/src/lib/map/terrain/`:

- `dem.ts`: fetch and decode Terrarium tiles to `Float32Array` (LRU of ~40 tiles), with a
  1-pixel border from neighbours so tile edges don't show; `mosaic(bounds, zoom, maxPx)`
  for viewport-wide work (1024² desktop, 768² phone).
- `analysis.worker.ts`: slope and aspect by Horn's 3×3 method with ground metres per pixel
  from latitude and zoom. Analysis zoom is capped at 12 (about 10–13 m a pixel here):
  1 m lidar slope is noise at the scale avalanches care about.
- `protocol.ts`: `addProtocol('terrain', …)` serving `terrain://{mode}/{z}/{x}/{y}?…` as
  `ImageBitmap` raster tiles (source `tileSize: 512`, `maxzoom: 12`, overscaled beyond).
- Modes:
  - `slope`: clear below 25°, then 25–29, 30–34, 35–39, 40–45, 46–50, 51°+ in a
    yellow → orange → red → purple → blue → black ramp.
  - `aspect`: eight compass colours.
  - `match`: highlight pixels meeting `slopeMin`, an aspect set and an elevation range
    (used by B7).
  - Elevation bands use the native `color-relief` layer, no custom tiles.
- These are ordinary raster layers, so they drape on 3D terrain and work offline.

### B3. Hillshade and contours

- Native `hillshade` layer (method `igor` or `multidirectional`) under the labels on every
  base, strength in settings. Makes satellite and Esri topo read as terrain.
- `maplibre-contour` lines and elevation labels (ft or m with the units setting), shown on
  satellite and recent-imagery bases, where there are none today.

### B4. Sun and shade

- `sun.ts`: solar azimuth and altitude from date, time, lat, lon (NOAA formulas, ~40 lines, tested against known values).
- **Lit by the real sun**: drive `hillshade-illumination-direction` and `-altitude` from a
  time slider. Instant, no cast shadows.
- **Cast shadows**: in the worker, on a viewport mosaic extended toward the sun
  (up to 15 km), march each pixel toward the sun and mark it shaded if terrain rises above
  the ray. Draw the mask as a canvas source (the `PrecipLayer` pattern). Slider from sunrise
  to sunset in 15-minute steps, any date; recompute on `moveend` (250 ms debounce), cancel stale work.
- **Sun hours**: sum masks every 30 min into "hours of direct sun today", with first and
  last sun reported by the Inspector.

### B5. Wind loading ("where the snow likely went")

- In the worker: Winstral Sx for eight wind directions on the viewport mosaic at ~25 m
  (search 300 m; second pass at 1500 m for ridge-scale lee).
- Wind input: the nearest saved location's loading rose, which already gives snow × ridge
  wind per sector (`analysis/backcountry.py::loading_rose`, `Rose.sectors`, `snow_cm`,
  `mean_kmh`). Expose roses for "last 48 h", "next 24 h" and "next 72 h" in the snapshot.
  Beyond 40 km from any location, use the wind layer value from `/api/map/point` (after A5).
- Index: `L = transport × Σ_d w_d · g(Sx_d)`, positive where upwind terrain shelters the
  pixel (lee, deposition), negative where exposed (scour); `transport` scales with wind
  above `rose_min_wind_kmh` and new snow above `rose_min_snow_cm`.
- Drawn as a diverging overlay (scoured ↔ loaded) with the caption
  "Likely wind effect from model wind and terrain shape. Local gusts and trees aren't modelled."

### B6. Recent satellite imagery

- Backend `maps/sat.py`, worker job every 6 h: for each location search Planetary Computer
  for Sentinel-2 scenes in the last 30 days, then for candidates newest first read the
  64×64 `SCL` crop around the location and keep the newest with ≥ 70% clear pixels and
  < 10% no-data (scene-wide cloud % is not enough: a "0% cloud" scene had no data at the
  test location). Write `data/sat/index.json` (scene id, time, clear %, snow %), keep the
  last three clear scenes. Serve at `/api/sat`.
- `tiles.py`: two new proxied, cached, whitelisted upstreams:
  `/api/tiles/s2/{item}/{z}/{x}/{y}.jpg` (only item ids present in the index) and
  `/api/tiles/gibs/{layer}/{date}/{z}/{x}/{y}` (layer whitelist, date pattern).
- Frontend base option "Recent satellite": GIBS VIIRS daily below zoom 9, HLS 30 m at
  zoom 9–12, Sentinel-2 10 m from zoom 11 near locations. A chip shows
  "Sentinel-2 · 4 Nov · 6 days ago · 92% clear", with previous/next scene and a
  natural / snow-vs-cloud (B11-B8A-B04) toggle. Esri imagery stays as "Satellite (detailed, undated)".
- Attribution: "Contains modified Copernicus Sentinel data", NASA GIBS, Microsoft Planetary Computer.

### B7. Avalanche layers

1. **Danger zones for the whole West, as published.** Worker writes
   `data/avalanche/zones.geojson` from the avalanche.org map layer and Avalanche Canada
   areas/products (reuse the normalisers in `avalanche.py`; fetch a US product per rated
   zone in the box so problems are known everywhere). `GET /api/avalanche/zones.geojson`.
   Polygons in the official danger colours, expired ones grey, tap for the three-band
   pyramid (`DangerPyramid.svelte`), problems and a link to the center.
2. **Terrain matching today's listed problems.** For the zone under the map centre, each
   published problem (aspects, elevation bands) becomes a `match` layer (B2): those aspects,
   those bands, slope ≥ 30° (25/30/35 selectable). Band boundaries are not published as
   numbers, so ship `config/treeline.yaml` (approximate treeline range per center/zone),
   let the owner override per location, show the numbers used, and label them approximate.
3. **Terrain concern index (experimental, the app's own estimate).**
   - `base` = the published danger (1–5) for the pixel's elevation band. No current bulletin → no layer.
   - `slope`: 0 below 25°, 0.5 at 25–29°, 1 at 30–45°, 0.7 at 46–55°, 0.3 above.
   - `match`: 1 if the pixel's aspect and band are in a listed problem, 0.6 otherwise (0.8 if no problems are listed).
   - `wind`: +0.5 where B5 says loaded and a wind- or storm-slab problem is listed or new snow exceeds the threshold; −0.25 where scoured.
   - `sun`: +0.5 in the afternoon on E–S–W aspects with several sun hours when a wet problem is listed or the rapid-warming / rain-on-snow flag is up.
   - `score = (base + wind + sun) × slope × match`, shown in four relative classes
     (lower, elevated, high, very high) in a palette that is not the danger scale's.
   - Thresholds live in `config/forecast.yaml` → `terrain:`. The Inspector shows each factor for a tapped point.
   - Guard rails: setting `HAZARD_INDEX=off|owner|public`, default `owner` (visible only
     with the owner session) until the display terms of avalanche.org and Avalanche Canada
     have been re-read for a derived product; a one-time acknowledgement; a fixed caption:
     "Experimental estimate from the bulletin and terrain shape. Not a forecast. Doesn't
     show runouts or slopes above you."
   - `docs/ARCHITECTURE.md` currently says "no safety judgement anywhere": update it to describe this one, bounded exception.
4. **ATES ratings**: owner uploads a KMZ/GeoJSON (downloaded from Avalanche Canada's trip
   planner, which shows its own disclaimer) into `data/overlays/`; drawn as
   simple / challenging / complex / extreme polygons. Stretch: run the open-source
   AutoATES v2 offline per location (needs forest cover, heavy dependencies; research item).
5. **Observations**: Avalanche Canada MIN reports as points if the endpoint is reachable
   from the server (not verified here). US observations need a key: link out instead.

### B8. Inspector and measuring

- Long-press or tap empty map → sheet with elevation, slope, aspect, band; forecast snow
  for the windows (A6); snow level; first/last sun today; wind effect; avalanche zone and
  rating; concern-index factors when that layer is on.
- Measure: tap out a line → distance, climb/descent, average and steepest slope, an
  elevation profile (the charts' d3 scales and `Frame.svelte` conventions), segments
  coloured by slope class. GPX import (parsed in the browser, never uploaded).

### B9. More map features

- `osm.py` query additions: huts, trailheads, cliffs, glaciers, passes, and ski-route
  relations (`route=ski|piste`) so multi-way tours get their names.
- Snow stations layer: all SNOTEL and BC ASWS stations in the box (the BC CSVs already
  hold the whole network) with 24-hour new snow and depth, tap for a 7-day sparkline.
- Tapped run or tour line: length, vertical, steepest pitch from the DEM.

### B10. Optional and stretch

- Vector base map (OpenFreeMap) with our own outdoor style: crisp at every zoom, real dark
  theme, far smaller offline. A style-design project, not required by anything above.
- "Likely surface conditions" near saved locations (powder, wind-affected, sun-affected,
  rain-affected) by combining new snow, B5, B4 and the snow level. Experimental label.

## Frontend structure

`MapView.svelte` is 1,650 lines; split before adding layers:

- `lib/map/style.ts` (sources, base layers, `skiLayers`), `lib/map/layers/{precip,terrain,sat,avalanche,stations}.ts`
- `lib/map/LayersSheet.svelte`: Base (Topo, Satellite, Recent satellite) · Weather (one of:
  Radar & forecast, Snow total, Snow level, Wind, Snow on ground, Clouds) · Terrain (one of:
  Slope, Aspect, Elevation bands, Sun & shade, Wind effect, Avalanche problems, Concern
  index) · Features (runs, peaks, stations, danger zones, contours).
- `lib/map/Timeline.svelte`, `Legend.svelte`, `Inspector.svelte`, `Measure.svelte`.
- `prefs.svelte.ts`: `mapWeather`, `mapOverlay`, `mapFeatures`, replacing `mapPrecip`/`mapMode`
  (migrate stored values). Every control keeps working at 380 px with a thumb.

## Performance rules

- Animated layers are single pictures swapped on one canvas; at most 4 decoded at once (as now).
- First load fetches radar, nowcast and 48 h only (~2–3 MB); the rest on demand.
- Terrain tiles: < 5 ms each in the worker; mosaic jobs one at a time, cancellable, 768² on phones.
- Budget: ≤ 300 MB in headless Chrome on the iPhone profile during playback, 3D pan and one
  terrain overlay (today ~220 MB). Add this as an e2e measurement.
- Server: worker ≤ 1.5 GB; api tile rendering reads memory-mapped grids. Map data on disk
  stays under ~3 GB plus the existing tile cache cap (`TILES_MAX_MB`).

## Order of work (each milestone is one shippable PR)

| # | Milestone | Contains |
|---|---|---|
| 1 | Foundations and wide radar | A0, A1, fixed West box (done, see "Milestone 1 notes") |
| 2 | Longer, better forecast | A2, A3 and the data-space blend (done, see "Milestone 2 notes") |
| 3 | Terrain basics | Frontend split + Layers sheet, B1, B2, B3, B8 inspector (terrain facts) (done, see "Milestone 3 notes") |
| 4 | Sun and wind | B4, B5 (done, see "Milestone 4 notes") |
| 5 | Avalanche | B7.1, B7.2, then B7.3 behind `HAZARD_INDEX` (done, see "Milestone 5 notes"; B7.3 is open to every visitor) |
| 6 | Recent satellite | B6 (done, see "Milestone 6 notes") |
| 7 | More weather layers | A5, A6 (done, see "Milestone 7 notes") |
| 8 | Terrain-adjusted totals | A4 |
| 9 | Tools and features | B8 measure/GPX, B9, B7.4, B7.5 |
| 10 | Stretch | A7, B10, RRFS source |

## Handoff

- This file is committed as `docs/MAP-PLAN.md` in a docs-only PR. Merge that PR first: a
  new cloud session clones the default branch, so the plan must be on it.
- One new session per milestone, with a prompt such as: "Implement milestone 1 of
  `docs/MAP-PLAN.md`. Read `docs/ARCHITECTURE.md` and `docs/SOURCES.md` first. Re-probe
  each source the milestone uses before coding against it, and update `docs/SOURCES.md`
  with what you find." Each session ends with a PR; tick the milestone off in this file.
- How hard each milestone is (a judgement, not a measurement). "Hard" ones deserve the
  strongest model available and a careful review:

| Milestone | Difficulty | Why |
|---|---|---|
| 1 Foundations and wide radar | Routine | Well-specified refactor plus one new source on an existing code path |
| 2 Longer forecast, totals | Routine, except the data-space blend (decision 8): hard | The blend is where grids, units, accumulation periods and run times all have to agree; mistakes look plausible |
| 3 Terrain basics | Routine | Large but mechanical frontend split; slope and aspect are textbook |
| 4 Sun and wind | Hard | New numerical algorithms that must also stay fast on a phone |
| 5 Avalanche | Routine for zones and problem matching; hard for the concern index | Safety-sensitive, and it depends on milestone 4's outputs |
| 6 Recent satellite | Routine | API plumbing with a clear selection rule |
| 7 More weather layers | Routine | Repeats the milestone 1–2 patterns |
| 8 Terrain-adjusted totals | Hard | Novel numerics; easy to get subtly wrong |
| 9 Tools and features | Routine | Independent, well-bounded pieces |
| 10 Stretch | Decide per item | |

- Whoever implements: if a source behaves differently from this document, stop and record
  it rather than working around it silently.

## Milestone 1 notes (done 10 Nov 2026)

What shipped, and where it differs from the plan above:

- `backend/snowwatch/maps/` with `region`, `geomet`, `palette`, `grib`, `render` and
  `sources/{radar_eccc,rainviewer,iem,wpc}` (`iem` and `wpc` hold today's IEM HRRR tiles and
  WPC polygons until milestone 2 removes them). `precip.py` only re-exports.
- `index_map` returns the flat index of the nearest source cell per pixel (−1 outside the
  grid) rather than `(rows, cols)`: `gribberish` returns values and coordinates flat. It is
  built without SciPy: each source cell lands in the pixel under it, then gaps are filled
  from neighbours out to about one cell's width.
- `span_h` is 0 for radar and nowcast frames (a rate at an instant), 1 for hourly forecast frames.
- The scheduler jobs are `radar`, `forecast_frames` and `totals_fields`; each rewrites only
  its own part of the index under a file lock. `snowwatch map radar|forecast|totals|all`.
- Radar typing: the type product left 26% of echo pixels untyped on 10 Nov 2026, nearly
  all under 0.5 mm/h. So an untyped echo first takes the nearest radar type within 8 px
  (~12 km), then the first forecast frame's type, then rain. The type picture is classified
  by colour as planned; raw class values seen were 110/120 (snow) and 210/220 (mixed).
- 12-minute radar frames sit on the clock (UTC minutes divisible by 12) so they keep their
  names between runs; the newest 30 minutes are every scan.
- The whole first-load timeline is ~3.8 MB (radar, nowcast and 44 h of forecast), above the
  2–3 MB aim; loading beyond 48 h on demand (milestone 2) keeps it from growing.

## Milestone 2 notes (done 10–11 Nov 2026)

What shipped, and where it differs from the plan above:

- `maps/sources/hrrr.py` (our own HRRR from GRIB), `maps/sources/nbm.py`, `maps/sources/rdps_gdps.py`,
  `maps/totals.py`. `iem.py`, `wpc.py` and the `UNTYPED` ramp are gone.
- **Timeline**: hourly frames as before (HRDPS in its domain, HRRR outside, NBM's hourly fields
  for any hour no HRRR run reaches); then 3-hourly frames to the RDPS run's end (~84 h) and
  6-hourly to the GDPS run's end (240 h), each model's stretch ending on a 00/06/12/18 UTC
  hour. The Canadian model in Canada, NBM in the US (first shipped with a hard join at 49°N,
  then blended; see below).
- **NBM differs from the table above**: only 00/06/12/18 UTC runs reach 264 h; between 48 and
  192 h the 3-hourly files hold only a 1-hour APCP, and ASNOW exists only as 6-hour sums
  (1-hour to 48 h). So there are no NBM 3-hour sums: a 3-hour frame takes its share of its
  6-hour block from how RDPS splits the same six hours. NBM's rows alternate direction (scanning mode 0x50), which
  `gribberish` doesn't undo; `grib.decode` now does (it showed as striped fields).
- **RDPS differs**: `…-Accum3h` layers are 3-hourly, not hourly; freezing rain and ice pellets
  are `…FreezingRain-Accum-3h` / `-6h` (extra hyphen).
- **NBM probability messages** share the plain message's `.idx` name; `grib.find` now skips
  lines with fields after the forecast time.
- **Totals**: windows 12/24/48 h and 3/5/7/10 days. Longer-than-48 h windows end on the
  synoptic hour before and are dropped if the models stop short of 90% of the window; the
  10-day one ends where the shorter of GDPS and NBM ends (~230 h). Canada is chained
  HRDPS → RDPS → GDPS in 6-hour steps, each step with the temperature-based ratio from
  `slr_bands` (already, not "10:1 first"). WCS requests are pinned to their run
  (`DIM_REFERENCE_TIME`, verified). Joined with NBM across 48.5–49.5°N as planned.
  Grids saved as `data/maps/totals/<window>h.npy` (float16 cm).
- Index: frames' `south` is now `"hrrr"`, `"nbm"` or `""`; `src` names `hrdps`, `rdps`,
  `gdps`, `hrrr`, `nbm`. Totals gain `window` and `runs`; `hours` stays the actual length.
- Frontend: frames beyond 48 h load when the slider reaches them or after 5 idle seconds; the
  slider shows that stretch as a dashed band; labels read "Fri 4–10 AM · 6-hour average · in
  3 days"; day names that would crowd are skipped; the totals picker scrolls sideways.
- Config: `map.nbm_cycles` (default `[0, 12]`). Renderer working files: `data/maps/`.
- Measured with the blend: forecast cold build ~180 s (~85 s from the caches), ~570 MB;
  totals ~45 s (~17 s from the caches), ~400 MB; first-load forecast frames 2.5 MB, the
  extended frames 1.8 MB more on demand.

### The data-space blend (decision 8), as built

`maps/blend.py`; details and probe results in `docs/SOURCES.md`.

- Every source is numbers on the region grid (hourly rate in mm of water, plus a type
  code) before anything is coloured. The Canadian side moved from styled WMS pictures to
  WCS floats (`sources/rdps_gdps.py` `fields`): rain, snow, freezing rain and ice pellets
  per period, interpolated between cells.
- Weights: `feather` gives 1 well inside a source's domain, easing to 0 over ~100 km at its
  edge. `mosaic` lays sources down in order of preference, each taking its weight of what
  is left, so two models are never averaged inside the preferred one (that would smear two
  slightly different storms into one weaker one); they cross-fade only near its edge.
  Amounts are the weighted mean, the type comes from the highest-weight source that has
  one, and colours go on once (`paint_typed`).
- Hourly frames: HRDPS → HRRR (NBM hourly if no HRRR run has the hour) → RDPS hourly, which
  covers everything and so fills the Pacific south-west of HRRR's grid.
- Extended frames and totals: NBM's weight is its domain weight times a US preference that
  fades out between 48.5 and 49.5°N; the Canadian model takes the rest.
- Differences from decision 8 as written, and things it didn't foresee:
  - "Preferred lead time" is handled by which model each frame or totals step uses
    (HRDPS to 48 h, RDPS to 84 h, GDPS beyond), not by a weight inside a frame: a change of
    model between one frame and the next is not a visible join.
  - HRDPS's WCS grids hold 0 outside its domain, so its domain still comes from one WMS
    picture (kept on disk as a fallback).
  - WCS floats are 2.4 MB a layer uncompressed; `geotiff:compression=Deflate` and a disk
    cache by run keep a full rebuild to a few tens of MB.
  - Interpolating amounts rings snow areas with a false "mix"; mix is kept only next to a
    model cell that is itself mixed.
  - NBM's 6-hour amounts are split between 3-hour frames by RDPS's timing (shares add to 1).
- Known limits: where two models disagree, the lightest contour (0.1 mm/h) can run parallel
  to a domain edge inside the fade; and the Canada/US preference follows 49°N, not the
  actual border (they are the same line across this box, except the south tip of Vancouver
  Island, which is in the fade).

## Milestone 3 notes (done 11 Nov 2026)

What shipped, and where it differs from the plan above:

- **Split**: `lib/map/style.ts` (sources and layers), `lib/map/layers/terrain.ts` (wiring and
  updates), `lib/map/Timeline.svelte` (the weather controls and key), `LayersSheet.svelte`,
  `Legend.svelte` (terrain key), `Inspector.svelte`. `MapView.svelte` is ~1,200 lines (was
  1,880); the precipitation state and its effects stay in it for now rather than in
  `layers/precip.ts`. The tool column is Location, 3D, Layers, Offline, About.
- **Prefs**: `mapWeather` (`radar | totals | off`), `mapOverlay` (`none | slope | aspect | bands`),
  `mapFeatures` (`runs`, `peaks`, `contours`) and `mapShade` (`off | light | strong`, the
  "strength in settings" lives in the Layers sheet). Old `mapPrecip`/`mapMode`/`mapPistes`
  values are read once as defaults.
- **B1 differs**: Mapterhorn answers 404 over open sea at every zoom and beyond each area's
  finest zoom (z15 in Canadian lidar, z12 in remote BC), so `maxzoom: 16` on a plain URL
  would leave holes. Elevation goes through a `dem://` protocol served by the terrain
  worker, which fills a missing tile from its parent (z > 12) or as sea level (z ≤ 12),
  and switches to the AWS tiles after four failures in a row. Two raster-dem sources
  (3D to z16, shading/bands to z15) as MapLibre advises. Offline areas: Mapterhorn
  z7–13 plus z14 within 4 km (~7 MB of terrain instead of ~20 MB); 404s are skipped;
  removing an area also clears AWS tiles saved before the switch. PMTiles hardening not done.
- **B2**: `terrain/dem.ts` (fetch, decode, gap-fill, LRU of decoded tiles: 48 desktop,
  28 phone), `terrain/analysis.ts` (Horn slope/aspect, painting), `analysis.worker.ts`,
  `client.ts` (`dem://` and `terrain://` protocols). Overlays from zoom 8. `match` mode
  is built and tested, waiting for B7.2. Elevation bands: `color-relief` with hard steps
  every 500 m / 1,500 ft (it only accepts `interpolate`, so each step is two stops 0.5 m apart).
- **B3**: hill shading (`igor`) on every base, lighter on Esri topo. Contours are drawn on
  the satellite base only; `maplibre-contour` works with MapLibre 6.17 (checked in headless
  Chromium), loaded on demand, to z12.
- **B8 (terrain facts only)**: tap the map (not a marker) for elevation (finest tile to
  z15), slope and aspect (on the z12 grid) and the grid sizes behind them. The avalanche
  elevation band is left for milestone 5, which brings the treeline numbers.
- Not done: the ≤ 300 MB phone memory measurement (headless Chromium here renders with
  SwiftShader, where a 3D screenshot alone takes ~30 s).

## Milestone 4 notes (done 11 Nov 2026)

What shipped, and where it differs from the plan above:

- **Two new terrain overlays**, "Sun & shade" and "Wind effect" (`mapOverlay` `sun`, `wind`),
  with their own controls above the weather timeline (`lib/map/TerrainControls.svelte`; both
  now sit in one dock at the foot of the map). Their keys are in those controls, not in
  `Legend.svelte`. Sun from zoom 9, wind from zoom 10.
- **B4 sun**: `terrain/sun.ts` (NOAA formulas; within 0.1° of PyEphem at six test moments,
  sunrise and sunset within 2 minutes). Dates are the place's own, by longitude; clock times
  are shown in the device's time zone, with the zone named.
- **B4 lit by the real sun**: while Shade shows, the hillshade layer switches to MapLibre's
  `basic` method with the sun's direction and height (anchored to the map), whatever the
  hill-shading setting. `igor`, the everyday method, ignores the light's height.
- **B4 cast shadows differ in method**: not a march per pixel. One sweep across the grid from
  the sun's side carries the height of the shadow's upper surface from pixel to pixel
  (`terrain/shade.ts` `cast`), about 10 ms for a phone-sized grid, so a day of them is cheap.
  It agrees with ray marching on 97%+ of pixels in the tests. It runs twice: on a coarse grid
  (half the pixels a side, 15 km beyond the view on every side, not only toward the sun,
  so one pair of grids serves every time of day) and then on the view's own grid (zoom 12 at
  most), which takes the coarse result at its edges. The noon sun here is only ~18° up in
  December, so distant terrain matters all winter.
- **B4 sun hours**: a sweep every ~30 minutes from sunrise to sunset, drawn in six classes.
  About 0.3–0.7 s on a desktop core; cancellable between sweeps.
- **Inspector**: first and last direct sun and the hours between come from the spot's own
  horizon (a ray every 2° out to 15 km, fine terrain near and coarse far), checked each
  minute of the day, so they are to the minute and don't need the layer to be on. They are
  for the date in the sun controls (today unless changed).
- **B5 wind**: `terrain/wind.ts`. Sx as in Winstral et al. (2002): for each wind sector, the
  mean over three rays (−15°, 0°, +15°) of the steepest angle up to the terrain upwind; a
  near search (0–300 m) on the ~25 m grid and a far one (300–1,500 m) on a half-resolution
  copy, combined 60/40 and scaled so ±20° is fully sheltered or exposed. Rays step in whole
  pixels, so there is no interpolation in the inner loop. Sectors under 5% of the loading are
  skipped. The result is multiplied by a transport factor: 0 below `rose_min_snow_cm` or
  `rose_min_wind_kmh` (the layer then says why it is empty), rising to 1 at 30 km/h and 20 cm
  above them. 0.3–1.8 s on a desktop core depending on how many sectors matter.
- **Wind input**: the snapshot's roses gain `past48`, `next24` and `next72` (the Backcountry
  tab still shows `past72` and `next48`), and `GET /api/map/wind` returns every location's
  roses at its summit coordinates with the two thresholds. The map uses the location nearest
  its centre within 40 km and names it. Beyond 40 km the layer is empty and says so: the
  wind-layer fallback waits for A5/A6 (milestone 7). A location whose forecast predates this
  change has no such rose until its next run; the controls say that too.
- **Drawing**: one canvas source for whichever of the three is showing
  (`layers/analysis.ts`), under the precipitation. One job at a time; a newer request calls
  off the running one and follows it, so dragging the time slider never queues work. The
  worker keeps the last view's grids, so a new time or wind window repeats only the
  arithmetic. Grids are 768 px on phones, 1,024 px otherwise; in a tilted view the area is
  capped at about two screens from the centre.
- Not done: the ≤ 300 MB phone memory measurement (as in milestone 3, for the same reason).
- Known limits: shadows ignore trees, cloud and the Earth's curve (17 m at 15 km); the sun
  is one position for the whole view; wind is one location's ridge wind for the whole view,
  and the effect is terrain shape only (no snow available for transport by elevation, no gusts).

## Milestone 5 notes (done 11 Nov 2026)

What shipped, and where it differs from the plan above:

- **B7.1 zones**: `backend/snowwatch/avalanche_zones.py` writes `data/avalanche/zones.geojson`
  with every avalanche check (each forecast run, the `avalanche_utc` times, and
  `snowwatch avalanche`), sharing its downloads with the per-location refresh (`avalanche.refresh`
  takes a `memo`). The file keeps the forecasts as fetched; `GET /api/avalanche/zones.geojson`
  applies expiry against the clock on each request (cached a minute, gzipped by hand, since
  the app has no compression middleware). Each feature's `view` is an `AvalancheView`
  whose `location_id` holds the zone id (`nac:2651`, `avcan:<area>`), so the Backcountry
  tab's `DangerPyramid` shows a zone unchanged. Re-probed: 87 US zones, not 93; a product
  can cover several zones (one fetch serves them all); Avalanche Canada answered from the
  sandbox. Drawn as a Features option, "Avalanche danger zones", fill strong zoomed out and
  faint up close, under the terrain overlays. Tapping the map gives the Inspector a line with
  the zone, the spot's band and today's rating for it, and a link to the zone's bulletin
  (`ZoneSheet.svelte`); without the terrain worker a tap on a zone opens the bulletin.
- **B7.2 problems**: overlay "Avalanche problems" (`mapOverlay: 'problems'`). The `match`
  mode now takes one rule per problem (aspects plus any number of elevation ranges, so
  "alpine and below treeline" works), a problem with no aspects or bands listed means all of
  them, and tiles name the zone so the worker clips them to it (the zone's polygons are sent
  to the worker first). The match colour changed from red to teal: red read as danger
  level 4. Slope 25/30/35° in the controls, default `terrain.problem_slope_deg`.
  `config/treeline.yaml` is a list of rules tried in order (center id, zone name, a box
  tested against the spot), ending with a default, plus `locations:` overrides that apply
  within 40 km of a location. US centers have one band each (NWAC's east slopes and Mt Hood
  their own); Canada is matched by place, because early-season Avalanche Canada areas span
  whole ranges. The file is re-read when it changes. The B8 Inspector's band uses the same
  numbers.
- **B7.3 concern index**: as specified, in `terrain/concern.ts` (shared by the worker and the
  Inspector), with these readings of the plan:
  - "Today" is the zone's own date; no rating for today (even if tomorrow is rated) means
    no layer, and a band without a rating draws nothing.
  - Wind is the nearest location's (within 40 km) **last-48-hour** rose, the snow that built
    today's slabs; beyond 40 km wind isn't counted and the controls say so. "Loaded" and
    "scoured" mean a scaled wind effect beyond ±0.2 (`concern_wind_effect`). Loading adds
    only with a wind or storm slab listed or ≥ 20 cm new snow (`concern_wind_snow_cm`);
    scouring subtracts whenever wind moved snow.
  - Sun: E, SE, S, SW and W aspects with ≥ 3 h of direct sun on the zone's date (cast
    shadows included), on a day with a wet problem (names containing "wet" or "glide") or a
    rapid-warming or rain-on-snow flag for that date at the nearest location
    (`/api/map/wind` now carries those flags). Not limited to the afternoon: the sun-hours
    grid is for the whole day.
  - Classes are absolute score thresholds 1.5 / 2.5 / 3.5 (lower, elevated, high, very
    high); ground under 25° and pixels outside the zone are clear. Blues to magenta.
  - **Differs from the plan: open to everyone.** The site has no visitor accounts, so the
    owner chose not to gate it behind the owner sign-in: `HAZARD_INDEX` is `on` (default)
    or `off` (old values `public` and `owner` read as `on`), and `GET /api/map/concern`
    answers 404 when it's off, so the option isn't offered. The other guard rails stay: a
    warning each browser accepts once (remembered in `localStorage`), the fixed caption in
    the controls and the Inspector, and the Inspector lists every factor. Drawn from zoom
    10 like Wind effect.
  - The acknowledgement is a modal alert dialog: it takes the focus (the dialog, not either
    button), keeps Tab inside, and Escape cancels. `e2e/concern.spec.ts` checks, on phone
    and desktop, that a visitor who isn't signed in is offered it, that nothing is drawn
    before "I understand", that Cancel and Escape leave the layer off and remember nothing,
    that the answer is kept in that browser, and that another browser is asked again.
- Known limits: the problems and concern layers use the zone in the middle of the map for the
  whole view (clipped to it); treeline bands are regional guesses; problems are not per day
  (both providers publish one list).

## Milestone 6 notes (done 11 Nov 2026)

What shipped, and where it differs from the plan above:

- **Backend**: `maps/sat.py`, the worker's `satellite` job every `map.sat_hours` (6), and
  `snowwatch map sat`. Per location (the mid band's point) a STAC search over the last
  `sat_days` (30) for a ±4 km box, so every MGRS tile of a pass that touches the square is
  found, not only the one under the point. A **scene is a pass** (datatake), with all its
  tiles; their SCL crops are merged before judging, since a location on a tile edge saw
  23–42% no data from one tile alone. Judged passes are remembered in
  `data/sat/checked.json` (up to 24 new ones per location a run), so a refresh after the
  first only reads new passes (6 s for six locations, against 29 s). Thresholds in
  `config/forecast.yaml` → `map.sat_*`. Probe results in `docs/SOURCES.md`.
- **Index** `data/sat/index.json` at `GET /api/sat` (`SatOut`): per location its clear
  scenes, newest first (id, time, platform, clear/snow/no-data %, items with their bbox,
  and whether GIBS has HLS for that day); plus the VIIRS day and the newest HLS day.
- **Tile proxy** as planned, with two changes: Sentinel-2 URLs carry a band mode
  (`/api/tiles/s2/{natural|snow}/{item}/…webp`, WebP to keep transparency at swath edges,
  z8–14 at 512 px), and natural colour is drawn from the bands rather than the
  `visual` asset, which flattens sunlit snow to white. GIBS: three layers (VIIRS true and
  false colour, HLS S30), days from 2015 to tomorrow. Both share the tile cache, its size
  cap, pruning and miss rate limit.
- **Which day of VIIRS**: the newest of the last four days whose tile over the locations
  isn't black (today's is black until the afternoon pass is processed).
- **HLS differs**: HLS on a fixed day is only the swaths imaged that day, so it isn't drawn
  for its own sake. It is drawn for the day of the Sentinel-2 scene on screen (HLS S30 is
  made from the same pass, and covers its whole swath), when GIBS has that day yet (about
  six days behind). GIBS has no false-colour HLS, so the snow-vs-cloud view goes from
  VIIRS straight to Sentinel-2.
- **Frontend**: base option "Recent satellite" (`prefs.mapBase: 'recent'`; Esri's stays
  "Satellite"); VIIRS at every zoom, HLS from zoom 8, Sentinel-2 from zoom 10, each tile
  of the scene a raster source with its bounds (`lib/map/layers/sat.ts`, under the hill
  shading); place names and contours drawn over it as over Esri imagery. The scene is the
  one of the location nearest the map's middle within 60 km. Controls in the dock
  (`SatControls.svelte`): the chip ("Sentinel-2C · 9 Nov · 2 days ago · 98% clear ·
  Banff Sunshine, 54% snow"), older/newer scene, and Natural / Snow vs cloud
  (`prefs.satBands`). Like Esri's satellite, it needs a connection: offline the map shows
  the saved topo map. Not saved for offline use.
- **Follow-up: views drawn by the worker, stitched and whole.** The first stitched
  version stacked up to eight cloud-cut layers in the browser, each tile made on demand
  from two upstream requests: slow to load and pan, blocky (20 m mask, square cuts, the
  375 m mosaic showing through), and a "whole" scene could end at a swath edge in view.
  Now (`maps/satrender.py`):
  - Each view is drawn once by the worker as one 24 × 24 km picture at 10 m (2,400 px, in
    Web Mercator), cut into 512 px tiles for zooms 9–13, `data/sat/views/<view>/<mode>/`,
    served as static files (`/api/sat/tiles/…`, names change with the content). The
    browser loads one layer of finished tiles; a new view goes on top of the old one,
    which stays until the new tiles are in.
  - Pictures come from Planetary Computer's tiler as four 1,200 px quarters per pass tile
    (a 4,000 px picture timed out; a 2,400 px one took 8–14 s, quarters in parallel ~4 s),
    kept in `data/sat/crops/`: a refresh after the first fetches only new passes (first
    run for six locations 14 min and 676 pictures; later ones seconds).
  - **Whole scenes**: passes of the last 60 days that cover the whole 24 km area (≤ 3%
    without data) and see ≥ 85% of it clearly. Snoqualmie on 11 Nov: 15 Oct, 3 Oct,
    28 Sep; the 21 Oct strip is no longer offered as a whole scene.
  - **Stitched**: per 250 m cell the newest pass of the last 30 days that saw it clearly
    (as before), then made compact: passes seeing < 15% of their coverage clearly are not
    used (their gaps are often haze), each cell goes to the commonest pass in its 5 × 5
    neighbourhood that saw it, three times, and pieces under 1.5% of the area join a
    neighbour that saw them; at most six passes; the newest whole scene fills what's left.
    At 10 m each pixel comes from its part's pass if that pass saw it clearly (parts
    scaled up smoothly), else from the newest other pass that did; cloud margin 80 m.
  - **Cloud SCL misses**: blue over 0.30 and shortwave infrared over 0.25 also counts as
    cloud (snow is dark in SWIR). On 4 Nov a long cloud band over Snoqualmie that SCL
    called clear is caught, while the fresh snow beside it stays; on a snowy limestone
    scene at Sunshine it adds 0.5% of the area, in specks.
  - **Haze SCL calls clear** (Revelstoke, 30 Oct: a grey veil over the valley, with
    fresh snow on the peaks worth keeping): a clear 250 m cell whose blue is 0.06 above
    the lowest blue any pass of the window saw there, and that isn't snow (NDSI < 0.4),
    counts as cloud. The grid request also returns blue, green and SWIR for this.
  - Pixels that every pass saw as cloud come from their part's pass rather than showing
    the 375 m mosaic through a hole.
  - The index gives each part's smoothed, simplified outline (labels: MapLibre writes a
    polygon's label in each tile it crosses, so dates follow the view as it pans) and
    lines only where two parts meet. Index ~30 KB gzipped for six locations.
  - The Sentinel-2 and cloud-cut tile proxies and the HLS layer are gone.
- Follow-up: nothing dims Recent satellite. It isn't darkened in the dark theme, hill
  shading is off over it whatever the setting (Sun & shade still lights the hills, since
  that is the layer), the 3D haze stops at the horizon, and natural colour has a brighter
  stretch with an S-curve for snow.
- Not done: the ≤ 300 MB phone memory measurement (as in milestones 3–4).
- Known limits: Sentinel-2 is 10 m, so up close it is far softer than Esri's sub-metre
  "Satellite"; 10 m imagery covers only the 24 km round each location (the 375 m mosaic
  beyond); stitched parts are planned on a 250 m grid, so lines and dates follow the
  10 m joins only roughly; thin cloud and haze can still slip through; a location with no clear pass in 30 days (Whistler and Snoqualmie on
  11 Nov 2026) shows only the 375 m mosaic; scenes are judged at the location, so cloud a
  few km away can still be in the picture; Sentinel-2 isn't fetched away from locations.

## Milestone 7 notes (done 12 Nov 2026)

What shipped, and where it differs from the plan above:

- **Backend**: `maps/layers.py` and `maps/sources/{snodas,nohrsc,gibs}.py`, the worker's
  `layers` job every `map.layers_minutes` (30), `snowwatch map layers`. Six layers in the
  index's `layers` (each `{frames: [...]}`, a frame with `t`, `file`, `kind`
  forecast/observed, `hours`, `src`, `runs`), drawn into the frames' folder and grid:
  `snowlevel`, `gust`, `ridge`, `depth`, `snowfall`, `clouds`. Every picture is redrawn only
  when its inputs change, and a layer whose source fails keeps its pictures. Probe results in
  `docs/SOURCES.md`.
- **Snow level and gusts differ in reach and source**: every 3 h to the end of RDPS's run
  (~84 h) for both (the plan had wind to 48 h). Canada: HRDPS-WEonG, fading at its domain's
  edge into RDPS-WEonG; the US: NBM (`SNOWLVL`, `GUST`) for both, not HRRR for the gusts as
  planned (NBM covers the whole box, is calibrated, and its run is already in use); joined
  across 48.5–49.5°N as numbers. HRDPS's own `WSPD`/`WGE` aren't used.
- **"Ridge level"** is RDPS's 700 hPa wind (about 3,000 m), one model for the whole box, with
  its direction kept for tap-for-numbers. The map's Wind layer switches between Gusts and
  Ridge (`prefs.mapWind`).
- **GeoMet's snow-level codes** (-1, -2: snow reaching the ground) take the nearest real
  value within 6 cells, then 0 m: mapping them straight to 0 m drew purple blobs on every
  range standing above the snow level. NBM's zeros needed nothing. Bands every 250 m as
  planned, 0 to 4,000 m+.
- **Snow on the ground**: SNODAS (masked to the US, 1 km) and CaLDAS (Canada), joined across
  the border, daily. **Observed snowfall**: NOHRSC 24/48/72 h (US only); its GeoTIFFs are in
  inches, not the metres its netCDFs say.
- **Clouds**: GOES-West GeoColor from GIBS, as planned, every half hour over the last 3 h,
  stitched at zoom 6 and kept as WebP (imagery, not a palette). Its own weather choice, not
  under the radar frames (one weather layer at a time). The infrared band was considered for a
  translucent cloud layer, but GIBS publishes no colormap for it.
- **Speed**: these layers are solid everywhere, so pictures are written straight as palette
  indices (`palette.index_ramp`, `Renderer._save_ramp`); matching each pixel's colour
  (`snap`) took seconds a picture (the first full run took 328 s). Measured 12 Nov 2026: a
  cold run (nothing cached) 82 s, peak 716 MB, most of the excess building NBM's grid map,
  which the forecast job normally has on disk already (~500 MB otherwise); nothing new,
  3 s. Pictures: 27 frames each of snow level (1.7 MB), gusts (3.5 MB) and ridge wind
  (1.9 MB), six cloud frames (1.6 MB); probes ~47 MB on disk in all.
- **A6 tap-for-numbers**: `GET /api/map/point` (`maps/point.py`, `PointOut`). Rather than
  decoding every frame on each tap, the worker keeps every 4th pixel of each picture
  (`data/precip/probe/<file>.npy`, ~6 km: palette indices for precipitation, values for the
  other layers); frames drawn before this get theirs the next time they're reused. Totals come
  from their full grids. Answers in ~35 ms, rate limited, never cached by the service
  worker. Per elevation (A4) waits for milestone 8.
- **Wind-effect fallback** (deferred from milestone 4): the point answer carries loading roses
  for the next 24 and 72 hours, built like a location's (ridge wind direction weighted by the
  snow in each forecast frame, scaled to the window's snow total). Beyond 40 km of every saved
  location the Wind effect layer asks for the map centre's and says it's using it; "Last
  48 h" has no such rose (the forecast frames don't go back), and the concern index still
  needs a location within 40 km.
- **Frontend**: `lib/map/weather.ts` (each layer as a loop of frames or pictures picked by
  window, keys, labels, sources); `Timeline.svelte` lists every layer in one scrolling row,
  with a slider for radar, snow level, wind and clouds and a window picker for snow total,
  snow depth and observed snow; the Layers sheet lists the same. Smooth fields stay on to
  zoom 15, radar and clouds fade by 13. The Inspector ("This spot") adds what the map's
  weather says there: snow for 24 h, 3 and 7 days, the next 48 hours as coloured cells, the
  snow level (and its 3-day low), the ridge wind and gusts, snow on the ground and snow that
  fell.
- **The rain/snow line draped on the terrain** (A5's cheap extra) uses the Snow level layer
  itself rather than a location's snapshot: from zoom 10 a colour-relief layer tints terrain
  above the snow level at the map's centre (for the frame on the slider) white, and the
  ±150 m mix band pink.
- Not done: the ≤ 300 MB phone memory measurement (as in milestones 3–6); particles for wind.
- Known limits: probes are ~6 km, so a tap reads the area, not the slope; the snow level's
  code fill guesses the level under a range from its surroundings; the drape uses one snow
  level for the whole view; observed snowfall stops at the border (Canada has no such
  analysis); SNODAS's glacier cells hold implausible depths (tens of metres).

## Files

- New: `backend/snowwatch/maps/{region,geomet,palette,grib,render,frames,totals,fields,tiles_render,layers,point,sat}.py`,
  `backend/snowwatch/maps/sources/{radar_eccc,rainviewer,hrrr,nbm,rdps_gdps,rrfs,snodas,nohrsc,gibs}.py`,
  `config/treeline.yaml`, `frontend/src/lib/map/**`, `docs/MAP-PLAN.md`.
- Changed: `backend/snowwatch/precip.py` (re-exports), `tiles.py` (new upstreams),
  `osm.py`, `avalanche.py` (zones file), `scheduler.py`, `cli.py` (`snowwatch map …`
  subcommands), `settings.py`, `api/app.py` (routes, CSP), `analysis/build.py` and `doc.py`
  (roses per window), `config/forecast.yaml` (`map:` and `terrain:`), `docker-compose.yml`,
  `backend/pyproject.toml`, `frontend/src/lib/{radar.ts,precipOverlay.ts,prefs.svelte.ts,offlineMaps.ts}`,
  `frontend/src/lib/components/MapView.svelte`, `frontend/src/service-worker.ts`,
  `frontend/package.json`, `docs/{SOURCES,ARCHITECTURE}.md`, `THIRD_PARTY_NOTICES.md`,
  the About page credits.
- Run `snowwatch schema` and `npm run types` after any API model change (CI checks both).

## Verification

- Backend unit tests (coverage gate is 88%): idx parsing; byte-range fetch with small real
  messages as fixtures (HRRR `CSNOW` is 13 KB, `APCP` 175 KB); `index_map` against
  `latlng()` at known points; radar type composition from fixture pictures; totals
  chaining and the 49°N blend; elevation-bin interpolation; the point probe; scene picking
  from fixture SCL crops; tile-proxy whitelists rejecting unknown layers and items.
- Frontend unit tests (vitest): slope and aspect of a synthetic inclined plane; sun
  position against published values; shadow behind a synthetic ridge; Sx sign on windward
  and lee sides; concern-index table cases; `toTimeline` with index v2 and v1.
- By hand, per milestone: `snowwatch precip` (and the new `snowwatch map …` commands), then
  `curl /api/precip` and open the Map page: scrub radar → nowcast → 48 h → day 10 over
  Whistler, Banff, Colorado and the Sierra; compare a snow total against the NWS and ECCC
  maps for the same window; check slope shading against a known 35° slope; check shade at a
  known time against a webcam.
- `npm run e2e -- --trace off` smoke test plus the phone memory measurement.
- `uv run ruff check`, `uv run mypy`, `uv run pytest`, `npm run lint`, `npm run check`, `npm test`.

## Risks and open items

- **GeoMet throttling** (429 under load): radar adds ~3 requests per new frame. Keep two
  at a time and the existing retry; RainViewer remains the fallback.
- **Third-party goodwill**: Mapterhorn (donation-funded) and Planetary Computer tiles (no
  SLA). Fallbacks are designed in: AWS Terrarium or a self-hosted PMTiles extract; GIBS HLS at 30 m.
- **RRFS is brand new**; HRRR stays the primary US short-range source until RRFS has a season behind it.
- **Bandwidth**: NBM long runs are ~60 MB a cycle; configurable cycles.
- **Treeline elevations are approximations**, and so is everything built on them.
- **Display terms**: the concern index is public; avalanche.org's and Avalanche Canada's
  terms for showing a product derived from their ratings haven't been re-read for it.
- **Not verified from the sandbox**: ECMWF open-data paths, Avalanche Canada MIN
  endpoint. (`api.avalanche.ca` answered from the sandbox on 11 Nov 2026.)
- **Not available for free**: an open ATES feed, US avalanche observations without a key,
  sub-daily high-resolution satellite, and radar coverage in terrain-blocked valleys.
