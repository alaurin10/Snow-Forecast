# Map weather overlays: radar rework and layer fixes

Status: in progress (started 16 Nov 2026). This is the working plan for the map's weather
layers; `docs/MAP-PLAN.md` is the map's history up to here. Milestones are ordered
hardest first. Tick them off here as they land.

## Why

The owner's list, and the cause found for each by reading the code and the live sources:

| Complaint | Cause |
|---|---|
| Jumps between nowcast and forecast | Hourly forecast frames (stamped with the hour's *end*) sort in between nowcast frames, so the loop goes nowcast → model → nowcast (`render.py:_index`, `radar.ts:toTimeline`). The hand-over fades a *frozen* last-nowcast picture over two hours of moving model frames (`radar.ts:handover`). In the northern US the model is HRDPS to 48 h, then NBM. |
| Frames slow to load; the display freezes | ~110 whole-box PNGs (1700×1970), four at a time. The "urgent" flag does nothing for a frame already queued (`precipOverlay.ts:blob`). A failed download draws a blank and is never retried. |
| Fast scrubbing lags | Every slider event is a PNG decode (four kept), a 3.3 MP canvas draw and a 13 MB texture upload; in 3D it also drops every draped terrain texture (`redrape`). Events aren't coalesced and work for frames passed over isn't cancelled. |
| Blending is messy | Hourly frames prefer HRDPS wherever it reaches; 3 h/6 h frames, totals, snow level and wind split at the border. Two rules. |
| Wrong data (the Rainier echo) | One radar source (ECCC's composite, decoded from pictures), no quality control beyond the Rainier fix, no coverage mask (no echo and no coverage look the same), no staleness check; if both radar sources fail the radar is wiped. |
| Snow total blank until the map moves (3D) | MapLibre 6.17 redraws a draped terrain texture only when its fingerprint (source id, tile keys, zoom, visible layers) changes (`src/webgl/render_to_texture.ts`, `rtt_fingerprint.ts`). `setSnowTiles` reuses the id `snowtiles`, so a new window's tiles have the old fingerprint and are never drawn. Also: tiles are drawn on demand behind a shared rate limit, errors aren't retried, and nothing says "loading". |
| Clouds: past only | Only GOES imagery is fetched. GeoMet has `HRDPS.CONTINENTAL_NT` (hourly to 48 h), `RDPS_10km_TotalCloudCover` (to 84 h), `GDPS_15km_TotalCloudCover` (to 240 h), all by WCS; NBM has TCDC. |
| Sun: the last frame changes the whole map | At altitude ≤ 0 the hillshade swaps method, light direction and anchor (`sunPaint` → `shadePaint`); at ≤ 0.25° the shade becomes a full veil (`shade.ts:cast`). Two thresholds, both hard steps. |

## Decisions (owner, 16 Nov 2026)

- **Models:** US models in the US, Canada's in Canada, blended across the same border zone
  at every lead time (no HRDPS-first rule in the northern US).
- **Radar drawing:** on the graphics chip again, done differently from the reverted
  attempt (see "What went wrong last time").
- **Radar range:** better coverage inside the map (MRMS, a coverage mask, filled gaps)
  *and* a bigger area.
- **Clouds:** the forecast follows the satellite loop on one timeline.
- More memory is acceptable.

## What went wrong last time (commits f3d9fb2, 3a66d94, reverted in b2d345a)

1. Types were carried in texture channels including alpha, through the browser's image
   decoder: premultiplied alpha corrupts such data. → Now: raw bytes, inflated in a
   worker, uploaded from typed arrays. Never an image decode.
2. Smoothing mixed a wet pixel's type with a dry neighbour's "no type" → rain shown as
   snow and the reverse. → Now: type is one number ("snowiness": rain 0, mix ½, snow 1),
   filled across dry ground from the nearest wet pixel before it is stored, so
   interpolation at an echo's edge is always between real types.
3. Flat used a shader, 3D a CPU painter: two implementations disagreed. → Now: one
   shader for both.
4. Textures weren't rebuilt after a phone dropped them. → Now: compressed bytes are kept
   and every texture is rebuilt on `webglcontextrestored` and on return from background.
5. The first version did 32–128 texture reads a pixel. → Now: two reads per frame (rate,
   type), two frames blended.

## Milestones

### M1 — Server: frames as numbers, one time axis, a real hand-over

- [x] `backend/snowwatch/maps/dataframe.py`: a precipitation frame as byte planes.
  - **rate**: `0` dry, `1..255` log-spaced 0.02–100 mm/h (`code = 1 + 254·ln(r/0.02)/ln(5000)`).
  - **type**: snowiness `0` rain, `128` mix, `255` snow, at ¼ of the rate plane's
    resolution, filled across dry ground (nearest wet pixel), lightly blurred.
  - File: 16-byte header (`SWF1`, version, rate w/h, type w/h) + planes, each row
    delta-filtered (left neighbour), then one raw-deflate stream. Name
    `<prefix><t>-<sha12>.bin`, immutable.
  - Resolution by source: radar and nowcast full, hourly models ½, 3 h/6 h models ¼.
- [x] `render.py`: `_save_precip` also writes the data file; index v3 adds per frame
  `data`, `dw`, `dh`, `valid` (the instant the frame stands for: scan time, or the middle
  of a forecast window). PNGs and probes stay for now (old cached apps, taps).
- [x] `_index`: no forecast frame at or before the last nowcast frame. Radar never
  committed empty: keep the last frames, mark `radar_stale`.
- [x] Hand-over on the server: each nowcast frame is `(1−w)·nowcast + w·model(t)`,
  `model(t)` interpolated in time between the bracketing forecast frames (read back from
  their data files), `w` easing 0 → 1 over the nowcast's span. `point.py` and `radar.ts`
  lose `HANDOVER_S`.
- [x] `api/app.py`: serve `.bin`. `frontend/e2e/precip_fixture.py` writes v3.

### M2 — App: radar on the graphics chip, continuous scrubbing

Landed (with M1). As built: the queue is `loader.ts` (nearest the slider first, six at a
time, cancels, retries); playing is a `requestAnimationFrame` loop in `MapView.svelte`
rather than a separate clock module. `e2e/radar.spec.ts` checks free scrubbing, every frame
drawn in 3D and recovery after a lost context. Phone profile (`perf.spec.ts`, 17 Nov
2026): page process peak 342 MB (was ~430), a new frame 0–1.1 ms on the main thread
(was ~10 ms); the graphics process holds more (441 MB peak, SwiftShader).

New `frontend/src/lib/map/precip/`:

- [x] `codec.ts` + `frames.worker.ts`: fetch, inflate (`DecompressionStream('deflate-raw')`),
  unfilter, optional 2× downsample, off the main thread.
- [ ] `store.ts`: priority queue that can re-prioritise and cancel; every frame resident
  as two R8 textures within a byte budget (desktop: radar at full resolution; phone:
  radar at ½ plus full for the frame at rest); compressed bytes kept for rebuilds.
- [x] `gl.ts`: one program. `rate = mix(A, B, f)`, `type = mix(A, B, f)`, colour from a
  LUT built from `radar.ts:RAMPS` (pinned to `palette.py` by a shared fixture), soft
  alpha above the 0.1 mm/h floor, premultiplied.
- [x] `layer.ts`: a MapLibre custom layer: `render` (flat) and `renderToTerrainTile` +
  `terrainTileRevision` (3D). Kept honest by e2e tests: 30 frame changes in 3D each
  change the pixels; flat and 3D colours match; forced context loss recovers; a rain and
  a snow frame match the server palette. Fallback if the 3D hook fails those tests: the
  same program draws into our own WebGL canvas fed to a MapLibre `canvas` source.
- [x] `clock.ts` + `Timeline.svelte`: the slider is a continuous position; frames blend by
  `valid` time; playing advances smoothly; one draw per animation frame.
- [x] `MapView.svelte`: radar on the new path; `PrecipLayer`/`FrameStore` stay for the
  pictures (snow totals, depth, snowfall, snow level, wind, clouds).
- [x] `service-worker.ts`/`swRoute.ts`: `.bin` frames cached and pruned like PNGs.
- [ ] `e2e/perf.spec.ts`: a scrub test (phone, flat and 3D): time from slider event to
  pixels, and the memory ceiling.

### M3 — Sources, blending, accuracy

- [x] `maps/sources/mrms.py`: NOAA MRMS from `noaa-mrms-pds` (`CONUS/PrecipRate_00.00`,
  `PrecipFlag_00.00`, `RadarQualityIndex_00.00`; 20–55°N, 130–60°W, 0.01°, every 2 min).
  Decode with `gribberish`; crop to the region before converting to floats (the 650 MB
  peak noted in MAP-PLAN came from the whole grid).
- [x] (Landed differently: ECCC's rates stay the base, so the nowcast, which extrapolates
  ECCC, carries on from the last scan without a jump; MRMS checks them in the US:
  `radar_eccc.Check`, `apply_check`, `Clutter`. Its quality index isn't readable by
  gribberish; MRMS is read from its PNG packing directly.) Radar frame = `mosaic([MRMS, ECCC composite])`, feathered at MRMS's edge. Types:
  MRMS `PrecipFlag`, then ECCC's type picture, then the forecast. RainViewer last.
- [ ] Coverage plane (¼ res) in the data frame from MRMS's quality index and GeoMet's
  `RADAR_COVERAGE_RRAI`. Where no radar sees, fill from the current forecast hour, drawn
  lighter with a hatch; legend line and a "Fill radar gaps" toggle; taps say so.
- [ ] `maps/qc.py`: speckle removal; a learned clutter map (echo in nearly every scan
  while surroundings and the model are dry; on disk, with decay); frame sanity checks
  (wet-area jump, stale scan) that reject a frame and keep the last good one.
  `health.json` per source on the Status page.
- [x] One ownership rule (`blend.py`, `render.py:forecast/_extended`): south of the
  border zone HRRR → NBM hourly → NBM 6 h; north HRDPS → RDPS → GDPS; `north_weight` at
  every lead time; RDPS fills where neither reaches; two frames cross-faded where one
  model hands to the next in time.

### M4 — Fixes that need no new architecture

- [x] **Snow total** (landed without the server pre-drawing tiles round locations; add it if
  first views are still slow) (`map/layers/snowtiles.ts`): source and layer ids carry the tiles id;
  the previous window stays until the new source has loaded (as `layers/sat.ts` does);
  errored tiles retried with backoff; a spinner in pick mode; other windows' pictures
  prefetched. Server: snow tiles get their own rate limiter, 503 carries `Retry-After`,
  and tiles z8–10 round saved locations are drawn ahead after each totals run.
- [x] **Sun & shade** (landed as: `dusk()` in `terrain/shade.ts`, a straight ramp from 8°
  to 0.25°, shared with `sunPaint`'s highlight; slider ends unchanged) (`map/style.ts`, `terrain/shade.ts`, `layers/terrain.ts`): one light
  model from 10° up to 6° below the horizon: `sunPaint` throughout, highlight and shadow
  easing with altitude; `paintShade` dims lit ground smoothly as the sun nears the
  horizon so it meets the shadow at sunset; one threshold constant; the slider ends on
  the exact sunrise and sunset.
- [ ] **Picture player** (`precipOverlay.ts`, still used by the other layers): real
  priority queue, retries, no cached `null`, try/catch in `show()`, a token on `refresh()`.

### M5 — Cloud forecast on the Clouds timeline

- [x] `maps/layers.py`: after the satellite frames, total cloud cover from HRDPS (to
  48 h), RDPS (to 84 h), GDPS (to 10 days) north and NBM `TCDC` south, 3-hourly then
  6-hourly, blended like `model_field`; white with alpha by cover (`palette.CLOUD`).
- [x] `map/weather.ts`, `Timeline.svelte`: "Now" at the last satellite frame; labels, key
  and source text.

### M6 — Bigger area

- [x] A second, coarse region `wide` (North America, about 15–72°N, 170–50°W, ~6 km a
  pixel; `config/forecast.yaml: map.wide`), drawn by a second `Renderer` into
  `precip/wide/` at a slower pace. Radar: ECCC composite + MRMS (CONUS and Alaska);
  forecast: the same ownership rule, RDPS/GDPS where no fine model reaches.
- [x] (Landed as radar and nowcast only, via the same `Renderer.radar` into `precip/wide/`,
  served at `/api/precip/wide`; 1800 × 1356 px, 23 frames of ~31 KB, a 90 s cold build at
  317 MB. Taps outside the box aren't read from it yet.) App: the wide frames draw beneath the home box and load when the view leaves it;
  frames pair by `valid` time; taps outside the home box read the wide probes.

## Verified facts about the sources (16 Nov 2026)

- GeoMet radar: `RADAR_1KM_RRAI`/`RSNO` keep 3 h at 6 min; the extrapolation layers run
  72 min ahead at 6 min and keep 3 h of reference times; `Radar_1km_dBZ-Extrapolation`
  and `RADAR_COVERAGE_RRAI` (time-enabled) exist. Bounds 16.9–67.2°N, 170.3–50°W.
- GeoMet models: `HRDPS.CONTINENTAL_RT` (instantaneous rate, hourly) and `…_NT` (cloud)
  exist as WCS coverages; HRDPS's bounding box is 27.3–70.6°N, 152.8–40.7°W.
- MRMS on S3: `PrecipRate` ~0.4 MB, `PrecipFlag` ~0.15 MB, `RadarQualityIndex` ~0.75 MB
  per file, gzip GRIB2, every 2 minutes; an `ALASKA/` domain has the same products.
- RRFS (`noaa-rrfs-ops-pds`): 3 km CONUS and Alaska hourly, 15-minute `subh` files to
  18 h, 13 km North America. Not used yet; a candidate for 15-minute forecast frames.
- MapLibre 6.17: custom layers may implement `renderToTerrainTile(gl, {tileID, width,
  height})` with `terrainTileRevision`; clip space (−1,−1) is the tile's south-west
  corner. A revision change redraws only the stacks holding the layer.

## How to check the work

- Backend: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy snowwatch && uv run pytest`
- Frontend: `cd frontend && npm run lint && npm run check && npm test && npm run build && npm run e2e -- --trace off`
- Live: `snowwatch map radar|forecast|layers` into a scratch `DATA_DIR`, then look at the
  frames (MRMS/ECCC seam, Rainier, the hand-over, the 48 h join at Snoqualmie).
- Browser: Playwright at phone and desktop sizes, flat and 3D; `perf.spec.ts` numbers in
  each PR.

## Found along the way

- 3D terrain near Whistler shows a wall with stretched stripes along a band (with no
  weather layer at all, 17 Nov 2026, SwiftShader): elevation tiles from different
  sources not meeting? To look into separately (`terrain/dem.ts`).
