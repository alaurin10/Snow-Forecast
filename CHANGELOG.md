# Changelog

Notable changes to Snow Watch. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **The map's Layers sheet is redesigned**: every choice is a tile of the same size in a
  well, the chosen one raised (as the app's other switches), with "None" first in Weather
  and Terrain and the features shown as toggle tiles; shorter names ("Huts & passes",
  "Avy zones", Concern with a "beta" tag); hill shading beside the base maps; and each
  section's (i) says in one line what the chosen option is. It fits a small phone
  without scrolling, as a sheet above the tab bar.
- **"This spot" and the other map panels share the overview's look**: big numbers in
  tiles (elevation, slope and aspect; forecast snow for 24 hours, 3 days and 7 days),
  snow by height as little bars like the overview's days, label-and-value rows divided
  like its list, the avalanche rating as the usual danger pill, and the chips as a
  segmented well. Glaciers and snow stations use the same tiles.
- **Phones: one control at the foot of the map at a time.** The one last touched (or the
  newest) is open; the others fold to a single line saying what they show, which opens
  them. The Recent satellite controls are one row, with the longer story behind an (i);
  the weather controls no longer repeat the layer choice on phones.
- **A double tap on a phone only zooms.** A tap on the map waits a moment (about a fifth
  of a second) before opening or closing the panel, and a second tap in that moment, as
  in a double tap to zoom in or a double tap held and dragged to zoom with one finger,
  calls it off. Pans and pinches never count towards a double tap, so the first tap after
  one acts. A mouse click still acts at once.
- **A tap elsewhere on the map puts the panel away**, rather than opening it on the new
  spot; the next tap opens it again.
- **On a glacier or an ATES area, a tap shows the spot first** (its terrain and weather),
  named for the glacier ("This spot · Tacoma Glacier"), with a line for the glacier and
  its area, and the ATES rating under Avalanche. The glacier's own card is a chip, or a
  tap on its line, away.
- **The phone sheet follows your finger anywhere on it.** At the peek, a swipe up (or a
  scroll) grows it instead of scrolling its few lines; grown, the content scrolls, and
  pulling down from its top shrinks it again. A tap on the title bar still switches.
- **The map stays still when its panel opens**, on desktop and on phones (the controls
  at the foot hide under the sheet without giving up their place).
- **One gesture on the map: a tap.** What the panel shows first follows the zoom, as
  the map does: zoomed out, where avalanche zones are coloured and glaciers are specks,
  the zone's bulletin, then the spot; zoomed in past where the zones' colour fades, the
  spot, with the zone last. An open panel follows the zoom too, until you pick a chip.
  The long press and right-click shortcuts are gone.
- **Glaciers tell you more**: their type as mapped (valley, cirque…), area, the
  elevation of the top and the toe, the distance and drop between them, which way the
  ice flows, its average slope and how much is steeper than 30°, worked out from the
  terrain over the whole mapped outline; the forecast snow for 24 hours, 3 days and 7
  days at the top's and the toe's heights, and the snow level; and a Wikipedia link
  when mappers gave one.
- **A tap on the map opens one panel, always in the same place**, whatever it lands on:
  docked to the right edge on desktop (the terrain key and the map credits step left of
  it), a bottom sheet above the tab bar on phones and tablets (drag its handle, or tap it,
  between a peek and most of the screen).
- **The panel opens on what you tapped, not always on "This spot".** A station, a field
  report, a hut, trailhead or pass, a run or route, a glacier, an ATES rating or the
  avalanche zone (while zones or an avalanche layer are on) each has its own content, most
  specific first, with chips for the rest ("Glacier · Zone · This spot") that switch it in
  place. Its terrain and weather are only worked out when "This spot" is shown. Huts,
  passes and glaciers link to OpenStreetMap.
- **"This spot" is tidier**: three sections in a fixed order (Terrain; Snow & weather,
  with a small 24 h / 3 days / 7 days table; Avalanche), one line per row with the label
  on the left and the number on the right. Rows hold their place while the numbers load,
  the concern index's arithmetic sits behind "How?", every caveat is in one "About these
  numbers", and the coordinates under the title copy on a tap.
- **On the map, the phone and tablet tab bar is icons only** (as it is while scrolling
  down other pages), leaving more of the map in view. Its height doesn't change, so the
  controls above it stay put.
- **The desktop rail never moves.** It sits in one place on every page (14 px from the
  window's top left), over the map too; only its background gets denser there. Folding
  it on the map slides it away and fades its button in, instead of swapping one for the
  other.
- **A location's sections are its page's tabs on desktop too**, so the rail's list of
  locations no longer grows when one is open. Keys 1–4 pick a section (from further
  down the page, that scrolls back up to the tabs, so a section starts at its top). On
  desktop and tablet the tabs and the elevation sit right under the location's name as
  two pills that scroll with the page.
- **Only the elevation sticks, on every screen.** Once the page's elevation picker has
  scrolled away, a compact one (numbers only) slides in at the top right; on windows
  wide enough to have an empty margin beside the page, it stands there instead, stacked,
  so it covers nothing. On phones the conditions row no longer sticks.
- **The chart's range (1–10 days) and Timeline switch sit under the chart on desktop
  and tablet too**, next to the timeline, where the pointer already is (as on phones).
- **Notices float at the top as a toast** (new version, offline, stale forecast) and can
  be closed, instead of pushing the page down when they appear. The full map keeps its
  own offline note.
- **The phone conditions pill is a weather icon and the temperature** (sun, moon,
  cloud, fog, rain, snow, mixed), instead of a sky name cut to "Ov…" beside the
  elevations. It's the same width whatever the weather; a tap shows the words
  ("Overcast · 33°F · Summit · updated …"), which are also its accessible name. On
  desktop the same icon replaces the plain sky swatch.
- **Chosen buttons and tabs no longer change width.** Selection is shown by colour and
  background only (it used to turn the label bold, which made it wider and could push
  its neighbours onto another row).
- **The desktop map fills the whole window.** The rail floats over its left side and
  folds to a small button (remembered in the browser); the map's buttons move clear of
  it. Like a phone's maps app, the map's centre sits in the space the rail and the panels
  at the foot leave free, and slides when a panel opens or the rail folds, so fits,
  fly-tos and "the middle of the map" (the zone, wind and scene the layers use) follow
  what you can see. On phones and tablets the same applies to the panels above the tab bar.
- **The map opens flat over Washington.** The full map now always starts as a 2D map
  framing Washington State, rather than framing every location; 3D terrain lasts for the
  visit (switching it on, or tilting the map, no longer carries over to the next one).
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
- **Pin Layers open (desktop)**: a pin in the sheet keeps it beside the map's buttons,
  remembered in this browser; a tap on the map then reads the spot instead of closing it.
  A row of terrain overlays (None, Slope, Aspect, Elevation, Sun, Wind, Avy) sits over
  the weather controls.
- **Full screen forecast chart on phones and tablets**: an expand button opens the chart
  over the whole window, where a finger scrubs it without scrolling the page (and it asks
  for landscape where the browser allows). In the page, a touch on the chart now picks
  sideways (read the chart) or up and down (scroll) after its first few pixels.
- **View a location on the map.** A Map button on each location page opens the map
  centred on it, close in and flat, with its popup open (`/map?loc=<id>`); the popup's
  "Open forecast →" goes back.
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

### Fixed
- **The Calendar no longer fails with "Something went wrong"** when a location storms
  twice inside another location's longer storm: a storm cycle now lists each location
  once, with its storms' totals added together. The error page now shows what failed,
  in small print, and the browser console logs it in full.
- **The current-conditions pill is no longer cut off** on desktop or phone (including
  when it sticks to the top). Long text ends in "…" and the temperature always shows;
  on phones the pill and the elevations stay on one row. On desktop, "Updated …" has its
  own pill. The Calendar's subtitle does the same.
- **Satellite no longer brightens as you zoom in.** Hill shading over imagery now ramps
  up with zoom (and uses a softer shadow) to even out MapLibre's stronger shading when
  zoomed out.
- **Avalanche danger zones stop tinting the map up close.** Their colour fades out by
  zoom 11; the outline stays at every zoom, as the boundary and the thing to tap.

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
