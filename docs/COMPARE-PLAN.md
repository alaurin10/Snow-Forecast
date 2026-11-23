# Snow Watch: Compare plan (conditions side by side across locations)

## Context

The use case: it's Friday evening and you're choosing where to ski this weekend. The
questions are the same every time:

1. Where will there be the most new snow by the time I get there?
2. Will it be snow or rain at the height I'll ski?
3. How dry will it be (snow ratio)?
4. Will I see anything (cloud), and will the lifts run (wind)?
5. How cold will it be?

Today the app answers question 1 across locations (Overview: 7 days of snow at mid;
Calendar: 10 days of snow as a heat grid). Questions 2–5 can only be answered one
location at a time, by flipping between location pages and remembering numbers.
Compare puts the locations you choose on one chart, for any metric, at the same
elevation band.

**History.** The original plan had "Compare" and replaced it with "Plan a day"
(`docs/history/PLAN.md`, decision 10): every location for one date, plus "stack the
day/night bars of 2–4 locations on one scale". The API for it still exists
(`GET /api/plan`, mid band only), but there is no page for it. This plan brings back the
chart side and keeps the 2–4 limit, for the reasons in section 4.

**Rules this has to keep** (from `docs/REDESIGN.md` and `docs/ARCHITECTURE.md`):

- Calm, not a dashboard: one column, few controls on the page.
- One y-axis per chart. No mark outside the plot (tested). Works at 380 px with a thumb.
- Units are converted in the browser; the API serves metric only.
- Data colours (snow blue, rain green …) mean the same thing everywhere.
- Controls never move because of their own state or a neighbour's (APP-NOTES-PLAN).
- No prose and no AI: rule-based facts only. Never a "go here" verdict.

**Facts measured for this plan** (fixtures `live-20261104`, rebuilt locally):

- A snapshot is about 27 KB gzipped (175–183 KB raw): 240 hourly steps × 3 bands, with
  every metric Compare needs (`snow_cm`, `rain_mm`, `temp_c` and its model range,
  `wind_kmh`, `gust_kmh`, `wdir`, `cloud`, `cloud_low/mid/high`, `fl_m` and its range,
  `slr`, `pop`). Four snapshots are about 110 KB, and `getSnapshot()` already caches
  them (and the service worker keeps them for offline use).
- Hourly times carry their UTC offset (`2026-11-04T15:00-06:00`), so series from
  different time zones can be lined up exactly. Sunshine is an hour ahead of the
  Washington and BC locations.
- The bands' elevations differ a lot between locations:

  | Location | Base | Mid | Summit |
  |---|---|---|---|
  | Revelstoke | 512 m | 1,500 m | 2,225 m |
  | Whistler | 675 m | 1,850 m | 2,182 m |
  | Snoqualmie | 914 m | 1,150 m | 1,652 m |
  | Crystal | 1,341 m | 1,800 m | 2,095 m |
  | Rainy Pass | 1,480 m | 1,890 m | 2,124 m |
  | Sunshine | 1,658 m | 2,160 m | 2,730 m |

  Sunshine's base is higher than Snoqualmie's summit.
- The ski-day rating (`snapshot.days`) exists for resorts only, at mid. Backcountry
  locations have `rating: null`.

Paths are relative to `frontend/src/` unless they start with `backend/` or `docs/`.

---

## Decisions at a glance

| Question | Recommendation | Why, in one line |
|---|---|---|
| Where does it live? | A new **Compare** page (`/compare`), a fifth item in the tab bar and rail, with a "Compare" button on each location page | Comparing is a job of its own, with its own controls and data; it doesn't fit inside a page about one location or the glanceable Overview |
| Overlay or separate charts? | **Overlay lines** for continuous metrics (snow total, temperature, wind, freezing level, ratio); **one lane per location** for cloud and precipitation type | Lines overlay cleanly; cloud cover and snow/rain don't, they turn into spaghetti |
| Which elevation? | **Relative bands** (Base / Mid / Summit), one switch for all, with each location's real elevation shown everywhere | It's where you'd actually ski, and it uses the numbers the app really computes. A fixed height would mean inventing data |
| How many locations? | **Up to 4** (3 picked to start with) | Only 3 of the app's colours stay distinct for every pair; a 4th needs a new colour and a dash pattern; 5+ can't be told apart, especially with colour blindness |
| How to add and remove? | Chips above the chart (✕ removes), a "+ Add" chip that opens a list of every location; the choice lives in the URL | Direct, works the same on phone and desktop, shareable, and the back button works |
| New backend? | **None for the first milestone** (the browser loads each picked location's snapshot). A small summary endpoint later, for ranking every location | Snapshots already hold everything and are cached; four are about 110 KB |

---

## 1. Where it lives

### Recommendation: its own page, `/compare`

- **Phone and tablet:** a fifth tab, ordered Overview · Compare · Map · Calendar ·
  Settings. Choosing where to go is the app's main job, so it earns a tab. Five tabs fit
  the bar: at 380 px each tab is about 68 px wide and "Compare" is about 50 px at the
  tab label size. The compact bar (icons only, while scrolling) widens from 220 px to
  about 270 px so each icon keeps a 44 px target. Icon: two crossing lines on axes.
- **Desktop:** the same item in the rail, after Calendar (Overview · Calendar · Compare
  · Map · Settings).
- **From a location page:** a "Compare" button next to Share opens
  `/compare?loc=<this location>,…`. This location is added to the last set compared, or,
  if there was none, it joins the next two snowiest locations.
- **From the Overview:** nothing new on the page itself (it stays one list with one sort
  control). The tab is one tap away.

### Rejected

- **A mode on the Overview** ("select rows, then Compare"). It adds selection controls to
  the calmest page, and the Overview only loads `OverviewRow` (mid band, snow only).
  Compare needs whole snapshots, every band and every metric. Two jobs on one page would
  fight over the space.
- **A tab on the location page.** The location page's tabs (Forecast, Confidence,
  Backcountry, Observed, Webcams) are all about one place. Compare is about several,
  and it would get buried at position 6.
- **Inside the Calendar.** The Calendar is already "where and when the snow is" for
  every location, and REDESIGN says it keeps its layout. Compare links to it for "every
  location, snow only".

---

## 2. Elevation: relative bands, shown honestly

### The options

| Option | For | Against |
|---|---|---|
| **A. Relative band**: each location at its own Base / Mid / Summit | It's where you ski. The numbers are the ones the app computed at that band's own coordinates. No interpolation | "Base" means 512 m at Revelstoke and 1,658 m at Sunshine, so temperatures at the "same" band aren't the same height |
| **B. Fixed elevation**: everyone at, say, 1,500 m | A like-for-like comparison of the weather | The height doesn't exist at some locations (Snoqualmie tops out at 1,652 m; Sunshine starts at 1,658 m), so the app would be extrapolating. Snowfall can't be interpolated between bands: near the snow line it isn't linear (rain at base, snow at mid). It answers a meteorologist's question, not a skier's |
| **C. Relative band, elevation-aware** (recommended) | A's honesty, plus the elevation differences are shown instead of hidden | Needs care in the legend and in the freezing-level view |

### Recommendation: C

- **One band switch for all locations** (Base / Mid / Summit), a segmented control in
  the page header. It's saved per device as its own setting (`prefs.compareBand`,
  default **Mid**), so Compare's first view matches the Overview and Calendar, which are
  at mid. It's kept separate from the location page's band so that flipping elevation
  on one location doesn't change Compare.
- **Every location's real elevation is always shown**: on its chip ("Crystal · 6,870
  ft") and on its row in the readout, with the band's own label ("Alpental top"). The
  difference is never hidden behind the word "Summit".
- **The freezing level reads against each location's terrain.** Freezing level is a
  height in the air, so it's charted as a height (one axis, as today). Each location's
  elevation at the chosen band is a short tick in its colour on the plot's right edge,
  and the readout says what matters: "1,200 ft below Crystal's summit: snow" or "800 ft
  above Snoqualmie's top: rain likely". This is what decides "snow or rain where I'll
  ski".
- **Snow, ratio, temperature, wind and cloud are simply each band's own numbers**, since
  that's what you'd ski in.

### Not now

A "same height" mode (B) could come later for **temperature and freezing level only**:
interpolate between a location's bands with the lapse rate the models imply, and grey
out locations whose range doesn't include that height. Never for snowfall, and never by
extrapolating. Leave it out until someone asks for it.

---

## 3. Chart design

### 3.1 Colour means location, and only location

On the Compare page, a line's colour says which location it is, never which metric.
The metric is always named by the selected metric control. Each location keeps its
colour while it's picked (it follows the location, never its rank): adding takes the
lowest free slot, and removing one never repaints the others.

| Slot | Light | Dark | Line | Notes |
|---|---|---|---|---|
| 1 | `--s1` `#4a8fe7` blue | same | solid | existing token |
| 2 | `--s2` `#dd6b20` orange | same | long dash | existing token |
| 3 | `--s5` `#c2479f` magenta | same | short dash | existing token |
| 4 | new `--cmp4`, `#5b3fb5` violet | new, around `#36ab9c` teal | dots | needs its own step per mode |

Checked with the dataviz palette validator against the panel surfaces (`#f7f9fc` light,
`#222d44` dark), **all pairs** (overlapping lines, so every pair is on screen together):

- Slots 1–3: every check passes in both modes (worst colour-blind ΔE 11.3, normal 20.4).
- Every 4th colour taken from the existing tokens fails (teal, purple, amber and green
  each clash with blue or orange). A new violet passes every check in light mode; in
  dark mode the best candidate (teal `#36ab9c`) is just over the lightness band's limit
  (0.673 against 0.67). Tune it when building, and re-run
  `validate_palette.js --pairs all` for both modes.
- Because of that, **the dash pattern is required, not decoration**, and every line
  also has a label (3.4), so identity never rests on colour alone. Rain green is
  deliberately not a location colour: green keeps meaning rain in the day rows (3.3).

### 3.2 One form per metric

The metric control has the location page's six metrics, renamed for Compare where
the meaning changes.

| Metric | What's drawn | Why this form |
|---|---|---|
| **Snow** | Each location's **running total from now** as a line, ending in a label with the total. The precipitation type is in the day rows under the plot (3.3) | Overlaid bars are unreadable: 4 locations × 20 steps is 80 bars about 4 px wide at 380 px. Running totals overlay cleanly and answer "how much by Saturday" directly |
| **Temperature** | A line per location; the 32 °F / 0 °C line | Continuous, overlays well. The model range band only for the focused location (3.5) |
| **Wind** | A line per location of **gusts** (what holds lifts), with a faint reference line at the ski-day rating's lift-hold gust (45 mph, `skiday.gust_hold_kmh`). The readout gives sustained wind and direction | Two lines per location would be 8 lines. Gusts are the number that changes the decision |
| **Freezing level** | A line per location, with each location's band elevation as a tick on the right edge (section 2) | One axis, with heights. The tick tells you whether the line is above or below that place's terrain |
| **Snow ratio** | A line per location over the existing four zones (Heavy & wet … Dry & fluffy); gaps where it's too warm to snow | Same zones as the location chart, so it reads the same way |
| **Cloud** | **One lane per location** (a strip, darker for more cloud), stacked under each other on one time axis. The readout gives low / mid / high cloud | Cloud cover jumps 0–100 % hour to hour; four of those lines overlap into a mess. Lanes on one time axis (small multiples) compare at a glance |

### 3.3 The day rows (precipitation type, the timeline and the table view in one)

Under the plot, one row per location, ten cells per row (one per forecast day), in the
location's slot order with its swatch at the left. Each cell is the Calendar's heat cell
for that day at the chosen band: the snow ramp for snow, green for rain, purple for
mixed, a faint well for nothing. On the Snow metric the cells show amounts; on the other
metrics they show the day's figure for that metric (high temperature, top gust, lowest
freezing level, mean ratio, mean cloud), so there are exact numbers on every view.

The rows replace the single-location chart's timeline strip: the chart's window is a
raised capsule across all rows; drag it, tap a day, or use ‹ › to move it, exactly as
the location chart's timeline works today (REDESIGN 5.1). They also give the chart its
table view (dataviz rule: every chart has one), and on desktop pointing at a cell shades
that day on the plot.

### 3.4 Readout and labels

- **The readout is above the plot**, because on a phone the hand comes from below and
  covers everything under the finger. It's a fixed-height block: the time being read,
  then one row per location (swatch with its dash, name, band label and elevation,
  value, one-line detail such as "2.1 in this step · 9.5 in by then" or "gusts 38 mph
  SW"). Four rows always take the same space, even with fewer locations, so nothing
  moves when you add one.
- **Line-end labels on desktop and tablet**: each line ends in its location's short name
  and its last value, nudged apart so they never overlap (like the totals on the
  overview's share card). On phones, where long names don't fit beside the plot, the
  readout rows are the labels (same order, same swatches).
- **No "winner" marks on the chart.** The readout lists locations in slot order, never
  sorted by value, so rows don't jump about while you scrub.

### 3.5 Focus: one location in front

Tap a chip or a readout row to **focus** that location: the others fade to a muted
version of their colour and step behind, and the focused one gets its detail (the
temperature or freezing-level model range, sustained wind under the gusts). Tap again,
or tap the plot's background, to clear it. This is the "emphasis" form: one series is
the point and the rest are context. It's the answer to "it's getting busy" that doesn't
need more controls.

### 3.6 Time

- **Hourly, 3- and 6-hour steps** (1, 3 and 5 days) are lined up by absolute time.
  Each location's steps come from `buildSteps()`, as on its own page, and are placed by
  `Date.parse(step.t)`.
- **Day and night steps** (10 days) and the day rows are lined up by each location's
  local date and half (day 06–18, night 18–06), because "Saturday" means Saturday where
  the mountain is.
- Time labels use the first location's time zone. When the picked locations' zones
  differ, a small note says so ("Times in Pacific time; Sunshine is an hour ahead").
- A location whose last good snapshot is old (its run failed) gets a chip note
  ("updated 9 h ago"), and its lines start where its data starts.

### 3.7 Ranges

1 / 3 / 5 / 10 days, the same segmented control and step sizes as the location chart
(`RANGES`, `STEP` in `lib/charts/forecast.ts`). A window that moves keeps one y-scale,
so lines don't jump while panning (as `ForecastChart` does today). The y-scale covers
every picked location, so they always share one axis.

### 3.8 Layout

**Phone (380 px):**

```
Compare                                   [Share]
[ Base | Mid | Summit ]
(● Crystal ✕) (╌ Snoqualmie ✕) (┄ Whistler ✕) (+ Add)   ← scrolls sideways if it must
[Snow] [Temp] [Wind] [Cloud] [Freezing] [Ratio]          ← 3 × 2 chips, as on a location
┌──────────────────────────────────────────────┐
│ Sat 6 AM                                     │  readout, fixed height
│ ● Crystal · Summit 6,870 ft     9.5 in       │
│ ╌ Snoqualmie · Alpental top     6.0 in       │
│ ┄ Whistler · Peak 7,160 ft     12.0 in       │
├──────────────────────────────────────────────┤
│        running totals, one line each         │  plot, 200 px
├──────────────────────────────────────────────┤
│        Fri  Sat  Sun  Mon  Tue …             │
│ ●  ▆   ▇   ▃   ·   ·  …                      │  day rows: heat cells,
│ ╌  ▅   ▃  rain ·   ·  …                      │  the window's capsule
│ ┄  ▂   ▇   ▇   ▅   ▂  …                      │  across all three
└──────────────────────────────────────────────┘
[ 1 | 3 | 5 | 10 days ]
```

**Desktop (≥ 1100 px):** the rail, then one column, as on every page.

```
Compare                                 [ Base | Mid | Summit ]  [Share]
(● Crystal 6,870 ft ✕) (╌ Snoqualmie 5,420 ft ✕) (┄ Whistler 7,160 ft ✕) (+ Add location)
┌ Chart card ──────────────────────────────────────────────────────────────────┐
│ [Snow | Temperature | Wind | Cloud | Freezing level | Ratio]  [1|3|5|10 days] │
│ Sat 6 AM · readout: one cell per location, side by side                       │
│ plot 310 px, left axis, night shading, line-end labels on the right           │
│ day rows (ten days, amounts in each cell; weekends in the accent)             │
└───────────────────────────────────────────────────────────────────────────────┘
```

Under the card, a one-line link: "Every location, snow only: Calendar".

---

## 4. Adding and removing locations

### How

- **Chips** above the chart, one per picked location: swatch with its dash sample, name,
  elevation (desktop), ✕ to remove. Tapping the chip (not the ✕) focuses it (3.5).
- **"+ Add"** is the last chip. It opens a sheet (`Sheet.svelte`, a bottom sheet on
  phones, a popover on desktop) listing every location in "my order" with its region,
  kind and its 5-day snow at mid (from the overview rows the layout already loads), with
  a search box once there are more than 8 locations. Picked ones show a tick and can be
  unticked there too. Locations without a forecast are listed but disabled ("No forecast
  yet").
- **At 4**, "+ Add" stays in place but disabled, with "Up to 4" under it (the control
  keeps its size).
- **With 1 picked**, the chart still draws, and the space where the next chip would be
  says "Add a location to compare". With none (everything removed), the page shows the
  defaults again.
- **Defaults** the first time: the three snowiest locations over the next 7 days, as
  the overview share card picks them (`defaultShareIds(rows, 7, 3)`). After that, the
  last set used.
- **The URL holds the state**: `/compare?loc=crystal,snoqualmie,whistler&band=summit&metric=fl&range=5`.
  A link opens exactly that comparison, the back button undoes an add or remove, and it's
  what the location page's "Compare" button builds. The last set is also saved per
  device (`prefs.compareLocs`), used when `/compare` opens without a `loc`.
- **Keyboard:** the chips are a list of buttons (Delete removes the focused one); the
  plot takes arrow keys as the location chart does.

### Why at most 4

1. **Colour.** Only three of the app's colours stay distinct for every pair (3.1). A
   fourth needs a new colour and a dash pattern; a fifth would be indistinguishable for
   colour-blind viewers, and dataviz practice puts the soft cap for overlaid lines at
   4–6 with direct labels.
2. **The phone.** Four 2-px lines and four readout rows fit at 380 px. Five crowd the
   plot, and the readout grows into the chart's space.
3. **The decision.** By the time you're comparing charts, you're usually down to 2 or 3
   places. "Which of all of them has snow" is the Calendar's job (and the ranked list in
   milestone 3).
4. **Precedent.** The original Plan a day design capped its stacked bars at 2–4.

---

## 5. Data

### Milestone 1: no backend change

- The page calls `getSnapshot(id)` for each picked location (cached for the page's life,
  kept by the service worker for offline use). Adding a location costs one request of
  about 27 KB; removing one costs nothing.
- The location list and 5-day totals for the Add sheet come from `getOverview()`, which
  the layout already loads.
- A new pure module, `lib/compare.ts`, does the work and is tested on its own:
  - `seriesFor(snapshot, band, metric, range)`: steps from `buildSteps()` for one
    location, plus the metric's value and detail per step.
  - `alignByTime(series[])` for hourly to 6-hour steps, `alignByDay(series[])` for
    day/night steps and the day rows (local dates, see 3.6).
  - `dayCells(band, metric)`: the ten day-row values (snow, rain and type per day reuse
    `lib/daybars.ts`).
  - `assignSlots(prev, next)`: keeps each location's slot, gives a new one the lowest
    free slot.
  - `parseCompare(url)` and `compareHref(state)`: the URL in both directions, dropping
    unknown ids, duplicates and anything past 4.
  - `fzReadout(fl_m, bandElev)`: "1,200 ft below the summit: snow" (uses the existing
    `snow_level_offset_m` logic for the snow/rain wording).

### Milestone 3: a small summary endpoint for ranking every location

To rank **every** location in the Add sheet by the chosen metric ("lowest freezing
level at summit, Saturday"), loading every snapshot would be up to 25 × 27 KB, about
700 KB, too much on a phone. Instead:

- `GET /api/compare` (in `backend/snowwatch/api/public.py`, built from
  `latest_snapshots()` like `/api/plan`): per location, per band, per day for 10 days:
  snow (day and night), rain, ptype, lowest and highest freezing level, mean ratio, high
  and low temperature, top gust, mean cloud (low, mid, high), plus the resort rating at
  mid and the avalanche danger for that date. About 11,000 numbers for 25 locations,
  roughly 10 KB gzipped; cached like `/api/overview`.
- New response models in `backend/snowwatch/api/models.py`, then `snowwatch schema` and
  `npm run types` (CI checks both).
- Either a new endpoint or `/api/plan` grown to carry bands and these fields. A new
  endpoint is cleaner: `/api/plan` answers "one date, every location", this answers "ten
  days, every location, every band", and nothing in the app uses `/api/plan` today, so it
  could then be retired.

---

## 6. Day comparison sheet (milestone 2)

Tap a day (a day-row column, or a day label) to open a sheet comparing the picked
locations on that day, one column per location, one row per fact:

| Row | Source |
|---|---|
| Ski-day rating and its reasons | `snapshot.days` (resorts, rated at mid; backcountry shows its avalanche rating instead) |
| Overnight + daytime snow, at the band | band `periods` (night before + day) |
| Snow ratio and quality word | band `periods` (`slr`, `quality`) |
| Lowest freezing level, against the band's elevation | band `hourly.fl_m` with `fzReadout()` |
| Rain | band `periods.rain_mm` |
| High / low | band `periods` |
| Top gust (lift hours) | `snapshot.days.gust_max_kmh` |
| Low cloud and lowest visibility | `snapshot.days` |
| Avalanche danger | `getAvalanche()` |

In rows where "better" is unambiguous (more snow, less rain, lower gusts, less low
cloud, better visibility), the best value is set in bold. Temperature, ratio and
freezing level are never marked (colder isn't always better). No overall score and
no "go here": a single score would hide the trade-off that actually decides the day
(a foot of snow with a lift-closing wind), and the app's rule is facts, not verdicts.

---

## 7. Files

| File | Change |
|---|---|
| `routes/compare/+page.svelte` | New: the page (header, band, chips, chart card, links) |
| `lib/compare.ts`, `lib/compare.test.ts` | New: the data logic in 5 (pure, unit tested) |
| `lib/charts/CompareChart.svelte` | New: plot, readout, day rows, focus. Reuses `niceAxis`, `RANGES`, `STEP`, the night shading and the crosshair handling from `ForecastChart.svelte`. Factor the shared pieces (axis, night bands, pointer-to-step, keyboard) into `lib/charts/` helpers rather than copying them; `ForecastChart` stays as it is apart from using them |
| `lib/components/ComparePicker.svelte` | New: the chips and the Add sheet (built on `Sheet.svelte`; the toggle list is like `share/LocationPicker.svelte`) |
| `lib/prefs.svelte.ts` | `compareBand`, `compareLocs`, `compareMetric` (saved per device, like `band`) |
| `lib/theme.css` | `--cmp4` (light and dark) and four dash patterns as tokens |
| `routes/+layout.svelte` | Compare in `tabs` and `railNav`; tab bar `repeat(5, 1fr)`; compact width so icons keep 44 px; the active state for `/compare` |
| `routes/location/[id]/+page.svelte` | "Compare" button beside Share (milestone 2) |
| `lib/components/CompareDaySheet.svelte` | New: section 6 (milestone 2) |
| `lib/share/compareCard.ts` | New: the chart as a share image (milestone 2), like `forecastCard.ts` |
| `service-worker.ts` | No change: every page is served offline from the cached `/index.html`, and snapshots are already cached. The end-to-end test checks `/compare` offline |
| `backend/snowwatch/api/public.py`, `models.py`, `backend/tests/test_api.py` | `/api/compare` (milestone 3) |
| `docs/ARCHITECTURE.md`, `README.md`, `CHANGELOG.md` | The page in the code map and features; the changelog entry |

---

## 8. Milestones (each shippable)

1. **The Compare page.** Route, nav item, chips and Add sheet, band switch, the six
   metrics (3.2), readout, day rows with the moving window, focus, ranges, URL and saved
   state, empty and loading states. Frontend only.
2. **Deciding a day.** The day comparison sheet (6), "Compare" on location pages, and
   the share image.
3. **Ranking every location.** `/api/compare`, the Add sheet sorted by the chosen metric
   on the chosen day ("most snow", "lowest freezing level", "lightest wind"), and a
   "Closest to me" order using the browser's location (only when asked, as the map
   does).

---

## 9. Tests and verification

- **Unit** (`lib/compare.test.ts`): lining up Pacific and Mountain time locations (an
  hour apart) by time and by local day; a stale snapshot whose data starts earlier;
  slots that survive removing the middle location; URL round trips, unknown ids,
  duplicates and a fifth location dropped; day cells match `dailyTotals()`; the
  freezing-level wording above and below a band.
- **Charts** (`lib/charts/__tests__/`): the existing "no mark outside the plot" check
  for every metric of `CompareChart`, at 380 px and desktop width, with 1 to 4
  locations, including a location whose ratio is all gaps.
- **Component**: the picker adds, removes, disables at 4, and never repaints a kept
  location.
- **End to end** (`e2e/compare.spec.ts`): open from the tab, add and remove a location,
  the URL changes and back undoes it, switch band and metric, scrub, open a shared link,
  no sideways scroll at 380 px, and the page still opens offline with the saved
  snapshots.
- **Palette**: re-run `validate_palette.js --pairs all` for light and dark with the final
  `--cmp4`, and keep the result in this file.
- **Look at it**: screenshots at 380, 768, 1280 and 1440 px, light and dark, with four
  locations on every metric; check that line-end labels never overlap and the readout
  never changes height.
- `npm run check`, `npm run lint`, `npm test` in `frontend/`; `uv run pytest` in
  `backend/` for milestone 3.

---

## 10. Open questions for the owner

Each has a recommendation; the plan works either way.

1. **A fifth tab, or a button only?** Recommended: the fifth tab, since this is the
   app's main job. The alternative is a "Compare" button in the Overview header plus the
   location pages, which keeps the tab bar at four.
2. **Default band: Mid or Summit?** Recommended: Mid, so the first view matches the
   Overview and Calendar. Summit is where storms differ most, so it's a fair choice too.
3. **Wind: gusts or sustained?** Recommended: gusts, with sustained wind in the readout
   and for the focused location.
4. **Default set: snowiest 3, or the first 3 in "my order"?** Recommended: snowiest 3
   the first time, then the last set used.
