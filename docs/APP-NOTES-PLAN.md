# Snow Watch: app-notes plan (bugs, map UX, layout stability, snow ratio, live sky)

## Context

The owner's notes list ~20 bugs and improvements across desktop and phone. This plan
sorts them into six milestones, gives the root cause found in the code for each, and
the fix. Each milestone is independent and can be handed to an implementer on its own
(order matters only where noted). Decisions already made by the owner:

- **Snow ratio**: the headline becomes the temperature-based depth (M5).
- **Calendar**: fails with the app's error page ("Something went wrong"), and reload
  doesn't help.
- **Conditions pill**: clipped on desktop, on phone, and on phone when stuck.

Rule that applies to every milestone (the owner's "General" note): **controls never
move**. No control may change size or position because of its own state (selected,
loading, 1 vs 2 lines of text) or because a neighbour appeared. Reserve space, fix
heights, truncate text with an ellipsis and a `title`, and animate anything that must
move.

Root causes below were found by reading the code; nothing was run (plan mode, and
`frontend/node_modules` isn't installed). Items marked **verify first** need a
30-second reproduction before the fix.

Paths are relative to `frontend/src/` unless they start with `backend/`.

---

## Milestone 1: Bugs that break things

### 1.1 Calendar shows the error page

- **Cause**: `lib/stormcycles.ts` `stormCycles()` merges storms whose dates overlap
  into one cycle, but a location can have **two** storms in the same cycle (A: Mon–Tue,
  B: Mon–Fri, A again: Thu–Fri all merge). `cycle.locations` then holds location A
  twice. The lists are keyed by location id: `routes/calendar/+page.svelte`
  (`{#each s.locations.slice(1, 3) as l, i (l.id)}`, and `slice(0, 3)` on desktop),
  `lib/components/StormSheet.svelte` (`{#each lines as { s, cells } (s.id)}`), and
  `routes/+page.svelte` (`s.top ... (l.id)`). Svelte 5 throws `each_key_duplicate`,
  the route's `+error.svelte` shows, and it stays until the forecast changes.
- **Fix**: in `stormCycles()`, after grouping, fold each cycle's entries by location
  id into one `LocationStorm` (earliest `start`, latest `end`, summed `total_cm`,
  `wet` if any). Then sort by total as now.
- **Tests**: add the A/B/A case to `lib/stormcycles.test.ts` (one entry per location,
  totals summed). **Verify first**: build that case as overview rows and confirm the
  page throws before the fix.
- **Also**: there is no `hooks.client.ts`. Add one with `handleError` that
  `console.error`s the error and returns `{ message }`, and have `+error.svelte` show
  the message in small faint text, so the next crash names itself.

### 1.2 Current-conditions pill is cut off (desktop, phone, phone stuck)

- **Cause** (`routes/location/[id]/+page.svelte`, `.pill`): it is `inline-flex` with
  `white-space: nowrap; overflow: hidden; max-width: 100%`. `text-overflow: ellipsis`
  does nothing on a flex container, so whenever the pill is narrower than its text the
  end is hard-clipped. Desktop: `.title { min-width: 0 }` in the wrapping `.lhead`
  lets it shrink. Phone: `.mrow .pill` sets `overflow: visible`, so the text runs past
  the glass background and is clipped by the row/viewport, worst when `.mrow.stuck`.
  **Verify first** at 320, 375 and 1100–1200 px with the longest labels
  ("Rain and snow", "Partly cloudy", a long region name).
- **Fix**: wrap the text in one `<span class="ptxt">` with
  `min-width: 0; overflow: hidden; text-overflow: ellipsis`, and keep the temperature
  in its own non-shrinking span so the number is never the part lost.
  - Phone: pill `flex: 1 1 auto; min-width: 0`, elevation buttons `flex: 0 0 auto`;
    one row always, no wrapping (which also stops the sticky row changing height).
  - Desktop: put "updated …" in a second, faint pill/line of its own (it is the part
    that overflows) so the first reads "Region · Sky now".
- Apply the same span pattern to the Calendar's `.sub` pill.

### 1.3 Satellite colour shifts from dark to light when zooming in

- **Cause** (most likely): the hill-shading layer over imagery. `lib/map/style.ts`
  `shadePaint()` uses a constant `hillshade-exaggeration` (0.45 on satellite) with a
  dark shadow colour. MapLibre's hillshade steepens slopes at low zoom and relaxes
  toward zoom 15, so the same setting darkens the picture zoomed out and barely
  touches it zoomed in. Recent satellite already switches shading off for this reason.
  Second contributor: Esri World Imagery uses different imagery per zoom band.
- **Verify first**: on Satellite, set Hill shading to Off and zoom 8 → 15. If the
  shift goes, it's the shading; what remains is Esri's imagery.
- **Fix**: make `hillshade-exaggeration` a zoom expression for imagery bases
  (about 0.12 at z7, 0.25 at z11, 0.45 at z14+, tuned by eye so tone is even), and
  lighten the shadow colour on satellite. Keep topo as is. `setShade()` in
  `lib/map/layers/terrain.ts` already re-applies the paint.

### 1.4 Avalanche danger zones tint the map when zoomed in

- **Cause**: `lib/map/layers/avalanche.ts` `ZONE_FILL` opacity is
  `5 → 0.42, 9 → 0.28, 12 → 0.08` and never reaches 0.
- **Fix**: fill `5 → 0.42, 8 → 0.3, 10 → 0.12, 11 → 0`; keep the outline
  (`ZONE_LINE`) at every zoom so the boundary and the tap target remain. Update the
  Layers hint to "Colour when zoomed out; outline up close".

---

## Milestone 2: A shell that doesn't move (rail, layout, "View on map")

### 2.1 Rail jumps between Map and other tabs

- **Cause** (`routes/+layout.svelte`): off the map the rail is `position: sticky`
  inside a centred `max-width: 1460px` flex row with `padding: 14px 20px` (so its left
  edge is 20 px, or more on wide windows where the row is centred). On the map
  `.overmap .rail` becomes `position: fixed; left: 14px`, with a different background
  and shadow. Same element, two places.
- **Fix**: on desktop the rail is **always** `position: fixed; top: 14px; left: 14px;
  width: 248px`. `.app.withrail` drops the centring flex layout and gives `.col`
  `margin-left: 282px` (0 on the map page) with its existing `max-width: 1140px`. Only
  what legitimately differs animates: background density and shadow (transition
  ~300 ms). The fold button stays map-only; fade it in rather than inserting it into
  the layout (reserve its 32 px in `.brandrow` always).
- Keep `RAIL_OPEN_INSET` / `RAIL_FOLDED_INSET` in `lib/railui.svelte.ts` in step
  (they stay 272 / 68 with left 14).
- Fold/unfold: animate the rail's `transform`/opacity (the map side already eases
  via `--ease-slide`), instead of swapping `{#if folded}` blocks instantly.

### 2.2 Location sections drop down inside the rail list

- **Cause**: `.secs` (Forecast, Models, Backcountry, Observed) renders inside the open
  location's `<li>`, pushing every location below it down ~150 px.
- **Fix**: remove `.secs` from the list. Show the sections as the page's own tab strip
  on desktop too: `routes/location/[id]/+page.svelte` already renders `.tabs` for
  non-desktop from the same `sections` store; drop the `!viewport.desktop` condition
  and style it as a glass segmented control under the header. The rail list then never
  changes height; the open location is marked by the existing `.open` highlight.
  Keep `[` / `]` and add `1`–`4` for sections.

### 2.3 "View on map" from a location

- Add a "Map" button in the location header (desktop `.lhead`, phone `.mhead`)
  linking to `/map?loc=<id>`.
- `routes/map/+page.svelte` passes the param to `MapView` as `focus`;
  `lib/components/MapView.svelte` `draw()` uses it instead of `HOME_BOUNDS` on first
  fit: `jumpTo` centre `[lon, lat]`, zoom 11.5, flat (don't force 3D), and open that
  location's marker popup. Reuse the row lookup in `flyTo()`.
- The marker popup's "Open forecast →" already gives the way back.

### 2.4 Layout-stability sweep (the "General" rule)

- `lib/theme.css` `.seg button[aria-pressed='true'] { font-weight: 600 }` makes the
  selected button wider than the others, so wrapping rows reflow. Fix once, globally:
  reserve bold width with a hidden pseudo-element
  (`button::after { content: attr(data-label); font-weight: 600; height: 0;
  visibility: hidden; display: block }`) or switch selection to colour/background
  only. Same for `.railnav a[aria-current]`, `.locs li.open .loc`, `.tabbar a`.
- Phone tab bar (`.tabbar.compact`) shrinks while scrolling: keep (it's animated),
  but confirm it never changes height on the map page, where the dock sits on it.
- Banners in `.col` (update / offline / stale) push the page down when they appear:
  render them as a fixed toast at the top on all pages, as `.overmap .banner` does.

---

## Milestone 3: Map taps: one panel, one place, the right content

### 3.1 Windows open in different places

- **Cause**: the Inspector renders inside `.top` (centred column, `top: 10px`);
  `StationSheet`, `ReportSheet` and `ZoneSheet` are each `position: absolute;
  top: 56px; left: inset + 60px`; Layers and About sit at `top: 136px`, Offline at 112.
- **Fix**: one `lib/map/MapPanel.svelte` shell (title, kind label, close button,
  scrolling body, fixed header) used by Inspector, station, report and zone.
  - Desktop: docked to the **right** edge, `top: 10px; right: 10px; width: 360px;
    max-height: calc(100% - 20px)`. Move the terrain `Legend` (now top-right) to sit
    left of it, or into the dock.
  - Phone: a bottom sheet in a fixed position above the tab bar with two heights (peek
    ~35%, full ~80%) and a drag handle; while it's open the dock controls collapse
    (see 4.3) so they don't stack.
  - Feed the panel's size into `mapPadding()` (add `right`, and the sheet's height to
    `bottom`) so the tapped point stays visible.

### 3.2 A tap always opens "This spot"

- **Cause**: `map.on('click')` in `MapView.svelte` special-cases stations and reports
  only, then always calls `inspect()`; glaciers, huts, runs, ATES and zones appear as
  small `here` rows inside the spot panel, and a zone's bulletin is two taps deep.
- **Fix**: resolve the tap to a ranked list of **targets**, most specific first:
  station → field report → hut/trailhead/pass → run/route → glacier → ATES polygon →
  avalanche zone (only when the Zones feature or an avalanche overlay is on) → the
  spot's terrain and weather.
  - The panel opens on the first target, with a chip row at the top listing the
    others ("Glacier · Zone · This spot"); chips switch content in place, so the
    panel never moves. "This spot" is always the last chip, so terrain numbers stay
    one tap away.
  - Extend `lib/map/here.ts` (`hereItems`, `HERE_LAYERS`) to return these targets;
    add the zone via the existing `zoneAt()`. Give glaciers and places real content
    (name, type, elevation, area from the polygon; OSM link).
  - Start `inspect()` lazily: only when the spot chip is shown (it costs a worker call
    and a `/api/map/point` request).
  - Long-press (phone) / right-click (desktop) goes straight to "This spot".

### 3.3 "This spot" is messy

- **Cause** (`lib/map/Inspector.svelte`): ~12 wrapping label/value rows in a
  340 px box, three different caption paragraphs, and long formulas inline (the
  concern arithmetic, "at this spot's height, adjusted to terrain. The model's
  area: …").
- **Fix**: three titled sections in a fixed order, each a two-column grid (label
  column fixed, value right-aligned, tabular numbers), one line per row:
  1. **Terrain**: the three big numbers (elevation, slope with its colour chip, aspect),
     then sun and wind effect.
  2. **Snow & weather**: a small 3-column table (24 h / 3 days / 7 days) with a row
     for "here" and, when adjusted, a faint row for "area"; the 48 h strip full
     width; snow level, wind, on the ground, fell.
  3. **Avalanche**: band rating and zone link; concern class with its formula behind
     a "How?" disclosure.
  - Fixed-height skeleton rows while terrain and weather load, so nothing shifts when
    they arrive.
  - All caveats collapse into one "About these numbers" disclosure at the foot;
    coordinates become a tap-to-copy line in the header.

---

## Milestone 4: Layers and the dock

### 4.1 Layers sheet redesign (`lib/map/LayersSheet.svelte`)

- **Causes**: Weather appends `None` last while Terrain puts it first; `.seg` is a
  wrapping flex row with `border-radius: 999px`, so on 2–3 rows the track's huge
  corners cut behind the text ("the circle doesn't cover the text"); bold-on-select
  changes widths so "Sun & shade" hops rows; features are 18 px checkboxes; four
  paragraphs of description are always shown (7 lines under Terrain on a phone).
- **Fix**:
  - Options become a **grid of equal tiles** (`grid-template-columns: repeat(3, 1fr)`
    on phones, 4 on desktop; fixed 44 px height; `border-radius: 12px`; label centred,
    ellipsis). Selection is colour only. `None` is always the **first** tile in
    Weather and Terrain.
  - "Show" features become toggle tiles of the same size (`aria-pressed` buttons),
    with their hint as the `title`.
  - Shorten labels: "Avalanche problems" → "Avy problems", "Concern index
    (experimental)" → "Concern" with a small "beta" tag, "Huts, trailheads, passes" →
    "Huts & passes", "Ski runs and routes" → "Runs", "Avalanche danger zones" →
    "Avy zones".
  - Descriptions move behind an (i) button per section (one line shown only for the
    selected option); the long text already exists in the About panel.
  - Target: the whole sheet visible without scrolling at 375 × 667.

### 4.2 Pin Layers on desktop, and quick terrain buttons

- Add a pin button in the sheet header (desktop only), remembered as `sw.layersPinned`
  in `lib/prefs.svelte.ts`. Pinned, it docks to the left beside the tool column and a
  tap on the map no longer closes it (the click handler's `panel !== 'none'` early
  return must skip a pinned panel, so taps still inspect). It shares the map padding
  logic with 3.1.
- Desktop only: a compact Terrain row in the dock above the timeline (None, Slope,
  Aspect, Elevation, Sun, Wind, Avy), mirroring the weather modes row in
  `lib/map/Timeline.svelte`. Not on phones.

### 4.3 Too many bottom bars on phones (Recent satellite + forecast)

- **Cause**: `.dock` in `MapView.svelte` stacks up to five full controls (Measure,
  `SatControls`, `AvalancheControls`, `TerrainControls`, `Timeline`), each with its own
  rows, above the tab bar. `SatControls` alone is three rows with ~4 lines of text.
- **Fix**:
  - **One expanded control at a time on phones.** Each dock control gets a collapsed
    one-line form (~40 px: icon, one status phrase, chevron). The last one touched is
    expanded; the rest collapse. Desktop keeps them stacked.
  - `lib/map/SatControls.svelte`: one row: bands toggle, the short status
    ("Nov 11 · 2 days ago", ellipsis), the ‹ n/m › stepper, and an (i). The
    explanatory `foot` text and the cloudy note move into the (i) popover.
  - `Timeline.svelte` on phones: hide the weather modes row (it duplicates Layers) and
    put the key (`.foot`) behind the collapsed form.
  - Give each control a fixed height per form so `applyPadding()` stops nudging the
    map when text changes.

### 4.4 Full-screen forecast chart on phones

- **Cause**: `lib/charts/ForecastChart.svelte` `.plot` is `touch-action: pan-y`, so a
  slightly diagonal scrub scrolls the page.
- **Fix**: an expand button in the chart header (phones and tablets) opens the chart
  in a full-window overlay (reuse `lib/modal.ts` for focus and Escape): the same
  component with a new `fullscreen` prop, `touch-action: none`, plot height filling
  the window, range and metric chips kept. Ask for landscape with
  `screen.orientation.lock('landscape')` when available (ignore failure). Use a CSS
  overlay, not the Fullscreen API (unavailable for elements on iPhone).
- In the normal view, lock scroll direction after the first ~8 px of movement
  (horizontal → scrub and `preventDefault`, vertical → let the page scroll).

---

## Milestone 5: Snow totals use the temperature-based ratio

- **What the two numbers are**: the headline is snow water × a fixed 0.7 cm/mm (7:1,
  the convention of the model data source). The second is snow water × a ratio from
  the temperature while it snows (`config/forecast.yaml` `slr_bands`: 8:1 wet, 11,
  14, 17:1 dry). 7:1 under-reports every storm colder than about −0.5 °C, by up to
  2.4×. The map's snow totals already use temperature ratios, so map and location
  pages disagree today.
- **Decision**: headline = temperature-based. `depth_method: slr` exists but is only
  half-wired, so flipping it alone would make the page inconsistent.
- **Backend** (`backend/snowwatch/analysis/build.py`; grep `snowfall_cm_per_mm`,
  `headline_slr`):
  - Already honoured: `PeriodOut.snow_cm`, `WindowOut.snow_cm`, `hourly.snow_cm`.
  - **Not** honoured, fix each to follow `depth_method`: `WindowOut.ens` and
    `members_cm` (always raw; use the `_slr` ones as the headline), per-period `ens`,
    per-model `models` and `blend_cm`, the daily rows behind Model agreement
    (`_daily`, line ~849), the trend/run history, `last24_cm`, flags and alert
    thresholds, the ski-day rating inputs (`skiday.rate`), the overview row
    (`next5_cm`, p10/p90, `periods[].snow_cm`) and push notifications (`push.py`).
    Simplest shape: compute one "headline depth" helper and route every depth through
    it, keeping `*_raw` fields for the detail view.
  - Verification (`verify.py`): keep scoring both `cons` and `cons_slr`.
  - Set `depth_method: slr` in `config/forecast.yaml`; note it in `docs/ARCHITECTURE.md`,
    `docs/DEPLOYMENT.md` and the changelog. Stored runs made under 7:1 will show a
    step in trend charts on the switch day: rebuild recent runs with
    `snowwatch rebuild`, or mark the switch on the trend chart.
- **Frontend**:
  - `lib/charts/PeriodSheet.svelte`: big number = headline; the line under it becomes
    "at 14:1 · Light" and, in the details, "Model snowfall at 7:1: X". Replace the
    footnote ("uses a fixed 7:1…") with one sentence on how the ratio is chosen.
  - `routes/location/[id]/+page.svelte` `aboutCard`: drop the "would be" sentence;
    say the totals use the temperature-based ratio.
  - `lib/observed/Scorecard.svelte`: label which method is the headline.
  - Regenerate `lib/types.gen.ts` / `api-schema.json` (`npm run types`) if fields move.
- **Tests**: extend `backend/tests/test_flags.py`, `test_api_locations.py` and the
  build tests so that with `depth_method: slr` every surfaced total equals the sum of
  its periods' headline values (one invariant test over a fixture snapshot).

---

## Milestone 6: A sky that follows the weather and the clock

- **Causes** (`lib/sky.ts`, `lib/skystate.svelte.ts`, `lib/components/Sky.svelte`):
  - The scene is worked out **once**, when the snapshot loads (`skyOf(snap)` in the
    layout and the location page). Nothing re-evaluates as the hour changes, so an
    open tab never goes from day to dusk to night.
  - Time of day is a boolean: `night` only replaces clear/partly; every other scene
    gets a 40% "dusk veil". Dawn/dusk (`glow`) only happens within 75 min of sunrise
    or sunset **and** only when clear or partly cloudy.
  - In light mode the palettes are pale and nearly alike (overcast, snow, mixed, rain
    and fog are all light grey-blue; "night" is lavender `#7f88d8`), so scenes differ
    little. Colour mode is tied to the app theme, not the hour.
  - Only snow animates (`flakes`); rain, wind and storms have no motion, and the
    fixed themes turn weather off entirely.
  - Most of the sky is behind large panels with a 34 px blur.
- **Fix**:
  - **Two axes instead of ten scenes**: `weather` (clear, partly, overcast, fog,
    drizzle, rain, storm, mixed, snow, heavy snow, blowing snow) × a continuous
    `phase` from the sun's position (night, dawn, day, golden hour, dusk), computed
    from `snap.sun` sunrise/sunset. Sky colours interpolate along `phase` for every
    weather type; a snowy dusk is dark blue-grey, not pale.
  - **Tick**: a store interval (every 60 s, paused when the tab is hidden)
    re-evaluates the current hour and phase; refetch the snapshot when its hour index
    runs past the data. The existing 900 ms crossfade handles transitions.
  - **Motion** (only with Motion: Full, and never under reduced motion): rain streaks
    (angle and speed from wind), snow drift scaled by wind speed, cloud speed from
    wind, occasional lightning flash for thunderstorm weather codes (95–99), stars
    and a moon at night, sun position along an arc by time of day. Draw particles on
    one `<canvas>` instead of 60 DOM nodes.
  - **Visibility**: let the sky show in a taller band behind the page header on
    location and overview pages, and tint glass panels slightly with the scene's key
    colour, so the weather reads even with content on top.
  - Night scenes need readable text: when `phase` is night/dusk and the theme is
    Auto, switch to dark mode (leave explicit Light/Dark alone).
  - Add the scenes to `lib/sky.test.ts` (phase from sunrise/sunset; weather from
    codes, wind, precipitation), and a Settings preview that steps through them.

---

## Suggested order

M1 (small, fixes a broken page) → M2 → M3 → M4 → M5 → M6. M3 and M4 both touch
`MapView.svelte` and the dock/padding code; do them in that order. M5 is backend-led
and independent. M6 is independent and the most open-ended.

## Verification (every milestone)

- `cd frontend && npm ci && npm run check && npm run lint && npm test`
- `cd backend && uv run pytest` (M5; also anything touching the API schema)
- `npm run e2e -- --trace off` (starts `e2e/serve.sh`: API + built frontend on fixtures,
  no network). Add e2e cases for: Calendar renders with a twice-storming location
  (M1); rail's bounding box is identical on `/`, `/calendar` and `/map` (M2); a tap on
  a station, a glacier and bare ground all open a panel at the same rect (M3); Layers
  sheet has no vertical scroll at 375 × 667 and tiles keep their rects when selected
  (M4).
- Screenshots with Playwright at 375 × 667, 820 × 1180 and 1440 × 900, light and
  dark, for each changed surface; compare before/after for moved controls.
- M5: for one fixture location, check next-5-day total = sum of its periods, on the
  overview, calendar, location page and period sheet.
