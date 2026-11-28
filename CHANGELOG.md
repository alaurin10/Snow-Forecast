# Changelog

Notable changes to Snow Watch. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **16 days on the location pages** (milestone 4B). The forecast chart's 15-day view
  runs to the end of the forecast with a second "Less certain →" mark 10 days out (bars
  and lines look the same throughout). The day by day lists 16 days, the Calendar shows
  16 columns (on a phone the rows scroll sideways together, names and dates staying in
  step), the Confidence tab's table shows 16 days with a 10-day total and its chances
  add days 11–16, the day-by-day image can share 16 days, and wide screens' Overview
  adds a "Days 11–16" column.
- **16-day forecasts** (milestone 4B, the data). Every location and spot now carries
  today and the next 15 days: the high-resolution blend is asked for 16 days (it was
  11), snapshots hold 32 day-and-night periods and 16 days of hours, and a "Days 11–16"
  window (with the ensembles' range) joins "Next 5 days" and "Days 6–10". Past about
  day 10 the forecast rests on the ensemble mean. Days 11–16 have no ski-day rating,
  nothing alerts past its usual limit, and each snapshot says where the forecast
  becomes less certain (5 and 10 days out). `snowwatch check-sources --local` lists how
  far each model reaches. The forecast chart offers 15 days (its range buttons read
  "1d … 15d" on a phone) and Compare goes to 16 days with a 15-day range.
- **Room for ~50 locations** (milestone 4, locations and UI). Manage's "Add a resort"
  can tick several ski areas and add them at once: the worker resolves each with every
  detected detail and fetches its forecast (`POST /api/admin/locations/catalog`, a
  queued `catalog` job each). With nine or more locations the Overview and Calendar get
  a filter, browser-saved favourites (the star on the Overview) and a group per state
  or province; the Compare picker and the location palette match a state's name too,
  and the palette lists favourites first. A new location's first satellite pass runs in
  the background within half an hour instead of waiting for the next full pass. The
  map's box no longer widens for locations within a degree of its edge, only for ones
  outside it.
- **Ensembles at every elevation** (milestone 4, ensembles and budget). Each ensemble
  system is asked at base, mid and summit in one request, so each band's likely range,
  chances and the forecast after 48 h come from its own members (no more "(est.)" from
  scaling mid's). Each system follows its own schedule (`schedule.ensemble_runs`: GEFS
  and ECMWF ENS four times a day, GEPS twice; replaces `ensemble_runs_utc`). A budget
  planner (`snowwatch/budget.py`) picks the richest of four tiers that fits the public
  daily limit (three bands or mid only, every run or two a day), drops a tier as
  locations are added, and shows on `snowwatch budget` and Manage. Systems the
  self-hosted server answers are free and always at three bands, spots included.
- **Fresher forecasts** (milestone 4, refresh and retention). With a self-hosted
  Open-Meteo server, each location refreshes a few minutes after a model it uses has a
  new run (HRRR and NBM hourly; at most every 40 minutes, at least every 3 hours;
  `schedule.refresh: data`, or `fixed` for the old schedule), instead of every 3 hours.
  The worker reads each model's run every 5 minutes; the Status page lists them and the
  Confidence tab says which runs a forecast was made from ("GFS 18z · ECMWF 12z · HRRR
  22z"). Spots are kept until their country's models update. Runs fetch four locations
  at once, serve queued Manage jobs between locations, and fetch SNOTEL's daily values
  every 6 hours. 24 snapshots are kept per location (was 8); after 48 h the daily
  forecast history keeps runs 6 h apart plus each day's last (the scorecard's), and raw
  responses are kept 6 h (was 24).
- **More from the self-hosted server's data** (milestone 3b). The chart's freezing-level
  view is now **Snow level** (snow level solid, freezing level dashed); freezing rain
  and sleet get pink "Ice"/"Sleet" marks on the snow view; the temperature view adds a
  dotted wet-bulb line. A rain/snow split by each band's wet-bulb is scored as
  `cons_wb` (switch with `physics.snow_split: wetbulb`). Spots without a station use the
  models' snow depth for rain on snow; snow falling through a wet-bulb above 0 °C is
  "Heavy & wet"; fog costs the ski day a step; very humid nights refreeze Partial at
  best; snowy periods with high CAPE say "showery". The scorecard names `cons_col` and
  `cons_wb`.
- **Richer weather on the page** (milestone 3, UI). With the self-hosted server: wet-bulb
  and freezing rain in the band table and period details, how the snow level was found,
  the column snow ratio, a "Sun (est.)" factor in the avalanche-weather outlook, fog,
  rime and corn-window rows in touring weather, a Model snowpack card on the Observed
  tab (every spot gets one), and Freezing rain as a push alert choice. The freezing-level
  chart now draws the snow level as a dashed line.
- **Richer weather with the self-hosted server** (milestone 3, backend). With
  `OPEN_METEO_URL` set, each run asks the server for humidity, wet-bulb, radiation,
  model snow depth and seven pressure levels with humidity (the public API keeps
  today's lean requests, also on a fallback). Snapshots gain: a snow level from the
  wet-bulb profile instead of the freezing level less 305 m, precipitation type by
  wet-bulb, freezing rain and sleet per hour (and a `freezing_rain` flag and push alert),
  the column snow ratio (`depth_method: column`, scored on the scorecard as `cons_col`
  beside `cons` and `cons_slr`), ridge wind interpolated between the two levels around
  the summit, a sun factor and sunshine per aspect in the avalanche-weather outlook, a
  spring corn window, rime and fog hours in touring weather, and the models' snowpack.
  Thresholds in `config/forecast.yaml` (`physics:`, `backcountry:`).
  `snowwatch check-sources --local` lists which models carry each new variable.
- **Self-hosted forecasts (optional).** Snow Watch can run Open-Meteo's own server next
  to it (compose profile `openmeteo`, then `OPEN_METEO_URL=http://openmeteo:8080`; see
  DEPLOYMENT.md step 5). Every forecast and elevation then comes from it for free; only
  ensembles use the public API (~24 calls per location a day instead of ~316), so up to
  50 locations with no pause between them. If the server is down, saved locations fall
  back to the public API within its daily limit. Off by default: nothing changes until
  it's turned on. Needs a CPU with AVX2 or ARM64.
- **Status shows the self-hosted server**: whether it's answering, how fast, today's
  requests and how many fell back to the public API. The usage bar now counts public
  Open-Meteo calls from a ledger of every request, and Manage shows the budget split
  between the server and the public API.
- `snowwatch openmeteo status` (CPU, one request's time, today's fallbacks and public use,
  each model's latest run) and `snowwatch check-sources --local` (every model and
  variable on the server, and the share of empty values against the public API).
- **Self-hosted ensembles, part 1: the downloader (optional).** With the compose profile
  `ensembles` next to `openmeteo`, a new service downloads every GEFS, ECMWF ENS and GEPS
  run (snowfall only, 16 days) from NOAA, ECMWF and Environment Canada into the server,
  which serves them right away. ~15 GB of downloads a day; on disk it stays at about
  1.5–2 GB (it deletes what isn't needed after each run) and pauses below 5 GB free.
  `snowwatch openmeteo status` lists each system's run, age, reach, size and last error,
  and free disk (warning under 10 GB). See DEPLOYMENT.md, "Self-hosted ensembles".
- **Self-hosted ensembles, part 2: the app uses them.** `OPEN_METEO_ENSEMBLES=local`
  takes each system's ensembles from the server while its downloaded run is fresh and
  complete, every run and for free, so `snowwatch budget` drops to ~0 public calls.
  A system whose run gets old, or whose answer comes back short, falls back on its own:
  first to the cached ensembles, then to the public API on its usual schedule, keeping
  room in the public budget for forecasts if the whole server is down.
  `OPEN_METEO_ENSEMBLES=shadow` keeps public ensembles and compares the server's each
  run; the Status page summarises a week of it, and `snowwatch check-ensembles` compares
  whole forecasts. `public` (the default) changes nothing. The Status page, Manage's
  budget and `openmeteo status` show where each system's ensembles come from.
- **Forecasts anywhere, part 1: the API.** With a self-hosted Open-Meteo server,
  `GET /api/spot?lat=&lon=` builds the full forecast a saved location has for any point
  in the US or Canada, in seconds: three bands chosen from the terrain around the point,
  named after a nearby peak or saved location, with alerts (US) and ensembles (from the
  server when it has them, otherwise from the public API within a daily allowance of
  2,000 calls, `spots` in `config/forecast.yaml`). `GET /api/spot/nearby` adds the
  nearest snow stations, field reports and the avalanche zone with its rating. Built
  spots are kept for an hour; new ones are rate limited per visitor and for the site.
  Without a server, both answer 503 and nothing else changes.
- **Forecasts anywhere, part 2: the app.** With a self-hosted forecast server, tap any
  point on the map and press **Full forecast here** (or right-click, or long-press) for
  the same forecast page a location has, at `/spot?lat=…&lon=…` (shareable): three bands
  from the terrain, the tapped one marked "This spot" and opened first, with the
  Forecast, Confidence, Backcountry (the zone's rating) and Observed tabs; no trend,
  scorecard or webcams. The last 10 spots are listed on the Overview and in the location
  palette (Ctrl/⌘ K), and kept for offline use. The owner can **save a spot as a
  location** from its page.
- **Faster forecasts anywhere.** A spot's requests now run at once, and the multi-model
  forecast and upper air are asked for one model each: in a new area a spot takes about
  6 s instead of 24, and a fresh server about 32 s instead of 128. While it waits, the
  page shows the seconds and says why a new area is slower.
- **The map stays where you left it.** Back from a spot (or any page) opens the map at
  the same place, zoom and tilt, so the next spot nearby is one tap away.
- **Peaks named everywhere on the map**, not only around saved locations.
- **Spots start before you press the button.** Once the map's spot panel has been open
  on a point for a moment, its full forecast starts making, so "Full forecast here" is
  often instant. It has an allowance of its own and never makes others wait.
- **A spot shows just its own elevation**: the forecast for where you clicked, without the
  bands above and below, with that elevation where the picker would be.
- **Spots are named after the terrain**: the peak you tapped, or how far and which way
  from the nearest one ("0.8 mi S of Mount Stuart"), anywhere, not only near saved
  locations.
- **Saving a spot as a location** (owner only) opens the zone form with the spot as the
  mid pin, to place the low and high points, so it's saved as a full location.
- **Back on the map, the spot you just opened is still marked**, with its panel open.
- **Back from a spot goes to the map**, and the map opens straight at the view you left
  (no zoomed-out flash first). Signed in as the owner, every spot panel you open starts its
  forecast early, with no allowance.
- **The snow level map shows what falls where: snow, mix or rain.** Instead of 17
  colours for the snow level's height, three colours (the radar's blue, pink and green)
  show where the ground is above the snow level, within 150 m (500 ft) of it, or below it.
  It's drawn on the device like the temperature, so zoomed in it follows every ridge with
  the snow level at each spot (not one level for the whole screen), and its slider moves
  smoothly between the 3-hourly frames.
- **The map's temperature says where it reaches 32 °F.** Zoomed in, a line under the key
  gives that height at the map's centre, so it can be read beside the snow level's
  "Snow above …". The snow level's note says why the two differ: snow usually reaches
  about 1,000 ft (300 m) below the 32 °F level, and sometimes much further.
- **Field reports on the map show what was reported**: a tapped report now has the
  observer's signs of instability (coloured as on NWAC's site), their summary (first
  lines, then More) and notes, and their photos, which open the full-screen viewer.
- **Photo gallery on wide screens.** Gallery (on the Webcams tab, or the grid button in
  the viewer) shows every field photo at once, each with its place and day; one opens on
  its own.
- **Swiping in the photo viewer.** The photo follows your finger and the next one slides
  in quickly (no motion with the app's motion setting off); swipe down to close.
- **Recent observations on the Backcountry tab.** What forecasters and people in the
  mountains reported around the location in the last two weeks: near it first, then,
  folded, the rest of its avalanche zone. Each shows who sent it, the day, the place and
  distance, the signs of instability they reported (avalanches seen, triggered or someone
  caught; collapsing; shooting cracks, with how widespread), their summary (first lines,
  then More) and their notes on instability and avalanches, small photos that open the
  full-screen viewer, and a link to the full report. The Webcams tab keeps to the photos.
- **Field photos full screen.** A photo on the Webcams tab opens a full-screen viewer
  that flips through every photo (arrows, arrow keys or a swipe), each with the report's
  place, who sent it, the day, how far away, the zone and the caption, and a link to the
  full report. **View all** starts from the first; Escape, ✕ or the phone's Back button
  close it and leave you where you were.
- **NWAC observation photos on the Webcams tab.** Locations in Washington and northern
  Oregon show recent photos from NWAC's observations (forecasters' and the
  public's) within 60 km, by the day observed, each with who sent it, the zone and a link
  to the full observation on nwac.us. The worker reads NWAC's observations page (with
  NWAC's agreement) in headless Chromium every 3 hours; the image now includes Chromium.
  The same observations show on the Observed tab's field reports and the map's field
  reports layer. Off with `map.nwac_obs: false`; read now with `snowwatch map nwac`.
- **Compare from a location**: a Compare button beside Map on every location page opens
  Compare with that location in it and the Add list open, to pick the others.
- **Compare's Add list ranks every location** by the metric being compared, over the days
  the chart shows and at the chosen band (snow total, high and low, top gust, average
  cloud, lowest freezing level or average snow ratio), with a "best first" order (most
  snow, coldest, lightest wind, clearest, lowest freezing level, driest snow) beside "My
  order". New endpoint: `GET /api/compare`, every location's next 10 days at each band.

### Changed
- **Rain and snow are split by each elevation's wet-bulb** (milestone 3c, with the
  self-hosted server). Last winter at Crystal, Snoqualmie and Rainy Pass SNOTEL, the
  models' own split put 16 points too little of the precipitation into snow (about
  6.6 mm of snow water short per wet day); the wet-bulb split, refined to snow at or
  below 0 °C and rain from 1 °C with a guard for warm air aloft, was within 4. Snow
  totals near the snow line rise accordingly. The scorecard still scores the models'
  own split ("Consensus (models' own rain/snow split)"). `backend/scripts/
  backtest_split.py` re-runs the comparison for any stations and season.
- **The self-hosted server's cache defaults to 10 GB (was 30 GB).** It's reserved on disk
  in full when the server starts, and 30 GB filled a 60 GB disk; ~27 MB per location was
  measured, so 10 GB is plenty for 50. DEPLOYMENT.md now says to check free space first.
- **The automatic deploy clears Docker's build cache older than a week.** It grew with every
  rebuild and reached 16.8 GB on the home VM.
- `snowwatch budget` prints the public and self-hosted estimates separately, plus today's
  actual public calls. The api container's memory limit is 768 MB (was 384 MB), ahead of
  forecasts built on demand. NWS, SNOTEL and the BC snow-pillow server get at least half a
  second between requests.
- **The backend tests no longer reach the network**: the worker's map test and the
  healthcheck test stubbed only part of their jobs, so they drew every weather layer and
  fetched avalanche forecasts for real. The suite takes about a minute and a half, down
  from 8–15 minutes.
- **Every factor in the avalanche weather is one line**, the same height, down to a
  360 px phone: "Snow" for the label, and shorter context for warming ("at the
  summit", "in 24 h") and light drifting ("little to drift").
- **The Backcountry tab's avalanche weather is easier to read, especially on a phone.**
  Each day is its own tile: the day, the avalanche center's rating when its bulletin
  covers the day, and a chip with the day's grade, now called **weather loading**. Under
  it, one line for each factor that is pushing on the snowpack (name, number, a few
  words such as "loads NE" or "18.1 in / 3 days", and a small meter for that factor's
  level), always in the order snow, wind, rain, warming; a quiet day says "Calm". A key
  under the days says what Little, Some, Strong and Very strong mean, and "See the
  numbers behind each level" shows the thresholds in your units. The snapshot now
  carries those thresholds (`backcountry.outlook_steps`). With `HAZARD_INDEX` off each
  day shows all four facts and no grade.
- **Signs of instability are coloured as on NWAC's site**: red for avalanches (seen,
  triggered, someone caught), orange for collapsing and shooting cracks.
- **The Webcams tab's field photos are quicker to scan**: a one-line heading, one short
  line per report (place, day, distance), then its photos; the sources in a line at the
  bottom. "View all full screen" is gone: a photo opens the viewer.
- **The viewer's previous and next targets are the outer part of each side** of the
  photo, not only the small arrows.

### Fixed
- **The freezing level (and the snow level from it) is one height for the location.** It
  was found again at every band, and for models without a freezing level of their own
  (ECMWF, GEM) the column started at that band's temperature: at a band above the
  freezing level it skipped the air below the band, so the same model and hour read
  lower at the summit than at the base, often by several hundred metres (up to 1,700 m
  in the test captures). Every band now shows the same freezing level, worked out at the
  lowest band.
- **The map could go white in 3D on a phone** and stay that way until the app was
  closed. 3D terrain with overlays used more graphics memory than a phone allows (each
  terrain tile drew the map into a 2048 px texture, about 21 MB), so the browser dropped
  the map's graphics. Phones now draw those at 1024 px, a quarter of the memory (the
  base map and overlays have no more detail than that to give). When the graphics did
  come back, 3D terrain was drawn through the lost ones as grey and red smears; it is
  now rebuilt properly. If they don't come back, the map says so and offers **Reload
  map**, since an app on the home screen has no reload button.
- **Backcountry's recent observations could be empty while Webcams showed photos** for
  the same place, for up to an hour after an update (the browser reused the location's
  field reports from before the full list existed). It now falls back to the photo
  reports.
- **The photo viewer keeps the photo the focus** and its short line of text (place, who,
  day, distance, caption) well clear of the screen's rounded corners.
- **The worker gives memory back between jobs.** It held ~2 GB while idle (memory freed
  by jobs on several threads, kept by the C library for reuse). The image now limits
  glibc to two memory pools (`MALLOC_ARENA_MAX=2`), and the worker releases freed memory
  after every scheduled job.
- **Field photos follow the location more closely.** The Webcams tab shows the photos
  *near* the location first (within 20 km, and closer to it than to any other location,
  so Crystal gets Silver Basin and a Paradise location gets Paradise), then, folded, the
  others from the same avalanche zone within 60 km. Photos from other zones are no longer
  shown there (the Observed tab still lists every report within 60 km).
- **The worker runs under an init process** (`init: true`), which cleans up the
  processes headless Chromium leaves when it exits.
- **Compare's Locations button and snow total switch sit under the chart's card**, so the
  card holds just the chart, its timeline and its range.
- **Compare reads times on your own clock.** When the locations span time zones, the one
  in your time zone (or nearest it) sets the chart's times and days, rather than whichever
  forecast is freshest: from Washington, Pacific time, even with Banff in the comparison.
- **Compare holds four locations, every one a line.** It used to take eight with only four
  drawn; now what you pick is what the chart shows. Old links and groups with more open
  with the four they drew. The list of locations under the chart is gone (the cards above
  the chart say the same): a free card offers **Add location**, and **Locations** beside
  the time opens the list to add or take one out.
- **The snow total switch sits under Compare's chart** when it shows snow with the
  timeline: *From now* or *Timeline window* (the Settings switch, renamed from "From the
  first day shown").
- **Snow totals add up the same way on the forecast and Compare charts**, set in Settings
  → Snow total on charts: *From now* (the default, a running total, so lines keep their
  place as you move along the timeline) or *From the first day shown* (starting at zero
  where the chart starts, so each line ends at its total for those days).
- **Compare has a Timeline button**, as the forecast chart does, sharing its setting;
  the chart keeps its height with the timeline shown or hidden.

### Changed
- **Compare's day range and a timeline sit right under the chart.** The 1 / 3 / 5 / 10
  day buttons follow the chart directly, with a timeline above them as on a location's
  forecast: one column per day with a small bar of each drawn location's snow in its
  line's colour, and the chart's window raised across it. Drag the window, tap a day or
  step with ‹ ›. The location rows below still fade the days outside the chart, but no
  longer move it.
- **Compare's cloud cover is a line per location**, its percentage of the sky on a
  0–100 % scale, like the other metrics, instead of a grey strip per location.
- **Compare's location list is one line each**: the name (still the line's switch), its
  band and elevation, and its total for the days shown. The ten day cells under the
  chart are gone; they repeated the chart in a form that was harder to read.
- **Pick out one location on Compare**: tap its card above the chart to make its line
  stand out (the same look as pointing at it on a desktop); tap it again to clear it, or
  another to switch. On a desktop, pointing still picks a line out while the pointer is
  there, then the selection shows again; a click selects, as a tap does.

### Added
- **Share on Compare**: an image of the comparison as it's shown, the metric, band and
  days in view, each drawn location's number for those days in its colour, the chart at
  the same scale, and the selected location picked out.

### Added
- **Compare**, a new page and the third tab: the locations you choose on one chart, to see
  where conditions look best. Nothing is picked for you: tick up to 8 locations, then
  Compare. Up to 4 are drawn as solid lines, one per location in its own colour, each
  named by a card above the chart (its colour down the edge, name and value, and on wider
  screens its band and elevation; two by two on phones), so the plot keeps its full width.
  Tap a location's name to draw or hide its line; on a desktop, pointing at a location
  picks out its line. For snow (a running total over the days in
  view), temperature, wind gusts (with the lift-hold gust marked), freezing level (with a
  tick at each location's elevation, and how far above or below it the freezing level
  is), snow ratio, and cloud cover (a lane per location). Every location gets a row of ten
  days at the chosen band and a total for the days the chart shows; drag or tap the days
  to move the chart. One Base / Mid / Summit switch covers every location, and each one's
  real elevation is shown. Save a comparison as a group ("Washington touring") to open it
  again later; a group opens the way you left it and keeps your changes. Groups are kept
  in this browser; Copy link takes one to another device. The comparison is in the page's
  address, so a link opens it and Back undoes adding or removing a location. Plan:
  `docs/COMPARE-PLAN.md`.

### Changed
- **The tabs and the rail are in one order**: Overview · Map · Compare · Calendar ·
  Settings (the rail had Calendar before Map). The phone tab bar's icons-only width grows
  from 220 to 248 px for the fifth tab, and the map's buttons stay centred beside it.
- **Temperature moves smoothly, and its slider is finer up close.** The map now draws the
  Temperature layer itself from numbers, as it does the snow total: colours run smoothly
  (with a crisp break at 0 °C), the slider glides between forecast frames rather than
  jumping, and zoomed in each spot gets the temperature at its own height, pixel by pixel
  (this replaces the drape coloured from the map's centre). The slider is continuous
  with marks at now, 12 h, 1, 2, 3, 5, 7 and 10 days, evenly spaced, so the first days
  take most of it; Play moves along it at an even pace, so the near days pass slowly and
  the far ones quickly. The key is a smooth gradient to match. On the server each
  temperature frame is also written as numbers (~230 KB, ~12 MB for the 10 days, fetched
  nearest the slider first); browsers without WebGL 2 keep the pictures.

### Added
- **Temperature on the map**, in the Weather choices beside Snow level: the forecast 2 m
  temperature every 3 hours to 3½ days, then every 6 hours to 10 days, drawn over the whole
  box so it shows zoomed out like the snow level. It is adjusted to the terrain: each
  model's temperature is for its own smoothed ground (HRDPS and NBM 2.5 km, RDPS 10 km,
  GDPS 15 km), so the worker takes it to sea level from that ground at 6.5 °C a km and
  back up to the real ground's height under each pixel (Mapterhorn's elevation), giving
  cold ridges and warm valleys and a freezing line that follows the mountains. Zoomed in
  past 10, the terrain itself is coloured by height from the temperature at the map's
  centre, ridge by ridge, as the rain/snow line is. The key runs from −30 to 30 °C in
  2 °C bands, turning from ice blue to green at 0 °C. Tapping a spot gives its
  temperature at that spot's own height now and its range over the next three days. An
  estimate: cold air pooled in valleys (an inversion) isn't in it. On the server: about
  50 more frames per layers run (~2 MB of NBM temperature each, cached), and the model
  ground heights and a grid of elevation, fetched once and kept. The Layers sheet's
  weather tiles now sit five across, so the nine choices still take two rows.
- **Forecast clouds at their heights.** Zoomed in (from zoom 8), the Clouds layer's
  forecast knows where the cloud's top is (NOAA's National Blend of Models, to 36 h,
  across the US and Canada to about 55°N): the cloud covers everything beneath its top as
  one layer, a full deck as a full deck, and summits standing above it show through, under
  only any cloud higher up ("at cloud height" beside the time). Elsewhere and beyond, the
  cover alone as before; zoomed out it looks as it did. It stays on further in than
  before, lighter, so the ground under it still reads. On the server: ~180 MB more NOAA
  downloads and under a minute of work per NBM run (twice a day); the ground under the
  clouds is the Temperature layer's elevation grid.
- **3D clouds** (Layers → Show, off until chosen): puffs of cloud floating at their
  forecast heights around each location, for the time on the weather slider (or now):
  none when it's clear, clumps when partly cloudy, a deck when overcast. Ridges hide the
  clouds behind them and summits poke through a deck. They keep one look at every hour
  (white tops, grey undersides, darker for a thick deck), so scrubbing doesn't flicker.
  Best in 3D, and a rough picture rather than a measurement. Each
  location's cloud layers come from one light Open-Meteo request a run (~2.4 calls; a
  location now uses ~310 calls a day, so 25 still fit the free tier).
- **`config/webcams.yaml` applies itself.** The worker reads it at start (so after every
  update) and every 5 minutes, and gives each location whose entry is new or changed the
  file's webcams, then refreshes it. Merging a webcam change is all it takes; no command
  to run. Entries that didn't change leave their location alone, so webcams edited on
  the Manage page stay until that location's entry changes; the first time an entry is
  seen for a location that already has other webcams, those are kept. A listed location
  that doesn't exist yet gets its webcams once it is added. `snowwatch locations webcams`
  still applies the whole file at once.
- **A Base pill at the foot of the map**, beside Terrain and Weather: Topo, Satellite or
  Recent, with Recent's controls (colours, the view stepper) in its panel, as Radar has
  its timeline. On phones a tab with something chosen shows just that ("Satellite",
  "Snow total") and Measure is a ruler, so the row fits without scrolling; the map's
  buttons now sit above the row instead of beside it.
- **A Names switch** in the map's Show tiles turns the town, lake, river and park names
  over satellite imagery off (state and country lines stay).
- **Recent satellite reaches past the 24 km square.** Round each location the map now
  also shows the newest clear Sentinel-2 view of the 72 x 72 km area at 30 m, stitched
  and dated like the 10 m view, which stays on top in the middle. Beyond it, and where
  no pass in 60 days was clear, the daily 375 m mosaic still shows. The (i) says how far
  the 30 m view reaches and the dates of its passes. Set `map.sat_wide_km` (36 by
  default; 0 turns it off). On the server it about doubles the satellite job's first
  run (4–5 minutes more per location) and adds ~40 MB per location on disk; memory use
  doesn't change, and later refreshes only fetch new passes.
- **The Observed tab, redesigned to read at a glance.** It now opens with the simple
  answers. A sentence sums up the snow station ("18 cm of new snow in the last 3 days"),
  with how its depth moved this week and how many days thawed. Below that: the depth on
  the ground with a 30-day sparkline, new snow over 24 h, 72 h and 7 days, and the last
  seven days as cells tinted like the calendar, each with its high and low. Beside it,
  "Did the forecast get it right?" puts the forecast's total next to the measured one,
  with one sentence on how it leans. Under "In detail": the last 30 days as depth (or snow
  water), new snow and a new low/high temperature chart, on one time axis with a shared
  crosshair; the day-by-day forecast check, with a New snow / Precipitation toggle and
  three numbers (typical miss, lean, days scored) in place of long sentences; and snow by
  elevation, a chart of the nearby stations' depth against their height with this
  location's elevations drawn across it, plus the full table folded underneath. The
  explanations fold away into "How this is measured".
- **Links to the Sierra, Central Oregon and Utah avalanche centers' observations** on the
  Webcams tab (Palisades Tahoe, Mt. Bachelor, Snowbird), like NWAC's. Their photos can't
  be shown in the app: the first two use avalanche.org's observation API, which only
  answers the centers' own sites, and the Utah Avalanche Center's site turns automated
  visitors away.
- **Recent field photos on the Webcams tab.** Photos from Avalanche Canada's Mountain
  Information Network reports within 60 km of the location, last 14 days, by day: each
  report's title (linking to it), time, distance and region, then its photos with their
  captions (each opens large). A location with no webcams gets the tab when there are
  photos. The worker fetches a report's photos once, when it first appears. NWAC's
  observations can't be shown (avalanche.org's observation API only answers the
  centers' own sites), so locations with an NWAC forecast get a "Recent NWAC
  observations" link there instead, and the Webcams tab even without webcams.
- **Webcams are bigger, and can all play at once.** Cards are wider (two across on a
  desktop), a camera playing on its own spans the whole row (Crystal's 360° view is now
  usable), and a single camera always does. "Play all live" starts every camera's video
  at once, muted; the device remembers it and starts them by itself next time, until
  "Stop all". Off by default, since a page of live video is heavy on a phone's data.
- **Webcams get their own tab, with live video in the app.** A location with webcams
  shows a Webcams tab (after Observed; key 5) instead of a card at the foot of Forecast.
  Each camera shows its picture, refreshed every 5 minutes while the page is in view, and
  a camera with a live stream plays it in place on "Live", one camera at a time. On the
  Manage page, a webcam's new "Live video link" takes a YouTube, Brownrice, CamStreamer,
  Roundshot or Ozolio link (the video's page or its embed link) and stores it as that host's
  player. Only those hosts may be framed (a new `frame-src` in the CSP); other players
  still open on their own site. Nothing loads from a video host until Live is pressed.
  Saving a change to a location's webcams or links now refreshes its forecast, so they
  show a minute or two later rather than at the next scheduled run. How to find each
  host's link: docs/DEPLOYMENT.md → Webcams.
- **`snowwatch locations webcams`** sets many locations' webcams from a YAML file
  (`config/webcams.yaml` by default) without touching anything else about them, and
  refreshes them. `config/webcams.yaml` holds 81 cameras for the home installation's
  locations: resort cams, the NPS cams at Mount Rainier and Hurricane Ridge, WSDOT pass
  cams, and Timberline's cams with ODOT's on US 26 at Government Camp.
- **Ozolio** players (Revelstoke, Palisades Tahoe) play in the app too.
- **The snow total is picked on a slider**, like the radar, rather than a row of buttons,
  and it slides smoothly from 12 hours to 10 days ("Next 2½ days, to Fri 1 PM"): the
  server sends the total every 6 hours for two days, then every 12 and 24, and the map
  blends between them. The arrow keys step from window to window.
- **The snow total draws like the radar, flat and in 3D**: the numbers come once and the
  phone's graphics chip colours them, so the map pans, zooms and tilts without waiting.
  Zoomed in, the terrain adjustment (more snow on the peaks than in the valleys) is worked
  out on the phone from the elevation the map already has; it used to be tiles the server
  drew on request, slow to come, worst in 3D, and fetched again for every window.
- **Radar's blind spots filled from the forecast** (docs/RADAR-PLAN.md M3): where no
  radar sees the ground (behind ridges, high over far valleys, out of range), the radar
  and nowcast frames take the forecast for the same moment, drawn lighter and hatched.
  Where radar reaches comes from NOAA's MRMS radar quality index (to 55°N) and Environment
  Canada's coverage beyond. Layers → Weather → "Radar only" leaves them out; tapping the
  map says "from the forecast" there.
- **Taps beyond the West box read the wider radar** (M6): what's falling now and whether
  it starts or stops within the hour. Inside the box the tap panel shows the same line.

- **The forecast checked against the station's precipitation gauge**: the Observed
  tab charts each day's rain and melted snow in the gauge beside the forecast's water,
  and the Confidence tab scores every model on it. It works where the depth can't, on
  bare ground and in rain, and without the snow ratio, so it says whether the models had
  the amount right.
- **New snow scored as settled snow**: a depth sensor sees snow that has settled for up
  to a day, so the depth chart sets it beside the forecast's snow water at 8:1
  (`verify_settled_ratio`) rather than the fresh-snow ratio of the app's totals. Days
  the depth can't measure (no snowpack on the ground, or above freezing all day) are
  shaded and left out of its score; the gauge still scores them.
- **The forecast scored at the snow station's own elevation**: each run also asks the
  models for the station's own spot and elevation (scoring only: the base, mid and
  summit bands stay where they are), so a station below or beside mid-mountain is
  compared with a forecast for where it is. Once that has a week of days, the charts
  and summaries lead with it; the mid band's scores stay alongside.

### Fixed
- **Measured snow was a day early**: SNOTEL dates each daily depth by the day it ends
  (its 14 Nov depth is the reading at midnight going into the 15th), but the scorecard
  and the Observed tab took it as the day's opening reading. So each day's measured new
  snow showed on the day before, beside the wrong forecast, and every SNOTEL station's
  score looked worse than it was. Stored days move to the right date on upgrade.
- **3D terrain "walls"** (seen near Whistler): a short network hiccup switched the
  elevation tiles from Mapterhorn to the AWS tiles mid-visit, and the two disagree by
  20–60 m at a tile's edge, which shows in 3D as a wall with the map stretched down it.
  The switch now waits for a real outage (15 s of failures), a failed download is tried
  again rather than kept, and when the switch does happen every tile is loaded again
  from the one source.

### Changed
- **Recent satellite shows every location's views at once**, so neighbouring areas that
  touch or overlap read as one (the nearest location's on top, and 10 m always over
  30 m). The controls and the dated outlines are still for the nearest location.
- **The forecast updates every 3 hours**, up from every 6 (`schedule.runs_utc`: 00:30,
  03:30 … 21:30 UTC; the ensembles still come twice a day, at 09:30 and 21:30). The
  runs in between catch the hourly HRRR and NBM in the US and keep "now" and the last
  24 hours fresh. Open-Meteo use roughly doubles, to ~290 calls per location a day
  (`snowwatch budget` shows the total). The Confidence tab's trend takes one run per
  6 hours, so it still reaches back about as far and runs that repeat the same model
  data don't flatten it.
- **Calmer map labels.** Zoomed out, only the major cities are named (Seattle, Tacoma,
  Everett), then other cities from zoom 9, towns from 10, villages and hamlets from
  10.5-11. Peaks are shown by how far each is from a higher one, so zoomed out you see
  the big standalone peaks, and more as you zoom in (every named peak from zoom 14);
  where names collide the highest wins, and a peak shows no dot without its name.
  Rivers and creeks near your locations are named once along each stretch on screen
  instead of every few hundred pixels.
- **No county lines over satellite imagery, and more names.** Place names and borders
  over the Satellite and Recent satellite bases now come from OpenStreetMap and are
  drawn by the app instead of Esri's label pictures, so county lines are gone (state,
  province and country lines stay). More is named: smaller towns and hamlets a zoom
  sooner, national forests and wildernesses at every zoom, town parks and golf courses
  close in, lakes a zoom or two sooner, and rivers and creeks along their whole length
  near your locations (fetched weekly with the ski map). Compared view by view with the
  old labels, the only names lost are county names, one Whistler park OpenStreetMap
  doesn't have, and two Whistler village parks that now appear a little further in.
- **Tidier recent satellite.** The stitched newest-clear view no longer looks like a
  patchwork of boxes: cloud gaps are round rather than square, the parts' borders curve
  instead of following a 250 m grid, each part's gaps are filled from one or two passes
  rather than a scatter of them, and the joins between passes fade instead of being cut
  sharp. The 10 m views stay first: the 30 m view round them never changes which passes
  they use.
- **The Recent satellite bar leads with the dates.** Folded, it now starts with the span of
  the passes ("21 Oct–4 Nov", or "2–9 Nov" within a month) or a scene's day ("9 Nov · 9
  days ago · 92% clear"), so the dates show even on a phone where the line is cut short.
  "Newest clear view" and the satellite's name (Sentinel-2C) moved behind the (i).
- **Radar scrubs as fast as you can drag, flat and in 3D** (docs/RADAR-PLAN.md, part 1):
  - The server sends each radar and forecast frame as numbers (the rate, and how much
    is snow, mix or rain), and the phone's graphics chip colours them at the screen's own
    resolution. Every frame of the timeline is held there, so moving the slider is one
    draw: nothing is decoded or copied, and the map never stalls waiting on a frame.
  - The slider slides rather than steps: between two frames the map shows them blended,
    so storms move smoothly however slowly or quickly you drag, and playing is one
    continuous movement.
  - Frames load nearest the slider first, wherever it is dragged, and a frame that fails
    to load is tried again (it used to stay blank).
  - On phones the loop is held at half resolution and the frame you stop on is fetched
    sharp.
  - The same drawing flat and in 3D, and it comes back on its own after the phone drops
    the map's graphics.
- **No more jump between the nowcast and the forecast:**
  - The nowcast hands over to the forecast as it goes: its first frames are the radar
    moved on, its last are the forecast, and those between mix the two by the same
    moment. Tapping the map gives the same mix.
  - A forecast hour is placed at its middle, not its end, and none shows in the middle of
    the nowcast any more (the loop used to go nowcast, model, nowcast).
  - The radar is kept, not cleared, when no radar source answers.
- **One rule for which model draws where, at every lead time:** NOAA's models in the US
  and Canada's in Canada, blended across the border zone (48.5–49.5°N). For the first two
  days Washington, Idaho and Montana used to show Canada's HRDPS, then switch to NOAA's
  blend at 48 h; now they show NOAA's models (HRRR, then the National Blend) all along, as
  the snow totals, snow level and wind already did.

- **Radar beyond the West box.** Zoom out or pan away and the radar and nowcast carry on
  over most of North America (Alaska to the Gulf, the Pacific to the Atlantic coast), from a
  coarser loop (about 4–7 km a pixel, 0.7 MB in all) drawn beneath the West box's own and
  fetched only when the map looks past the box. It follows the slider by time and hides
  in the forecast (the models stay on the West box).
- **Deployment:** the worker's memory limit goes from 1.5 GB to 2.5 GB
  (`docker-compose.yml`): the map jobs now peak at about 470 MB (radar), 320 MB (wide
  radar), 570 MB (forecast), 550 MB (layers) and 400 MB (totals), and can overlap. The
  wide radar's first run waits 3 minutes after the worker starts.
- **Clouds: a forecast after the satellite loop.** The Clouds layer's slider now runs
  on past "now" to about 10 days ahead: the forecast's cloud cover, every 3 hours to
  3½ days, then every 6 hours, drawn as cloud (the thicker, the greyer). Canada's models
  (HRDPS, RDPS, then GDPS) in Canada and NOAA's National Blend in the US, blended across
  the border like the other layers.

- **Radar over the US is checked against NOAA's MRMS**, NOAA's own quality-controlled
  mosaic of the same radars: echoes it finds false (ground clutter, the beam striking a
  mountain, echoes that don't reach the ground) are left out, echoes it has that
  Environment Canada's composite missed are added, and it says rain or snow (Environment
  Canada's "mixed" stands). Canada keeps Environment Canada's own checks and types. Echoes
  found false scan after scan are remembered and left out of the nowcast too. On live
  scans (17 Nov 2026) about 13% of the US echo was removed and 7% added. The radar job
  peaks about 70 MB higher (MRMS is read straight from its PNG, not the 200 MB grid).

### Fixed
- **Snow total: a new window shows at once in 3D.** Choosing another window (7 days to
  10 days) used to leave the map blank, or showing the old window, until it was moved:
  the map took the new window's tiles for the old ones' drape. Each window is now a layer
  of its own; the old one stays until the new one's tiles are in, tiles that fail are
  asked for again, a spinner shows while a window loads, and the other windows' pictures
  load in the background. The server gives these tiles an allowance of their own, apart
  from the base map's.
- **Sun & shade: the last frames before sunset only get darker.** The final step used to
  switch the hill shading to another method and light direction and lay a full dark veil
  over the view, so the map looked completely different. Now the light keeps its
  direction and fades, and sunlit ground dims a little each step from about 8° above the
  horizon until it meets the shade as the sun sets.
- **No more "rain" on Mt. Rainier's summit on the radar.**
  - What it was: the radar beam strikes the mountain, which shows as a strong, unmoving
    echo. Environment Canada leaves it untyped, and the map used to call any untyped echo
    rain.
  - Now: an echo that no nearby radar type, and no forecast precipitation, explains is
    left out.
  - Real precipitation is still typed as before: by radar near it, or by the forecast.

- **The radar is reliable again.**
  - **Colours:** the server colours every frame, as before, and the map shows it as a
    picture, flat and in 3D alike. The map-side drawing that replaced this sometimes showed
    rain as snow (snow over Seattle in a forecast that said rain), and disagreed between
    flat and 3D.
  - **After switching apps:** the radar draws again when you come back to the app, rather
    than staying blank until a reload.
  - **Kept:** the smooth colours and soft edges, fades while playing, no fade while
    dragging the slider, and the gradual hand-over from the nowcast.
  - **No green wash:** nothing lighter than 0.1 mm/h is drawn (the nowcast's background
    of ~0.04 mm/h washed the West green).

### Changed
- **Smoother radar on the map.** Precipitation is now drawn the way the best weather apps
  draw it: storms with smooth, sharp outlines and colour running continuously inside, at
  any zoom, rather than six flat steps stretched into blurred pixels:
  - Radar arrives from Environment Canada as numbers rather than coloured bands, and the
    server sends the map numbers too.
  - The app smooths those numbers and colours them on the phone's graphics chip, at the
    screen's own resolution, for the part of the map on screen. Frames take less memory
    than the coloured pictures did, and draw in about 10 ms.
  - The model forecasts are smoothed where they used to show their grid cells, and the
    borders between snow, mix and rain follow the weather, not blocks.
  - Frames fade into one another as the radar plays or the slider moves (in 3D too), and
    steps through 6- and 12-minute radar more quickly than through hourly forecast.
  - The first two forecast hours fade from the last radar nowcast into the model, so the
    hand-over between the two is gradual; tapping the map gives the same mix.
  - The key shows each type's colours as a continuous strip.
- **The server sends far fewer bytes** (performance pass, part 5):
  - Forecasts, the overview, the radar timeline and the app's own code go out
    compressed: a location's forecast is about a sixth of its old size, the app's code
    under a third. Pictures are sent as before.
  - Snow-total tiles with no snow aren't stored any more: they're all the same clear
    picture.
- **3D terrain and overlay tiles no longer wait for the sun and wind layers**
  (performance pass, part 4; nothing the map shows changes):
  - The slow whole-view layers (Sun & shade, Wind effect, the concern index) work in a
    second background worker, started the first time one is opened, so elevation and
    slope tiles don't queue behind them.
  - Switching the overlay between slope, aspect and avalanche problems recolours the
    tiles already worked out instead of working them out again.
  - Panning back, nudging the map, or setting the date or wind back reuses the sun hours
    and wind effect already worked out for that view.
  - Downloads for tiles that have scrolled away are stopped, and a cancelled sun or wind
    picture stops within a fraction of a second.
- **The map fetches and draws less that you can't see** (performance pass, part 3;
  nothing it shows changes):
  - The Esri base map stops at the zoom where OpenTopoMap has covered it, and weather
    layers stop at the zoom where they have faded out, rather than being drawn invisibly.
  - Runs, stations, reports, ATES areas, avalanche zones and the measured line are cut
    into map tiles to zoom 12–14 and stretched beyond, rather than cut again at every
    zoom to 18.
  - Tapping a glacier or profiling a run reads the ski map's file the map already has,
    rather than downloading and keeping a second copy.
  - Leaving the map frees the terrain worker and the elevation tiles it holds; it starts
    again when you come back.
- **The map does less wasted work** (performance pass, part 2; nothing it shows changes):
  - Radar pictures and satellite tiles reach the map as soon as they arrive. They used
    to wait until a copy was written to the offline cache, which is now written in the
    background, pruned to two days, and cleared of radar frames the newest timeline no
    longer lists.
  - With no area saved for offline use, map tiles skip the service worker altogether.
  - The map's code starts downloading alongside the forecast list, and the map no longer
    waits for the contour library (contours appear when it arrives).
  - On phones, radar waits for Play instead of starting by itself.
  - Avalanche zones are sent to the map again only when they change (not every 5
    minutes), and so are stations, field reports and ATES areas (not on every switch or
    theme change).
  - Hovering over a measured line's profile moves only its dot.
  - Refreshes pause while the app is in the background, and catch up when it's back.
  - The Live Sky backdrop rests behind the full-screen map.
  - A radar frame asked for twice at once is decoded once; frame downloads stop when
    you leave the map.
- **Push alerts come as one digest per forecast update** instead of one notification
  per location. The title sums it up ("Powder at 3 spots: Alta 14 in Wed"), the body
  has a line per location (the top three, then "+2 more"), and each digest replaces
  the last one rather than piling up. A powder day inside a storm shows on the storm's
  line, and avalanche alerts found in the same run join the digest.
- **Fewer repeat alerts.** Powder days and storms alert once they're within 5 days
  (not 10). A flag that drops out and comes back within a day, or a storm whose start
  moves by a day, doesn't alert again; an event already sent alerts again only if it
  grows by half and at least 4 in (10 cm), or becomes a warning.
- **The Overview's share image fits any number of locations.** It is now a table: the
  day names once across the top, then a row per location with its name (on two lines
  when it's long), the week's bars and the total, with the type sized to the number of
  rows. Landscape images split into two columns past six locations. One image holds up
  to 12 locations, the snowiest 12 by default, and a **Locations** picker in the share
  sheet chooses which go in.
- **The Backcountry tab is reorganised around planning a tour**, top to bottom: the
  avalanche center's bulletin as published (each problem now has a small rose showing
  the aspects and elevations it lists, beside the ratings on wide screens); **Avalanche
  weather, day by day**, a new week-long outlook; **Where the wind is putting snow**
  (ridge wind now and at its strongest, summit snow, the two loading roses); and
  **Touring weather**, one table with a column per day for the sky above treeline,
  ridge wind, summit gusts and temperatures, the freezing level, the refreeze the night
  before at each elevation, and daylight (it replaces four separate cards).
- **New: Avalanche weather, day by day.** For today and the six days after it: the
  published danger on the days the bulletin covers, then what the weather does to the
  snowpack: new snow at the summit (and the 72 h total), sustained ridge wind and the
  slopes it loads, rain onto snow and how high it reaches, the freezing level and hours
  of thaw up top. Each factor and the day as a whole get a "weather stress" grade
  (Little, Some, Strong, Very strong) with a rising or easing arrow, and a sentence sums
  up the week ("Very strong weather stress Fri to Sun and Tue. Fri brings 11.8 in of new
  snow and S wind to 34 mph loading N slopes."). It is an estimate from the forecast,
  never a danger rating: it has its own words and colours (the map concern index's
  blues to magenta, never the danger scale's), and always says it can't see buried weak
  layers. The thresholds are in `config/forecast.yaml` (`backcountry: outlook_*`), and
  `HAZARD_INDEX=off` hides the grade and keeps the facts.
- **The Models tab is now Confidence**, built around one question: how sure is this
  forecast? For the next 5 days and days 6–10 it gives high, medium or low confidence
  with a sentence, the total and its likely range, and a line showing the range, the
  forecast and where each model stands. Below: **the models day by day** (a dot per
  model on each day with the ensemble range and the models' median, or the running
  totals as before) with a table of every model's numbers; **chance of at least** each
  amount as bars for both windows (replacing two step curves); **how the forecast has
  changed** in words ("Up 8.4 in since 4 runs ago") over the chart and table; and the
  **track record here**, which says how far off the app's forecast has been and which
  source has been closest. It follows the chosen elevation. The Base, mid and summit
  table moved to the Forecast tab.
- **The Observed tab measures more**: the snow station adds the last 7 days and a chart
  of new snow each day; **Measured against the forecast** charts each day's measured
  snow beside the forecast made the evening before and says how it leans; **Snow
  stations nearby** lists every station within about 37 mi, highest first, with the
  location's own elevations slotted between them, so you can see how deep the snow is
  at each height; and **Field reports nearby** lists recent Mountain Information Network
  reports (in Canada, or wherever one is close). New endpoint:
  `/api/locations/{id}/nearby`, read from the map's own station and report files.
- **The map's buttons on phones are easier to reach one-handed.** They're bigger
  (48 px) and centred in the gap between the tab bar and the edge of the screen. Layers,
  the most used, sits on its own level with the tab bar, the easiest spot for a thumb,
  and stays there while its sheet is open, so the same button closes it. The others
  (location, 3D, More, the compass) stand in a column above it.
- **The Layers sheet goes away with a swipe down** anywhere on it (it follows the
  finger, and springs back from a short pull), as well as with the Layers button, a tap
  on the map, or its ✕. A small handle at its top shows it can be swiped.
- **The full screen chart has no blank space, and its controls are bigger.** The metric
  cards are taller, with a line of detail under each value ("94% chance", "gusts
  14 mph"); the timeline is taller, with each day's snow over its bar; the cloud cover and
  chance of precipitation panel is taller, so its scale is readable; the range and view
  buttons are taller, and sit a little higher on a tall phone. The plot takes what's
  left, so it's shorter than before. Under the "All" view's last lane, only the day names
  show (the dates were hidden behind the timeline).
- **The map's More menu opens upwards** from its button, clear of the row of tabs at
  the foot of the map, instead of down over it.
- **Snow totals use the temperature-based snow ratio.** The headline depth is the snow
  water times a ratio from the temperature while it snows (8:1 near freezing, 11, 14,
  up to 17:1 in the cold) instead of the models' fixed 7:1, which under-read every storm
  colder than about −0.5 °C by up to 2.4×. Everything follows it: the bars and totals,
  the ensemble ranges, each model's bar, Model agreement, the past 24 h, Plan a day and
  the ski-day rating, the Backcountry storm, flags and push alerts, the overview and the
  Calendar, so they match each other and the map's snow totals. The period details show
  "at 14:1 · Light" under the big number and the models' 7:1 figure below; the forecast
  scorecard marks which consensus the app's totals use. The trend chart reads the
  matching stored consensus, so there is no step on the switch day. (`depth_method: slr`
  in `config/forecast.yaml`; `raw` goes back.)
- **The map's Layers sheet is redesigned**: every choice is a tile of the same size in a
  well, the chosen one raised (as the app's other switches), with "None" first in Weather
  and Terrain and the features shown as toggle tiles; shorter names ("Huts & passes",
  "Avy zones", Concern with a "beta" tag); hill shading beside the base maps; and each
  section's (i) says in one line what the chosen option is. No label is ever cut short
  (a long one takes two lines; the narrowest phones get three tiles across). It fits a
  375 × 667 phone without scrolling, as a sheet above the tab bar.
- **"This spot" and the other map panels share the overview's look**: big numbers in
  tiles (elevation, slope and aspect; forecast snow for 24 hours, 3 days and 7 days),
  snow by height as little bars like the overview's days, label-and-value rows divided
  like its list, the avalanche rating as the usual danger pill, and the chips as a
  segmented well. Glaciers and snow stations use the same tiles.
- **The controls at the foot of the map cover less of it, on every screen.** One row of
  tabs, Terrain and Weather always there (Satellite and Measure while in use), each
  saying what it shows ("Terrain · Slope", "Weather · Off"); at most one is open above
  it. An open one starts with a row of its types, None first, so a layer can be changed
  or turned off right there, then that type's own controls (the radar player, sun and
  shade, the avalanche problems). Choosing a layer opens its controls; a tap on the open
  tab folds it, leaving just the row. The open tab is remembered in this browser. The
  Recent satellite controls are one row, with the longer story behind an (i).
- **Phones and tablets: the map's buttons are at the bottom right**, under the thumb,
  the lowest level with the row of tabs at the foot (just above the tab bar), rising
  above a control when one opens: Layers lowest, then your location, 3D and a More menu (Measure, Offline maps, About this
  map), with the compass on top. The zoom buttons are gone there (pinch, or double tap),
  leaving the top of the map clear. Desktop keeps its column at the top left.
- **Desktop: with the rail folded, its button heads the map's column of buttons**, the
  same size, with the zoom and the rest stacked under it.
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
- **The map's memory is measured on every change.** A new browser test (`e2e/perf.spec.ts`)
  opens the map on the phone profile with radar playing, pans and zooms with the slope
  overlay on, then turns on 3D, and records each browser process's memory, the JS heap,
  and how long the map and its first radar frame take to appear. It fails if the page's
  own process passes 520 MB (today ~430 MB at its peak; the aim is 300 MB). The e2e server
  now serves a day of generated precipitation frames, so the timeline plays in tests.
- **Full screen forecast chart on phones and tablets**: an expand button opens the chart
  over the whole screen (the browser's own full screen where it offers one, as on
  Android; edge to edge on iPhone), clear of the notch and the rounded corners, with
  nothing to scroll: the place at the top, the chart, the cloud cover and chance of
  precipitation under it, the metrics as one row of chips, the day timeline, and the
  range (1–10 days) and the view in a bar at the foot, under the thumb. "All" stacks
  every measure on one time axis (snow and rain, temperature, wind, cloud cover,
  freezing level and snow ratio; three by two with the phone on its side, where the
  range and view move up beside the title); reading any of them reads them all, each
  lane saying its value at that time. It opens and closes where the chart in the page
  is, and follows the phone's turn rather than forcing one. In the page, a touch on the
  chart picks sideways (read it) or up and down (scroll) after its first few pixels.
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
