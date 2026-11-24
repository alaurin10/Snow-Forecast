# Snow Watch: Compare plan (conditions side by side across locations)

Status: **built** (24 Nov 2026): milestone 1, the Compare button on location pages and
the share image (milestone 2) and the ranked Add list with `/api/compare` (milestone 3).
The day comparison sheet (milestone 2) was left out: the owner found day-by-day tables
under the chart repeated it. "Built: what changed"
at the end lists where the build differs from the text below.

## Context

The use case: you're choosing where to go, whether that's this weekend at a resort or
the best touring next week. The questions are the same every time:

1. Where will there be the most new snow by the time I get there?
2. Will it be snow or rain at the height I'll ski?
3. How dry will it be (snow ratio)?
4. Will I see anything (cloud), and will the lifts run (wind)?
5. How cold will it be?

Today the app answers question 1 across locations (Overview: 7 days of snow at mid;
Calendar: 10 days of snow as a heat grid). Questions 2–5 can only be answered one
location at a time, by flipping between location pages and remembering numbers.
Compare puts the locations you choose on one chart, for any metric, at the same
elevation band, and lets you save a set of them as a group ("Washington touring")
to open again later.

**History.** The original plan had "Compare" and replaced it with "Plan a day"
(`docs/history/PLAN.md`, decision 10): every location for one date, plus "stack the
day/night bars of 2–4 locations on one scale". The API for it still exists
(`GET /api/plan`, mid band only), but there is no page for it.

**Rules this has to keep** (from `docs/REDESIGN.md` and `docs/ARCHITECTURE.md`):

- Calm, not a dashboard: one column, few controls on the page.
- One y-axis per chart. No mark outside the plot (tested). Works at 380 px with a thumb.
- Units are converted in the browser; the API serves metric only.
- Data colours (snow blue, rain green …) mean the same thing everywhere.
- Controls never move because of their own state or a neighbour's (APP-NOTES-PLAN).
- No prose and no AI: rule-based facts only. Never a "go here" verdict.

**Facts measured for this plan** (fixtures `live-20261104`, rebuilt locally):

- A snapshot is about 27 KB gzipped (175–183 KB raw): 240 hourly steps × 3 bands, with
  every metric Compare needs (`snow_cm`, `rain_mm`, `temp_c`, `gust_kmh`, `wind_kmh`,
  `wdir`, `cloud`, `fl_m`, `slr`, `pop`). Eight snapshots, the most a comparison holds,
  are about 220 KB, and `getSnapshot()` already caches them (the service worker keeps
  them for offline use).
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

## Owner review (23 Nov 2026)

Decided by the owner, and followed everywhere below:

- **A fifth tab is fine; Overview and Map stay first.** Order: Overview · Map · Compare ·
  Calendar · Settings.
- **Nothing is picked automatically.** You choose every location yourself.
- **Groups**: save a set of locations under a name ("Washington touring") and open it
  again later, e.g. to find the best place for the next week.
- **Every line is solid.** No dash patterns.
- **One line per location.** Charts that draw several lines for one metric on a
  location page (temperature with its model range, wind with gusts, freezing level with
  its range) draw a single line per location in Compare.
- **Groups stay in the browser**, like the app's other settings; "Copy link" moves one
  to another device. No server storage.
- **A new comparison starts at Mid.** A group keeps the band it was left at.
- **Wind is drawn as gusts**, with sustained speed and direction in the readout.
- **Up to 8 locations** in a comparison or group.

---

## Decisions at a glance

| Question | Decision | Why, in one line |
|---|---|---|
| Where does it live? | A new **Compare** page (`/compare`), the third of five tabs and the third rail item; a "Compare" button on each location page | Comparing is a job of its own, with its own controls and data; it doesn't fit inside a page about one location or the glanceable Overview |
| How are locations chosen? | **By hand only**: a list of every location with tick boxes. Nothing is pre-filled | The owner's call; what's worth comparing depends on the trip, which the app can't know |
| Can I keep a set? | **Groups**: name a set, open it from the page's header later. A group opens the way you left it | "Washington touring" is a question you ask again every week |
| How many? | **Up to 8 locations** in a comparison or group; **up to 4 drawn as lines** at once, which you turn on and off | Every location gets a row of day-by-day numbers. 4 is the most solid-line colours that stay clearly distinct in both themes |
| Overlay or separate charts? | **One solid line per location** for snow total, temperature, wind, freezing level and snow ratio; **one lane per location** for cloud | Lines overlay cleanly; cloud cover jumps 0–100 % and its lines would tangle |
| Which elevation? | **Relative bands** (Base / Mid / Summit), one switch for all, with each location's real elevation shown everywhere | It's where you'd actually ski, and it uses the numbers the app really computes. A fixed height would mean inventing data |
| New backend? | **None for the first milestone.** Groups are saved in the browser. A small summary endpoint later, for ranking every location | Snapshots already hold everything and are cached |

---

## 1. Where it lives

### Its own page, `/compare`

- **Phone and tablet tab bar:** Overview · Map · Compare · Calendar · Settings. Five tabs
  fit: at 380 px each tab is about 68 px wide and "Compare" is about 50 px at the tab
  label size. The compact bar (icons only, while scrolling) widens from 220 px to about
  270 px so each icon keeps a 44 px target. Icon: two crossing lines on axes.
- **Desktop rail:** the same order, Overview · Map · Compare · Calendar · Settings. This
  moves Map above Calendar in the rail (today the rail has Calendar second), so the two
  menus match.
- **From a location page:** a "Compare" button next to Share opens a new comparison with
  just this location in it and the Add list open, so you pick the rest. It never adds
  locations for you.
- **The Overview** doesn't change (one list, one sort control). The tab is one tap away.

### Rejected

- **A mode on the Overview** ("select rows, then Compare"). It adds selection controls to
  the calmest page, and the Overview only loads `OverviewRow` (mid band, snow only).
  Compare needs whole snapshots, every band and every metric.
- **A tab on the location page.** Those tabs (Forecast, Confidence, Backcountry,
  Observed, Webcams) are all about one place.
- **Inside the Calendar.** The Calendar is "every location, snow only", and REDESIGN
  says it keeps its layout. Compare links to it.

---

## 2. Elevation: relative bands, shown honestly

### The options

| Option | For | Against |
|---|---|---|
| **A. Relative band**: each location at its own Base / Mid / Summit | It's where you ski. The numbers are the ones the app computed at that band's own coordinates. No interpolation | "Base" means 512 m at Revelstoke and 1,658 m at Sunshine, so temperatures at the "same" band aren't the same height |
| **B. Fixed elevation**: everyone at, say, 1,500 m | A like-for-like comparison of the weather | The height doesn't exist at some locations (Snoqualmie tops out at 1,652 m; Sunshine starts at 1,658 m), so the app would be extrapolating. Snowfall can't be interpolated between bands: near the snow line it isn't linear (rain at base, snow at mid). It answers a meteorologist's question, not a skier's |
| **C. Relative band, elevation-aware** (chosen) | A's honesty, plus the elevation differences are shown instead of hidden | Needs care in the labels and in the freezing-level view |

### C, in practice

- **One band switch for all locations** (Base / Mid / Summit), a segmented control in
  the page header. A group remembers its band (touring groups will usually be Summit).
  A new comparison starts at **Mid**, matching the Overview and Calendar. It's separate
  from the location page's band, so flipping elevation on one location doesn't change
  Compare.
- **Every location's real elevation is always shown**: on its row ("Crystal · 6,870 ft")
  and in the readout, with the band's own label ("Alpental top"). The difference is
  never hidden behind the word "Summit".
- **The freezing level reads against each location's terrain.** Freezing level is a
  height in the air, so it's charted as a height (one axis). Each charted location's
  elevation at the chosen band is a small tick in its colour on the plot's right edge
  (a tick, not a second line), and the readout says what matters: "1,200 ft below
  Crystal's summit: snow" or "800 ft above Snoqualmie's top: rain likely".
- **Snow, ratio, temperature, wind and cloud are simply each band's own numbers**, since
  that's what you'd ski in.

### Not now

A "same height" mode (B) could come later for **temperature and freezing level only**:
interpolate between a location's bands, and grey out locations whose range doesn't
include that height. Never for snowfall, and never by extrapolating.

---

## 3. Chart design

### 3.1 Colour means location; every line is solid

On the Compare page, a line's colour says which location it is, never which metric (the
metric is always named by the selected metric control). Every line is solid and 2 px.
A location keeps its colour while its line is on: turning a line on takes the lowest free
colour, and turning one off never repaints the others.

| Colour | Light | Dark | Notes |
|---|---|---|---|
| 1 | `--s1` `#4a8fe7` blue | same | existing token |
| 2 | `--s2` `#dd6b20` orange | same | existing token |
| 3 | `--s5` `#c2479f` magenta | same | existing token |
| 4 | new `--cmp4`, `#5b3fb5` violet | new `--cmp4`, `#34a99a` teal | its own step per mode |

Checked with the dataviz palette validator against the panel surfaces (`#f7f9fc` light,
`#222d44` dark), **all pairs**, since overlapping lines put every pair on screen together:

- Colours 1–3: every check passes in both modes (worst colour-blind ΔE 11.3, normal 20.4).
- Every 4th colour from the existing tokens fails: teal, purple, amber and green each
  clash with blue or orange. A new violet passes every check in light mode. In dark mode
  the best candidate (teal `#36ab9c`) tells apart from the others (colour-blind ΔE 8.1,
  normal 15.7) but sits just over the lightness band's limit (0.673 against 0.67). Tune
  it when building and re-run `validate_palette.js --pairs all` for both modes.
- **Why 4 lines at most:** with solid lines, colour is the only thing on the plot that
  tells lines apart. A 5th colour is possible but marginal: in light mode a bronze
  (`#7a5a00`) passes, but in dark mode the only candidate that stays distinct is a lime
  (`#a3c45a`) that's too light for the band and close to rain's green, and a 6th fails
  the normal-vision check even in light mode. Four keeps every pair clearly distinct in
  both modes with one new token. Even so, lines are never told apart by colour alone:
  every charted location also has a label (3.4) and a swatch on its row (3.3).
- Rain green is deliberately not a location colour: green keeps meaning rain in the
  location rows.

### 3.2 One line per location, for every metric

| Metric | What's drawn, per charted location | Simplified from the location page |
|---|---|---|
| **Snow** | Its **running total from now** as a line, ending at its total. Amounts per day are in the location rows | Bars become one running-total line: overlaid bars for 4 locations would be about 4 px wide at 380 px |
| **Temperature** | One line; the 32 °F / 0 °C line as a faint reference | No model range band |
| **Wind** | One line of **gusts** (what holds lifts), with a faint reference at the ski-day rating's lift-hold gust (45 mph, `skiday.gust_hold_kmh`) | No separate sustained-wind line; sustained speed and direction are in the readout text |
| **Freezing level** | One line, plus its band-elevation tick on the right edge (section 2) | No range band, no base/mid/summit lines |
| **Snow ratio** | One line over the existing four zones (Heavy & wet … Dry & fluffy); gaps where it's too warm to snow | Same zones, so it reads the same way |
| **Cloud** | **One lane per location**: a strip, darker for more cloud, all on one time axis | Total cloud only (no low / mid / high split). A lane, not a line, because cloud cover jumps 0–100 % hour to hour and four such lines tangle |

Steps follow the location chart: hourly for 1 day, 3-hourly for 3, 6-hourly for 5, day
and night halves for 10 (temperature then shows the day's high and the night's low, as
it does today).

### 3.3 Location rows: everyone in the comparison, day by day

Under the plot, one row per location in the comparison (up to 8), in the comparison's
order:

```
● Crystal · 6,870 ft    ▆  ▇  ▃  ·  ·  ▂  ▅  ·  ·  ·   18 in
● Snoqualmie · 5,420    ▅  ▃  ░  ·  ·  ·  ▂  ·  ·  ·    9 in
○ Stevens · 5,800       ▃  ▅  ▂  ·  ·  ▂  ▃  ·  ·  ·   11 in
+ Add location                                   Edit
```

- **The name** has a swatch: filled in its line's colour when its line is on, an empty
  ring when off. **Tap the name to turn its line on or off.** This is the chart's legend
  and its on/off switch in one, so there's no separate row of chips.
- **Ten day cells**: the Calendar's heat cells at the chosen band (the snow ramp for
  snow, green for rain, purple for mixed, a faint well for nothing). On the Snow metric
  they show amounts; on the others they show the day's figure for that metric (high
  temperature, top gust, lowest freezing level, mean ratio, mean cloud). On phones they
  follow the Calendar's phone cells.
- **A summary column** at the right for the days in the chart's window: snow total,
  lowest freezing level, strongest gust, mean ratio while snowing, mean cloud, high and
  low temperature. With 8 touring spots in a group, this column is where "best place
  next week" is read.
- **Order**: the comparison's own order, or "Most snow" (the window's snow total), with
  the same sort button as the Overview (`prefs.sort` style, its own setting).
- **The window**: a raised capsule across all rows shows the chart's days; drag it, tap
  a day, or use ‹ › to move it, as the location chart's timeline works today
  (REDESIGN 5.1).
- The rows are also the chart's table view (every chart has one).

### 3.4 Readout and labels

- **The readout is above the plot**, because on a phone the hand comes from below and
  covers everything under the finger. It's a fixed-height block: the time being read,
  then one row per **charted** location (swatch, name, band label and elevation, value,
  one short detail such as "2.1 in this step" or "wind 20 mph SW"). It always keeps
  room for four rows, so nothing moves when a line is turned on.
- **Line-end labels**: on desktop and tablet each line ends in the location's name and
  value, nudged apart so they never overlap. On phones, where names don't fit beside
  the plot, each line ends in its value, matching the readout row of the same colour.
- **No "winner" marks on the chart**, and the readout keeps the rows' order while you
  scrub (it never re-sorts by value).

### 3.5 Time

- **Hourly, 3- and 6-hour steps** (1, 3 and 5 days) are lined up by absolute time. Each
  location's steps come from `buildSteps()`, as on its own page, and are placed by
  `Date.parse(step.t)`.
- **Day and night steps** (10 days) and the location rows are lined up by each
  location's local date and half (day 06–18, night 18–06), because "Saturday" means
  Saturday where the mountain is.
- Time labels use the first location's time zone. When the zones differ, a small note
  says so ("Times in Pacific time; Sunshine is an hour ahead").
- A location whose last good snapshot is old (its run failed) gets a note on its row
  ("updated 9 h ago"), and its line starts where its data starts.

### 3.6 Ranges

1 / 3 / 5 / 10 days, the same segmented control and step sizes as the location chart
(`RANGES`, `STEP` in `lib/charts/forecast.ts`). A window that moves keeps one y-scale,
so lines don't jump while panning. The y-scale covers every charted location, so they
always share one axis.

### 3.7 Layout

**Phone (380 px):**

```
Compare                                        [Share]
[ Washington touring ▾ ]           [ Base | Mid | Summit ]
[Snow] [Temp] [Wind] [Cloud] [Freezing] [Ratio]      ← 3 × 2 chips, as on a location
┌──────────────────────────────────────────────────┐
│ Sat 6 AM                                         │  readout, room for 4 rows
│ ● Crystal · Summit 6,870 ft          9.5 in      │
│ ● Snoqualmie · Alpental top          6.0 in      │
├──────────────────────────────────────────────────┤
│      running totals, one solid line each         │  plot, 200 px
├──────────────────────────────────────────────────┤
│                Fri Sat Sun Mon Tue …       Total │
│ ● Crystal       ▆   ▇   ▃   ·   ·  …       18 in │  location rows
│ ● Snoqualmie    ▅   ▃   ░   ·   ·  …        9 in │  (tap a name: line on/off)
│ ○ Stevens       ▃   ▅   ▂   ·   ·  …       11 in │
│ + Add location                        Edit · ⇅   │
└──────────────────────────────────────────────────┘
[ 1 | 3 | 5 | 10 days ]
```

**Desktop (≥ 1100 px):** the rail, then one column, as on every page.

```
Compare   [ Washington touring ▾ ]          [ Base | Mid | Summit ]  [Share]
┌ Chart card ──────────────────────────────────────────────────────────────────┐
│ [Snow | Temperature | Wind | Cloud | Freezing level | Ratio]  [1|3|5|10 days] │
│ Sat 6 AM · readout: one cell per charted location, side by side               │
│ plot 310 px, left axis, night shading, name + value at each line's end        │
│ location rows (ten days with amounts, summary column; weekends in the accent) │
└───────────────────────────────────────────────────────────────────────────────┘
```

Under the card, a one-line link: "Every location, snow only: Calendar".

---

## 4. Choosing locations, and groups

### 4.1 By hand, always

- **First visit** (no groups, nothing open): the page shows its header and, where the
  chart will be, "Choose locations to compare" with the list of every location (the same
  list as Add, below) right there. The chart appears once one location is added. Nothing
  is ticked for you.
- **"+ Add location"** at the foot of the rows opens that list in a sheet
  (`Sheet.svelte`: a bottom sheet on phones, a popover on desktop): every location in
  "my order" with its region, kind and its 5-day snow at mid (from the overview rows the
  layout already loads), tick boxes, and a search box once there are more than 8
  locations. Locations without a forecast are listed but can't be ticked ("No forecast
  yet").
- **"Edit"** on the rows shows ✕ to remove a location and handles to reorder (the
  "comparison's own order" used by the rows and the readout).
- **Opening `/compare` again** opens what you had open last: the group, or the unsaved
  comparison. That's your own choice coming back, never a suggestion.

### 4.2 Which locations are lines

- A location added while fewer than 4 lines are on gets its line turned on. The 5th to
  8th locations join as rows with their line off; tap a name to turn its line on.
- With 4 lines on, tapping a fifth name says "Up to 4 lines at once: turn one off first"
  in a short toast. The app never turns one off for you.
- Which lines are on is part of the comparison: it's in the URL and saved with a group.

### 4.3 Groups

A group is a named comparison you can open again: its locations (up to 8, in order),
which of them are lines, and its band, metric and range. **A group opens the way you left
it**, so "Washington touring" can stay at Summit, Snow, 10 days.

- **The group menu** is a pill in the page header showing the open group's name, or
  "New comparison" when nothing is saved. It opens a sheet listing your groups (name, and
  the first few location names), with "New comparison" at the top and an Edit mode to
  rename, reorder and delete them (a delete can be undone from its toast).
- **Saving**: an unsaved comparison shows a "Save as group" button beside the pill. It
  asks for a name (empty, with a placeholder such as "e.g. Washington touring").
- **An open group keeps your changes as you make them**: adding or removing a location,
  turning lines on or off, changing the band, metric or range. It works like editing a
  playlist; there's no separate Save step.
- **Where they're kept**: in this browser, like the app's other settings
  (`prefs.svelte.ts`). The app has no visitor accounts, and the owner's location list is
  the only thing stored on the server.
- **Moving a group to another device**: Share on the Compare page includes "Copy link".
  The link carries the whole group (`/compare?name=Washington%20touring&loc=rainy,…&on=…&band=summit&metric=snow&range=10`).
  Opened on another phone or computer, it shows the comparison with a "Save group" button.
- **When a location goes away** (archived or paused by the owner), its groups drop it,
  with a one-line note the first time the group opens.
- **Limits**: 8 locations per group, 20 groups per browser.

### 4.4 Why these limits

- **4 lines**: colour is the only thing telling solid lines apart, and 4 is the most
  that stay clearly distinct for every pair in both light and dark mode, including for
  colour-blind viewers; a 5th is marginal in dark mode (3.1). Four lines and four
  readout rows also fit a 380 px screen.
- **8 locations**: each is one row of day cells, which works for many more than four, so
  a touring group can hold every spot you'd consider. Eight rows still fit on a phone
  screen with the chart, and loading eight snapshots is about 220 KB. "Every location"
  is the Calendar's job.

---

## 5. Data

### Milestone 1: no backend change

- The page calls `getSnapshot(id)` for each location in the comparison (cached for the
  page's life, kept by the service worker for offline use). Adding a location costs one
  request of about 27 KB; removing one costs nothing.
- The Add list's names and 5-day totals come from `getOverview()`, which the layout
  already loads.
- Groups are stored with the other per-device settings: `prefs.compareGroups` (a list,
  under `sw.compareGroups`) and `prefs.compareOpen` (the group or unsaved comparison
  open last). They're checked when read, like the other prefs: unknown ids, duplicates,
  more than 8 locations or 4 lines, and bad band, metric or range values are dropped.
- A new pure module, `lib/compare.ts`, does the work and is tested on its own:
  - `seriesFor(snapshot, band, metric, range)`: steps from `buildSteps()` for one
    location, with the metric's one value and detail per step.
  - `alignByTime(series[])` for hourly to 6-hour steps; `alignByDay(series[])` for
    day/night steps and the location rows (local dates, see 3.5).
  - `dayCells(band, metric)` and `summary(cells, window, metric)`: the ten cells and the
    summary column (snow, rain and type per day reuse `lib/daybars.ts`).
  - `colours(prevOn, nextOn)`: keeps each line's colour, gives a new line the lowest
    free colour.
  - `toggleLine`, `addLocation`, `removeLocation`, `move`: the comparison's edits, with
    the limits in 4.4.
  - `parseCompare(url)` and `compareHref(state)`: the URL in both directions, dropping
    unknown ids, duplicates and anything past the limits.
  - `fzReadout(fl_m, bandElev)`: "1,200 ft below the summit: snow" (using
    `snow_level_offset_m` for the snow/rain wording).

### Milestone 3: a small summary endpoint for ranking every location

To rank **every** location in the Add list by the chosen metric ("lowest freezing level
at summit, next week"), loading every snapshot would be up to 25 × 27 KB, about 700 KB,
too much on a phone. Instead:

- `GET /api/compare` (in `backend/snowwatch/api/public.py`, built from
  `latest_snapshots()` like `/api/plan`): per location, per band, per day for 10 days:
  snow (day and night), rain, ptype, lowest freezing level, mean ratio, high and low
  temperature, top gust, mean cloud, plus the resort rating at mid and the avalanche
  danger for that date. About 10 KB gzipped for 25 locations; cached like
  `/api/overview`.
- New response models in `backend/snowwatch/api/models.py`, then `snowwatch schema` and
  `npm run types` (CI checks both).
- A new endpoint rather than growing `/api/plan`: that one answers "one date, every
  location"; this one answers "ten days, every location, every band". Nothing in the app
  uses `/api/plan` today, so it could then be retired.

---

## 6. Day comparison sheet (milestone 2)

Tap a day's label above the location rows to open a sheet with every location in the
comparison on that day: one row per location, one column per fact (on phones the table
scrolls sideways inside its card, as the app's tables do).

| Column | Source |
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

In columns where "better" is unambiguous (more snow, less rain, lower gusts, less low
cloud, better visibility), the best value is set in bold. Temperature, ratio and
freezing level are never marked (colder isn't always better). No overall score and no
"go here": a single score would hide the trade-off that actually decides the day (a
foot of snow with a lift-closing wind), and the app's rule is facts, not verdicts.

---

## 7. Files

| File | Change |
|---|---|
| `routes/compare/+page.svelte` | New: the page (header with group pill and band, chart card, empty state, Calendar link) |
| `lib/compare.ts`, `lib/compare.test.ts` | New: the data logic in 5 (pure, unit tested) |
| `lib/charts/CompareChart.svelte` | New: readout, plot and the one-line-per-location metrics. Reuses `niceAxis`, `RANGES`, `STEP`, the night shading and the crosshair handling from `ForecastChart.svelte`. Factor the shared pieces (axis, night bands, pointer-to-step, keyboard) into `lib/charts/` helpers rather than copying them; `ForecastChart` stays as it is apart from using them |
| `lib/components/CompareRows.svelte` | New: the location rows (line toggles, day cells, summary column, window capsule, sort, Edit) |
| `lib/components/CompareAdd.svelte` | New: the Add list, in a sheet and inline for the empty state (built on `Sheet.svelte`; the toggle list is like `share/LocationPicker.svelte`) |
| `lib/components/CompareGroups.svelte` | New: the group menu sheet (open, new, rename, reorder, delete with undo) and "Save as group" |
| `lib/prefs.svelte.ts` | `compareGroups`, `compareOpen` (saved per device, checked when read) |
| `lib/theme.css` | `--cmp4` (light and dark) |
| `routes/+layout.svelte` | Compare in `tabs` and `railNav`, both ordered Overview · Map · Compare · Calendar · Settings; tab bar `repeat(5, 1fr)`; compact width so icons keep 44 px; the active state for `/compare` |
| `routes/location/[id]/+page.svelte` | "Compare" button beside Share (milestone 2) |
| `lib/components/CompareDaySheet.svelte` | New: section 6 (milestone 2) |
| `lib/share/compareCard.ts` | New: the chart as a share image (milestone 2), like `forecastCard.ts`; the Share sheet also gets "Copy link" (milestone 1) |
| `service-worker.ts` | No change: every page is served offline from the cached `/index.html`, and snapshots are already cached. The end-to-end test checks `/compare` offline |
| `backend/snowwatch/api/public.py`, `models.py`, `backend/tests/test_api.py` | `/api/compare` (milestone 3) |
| `docs/ARCHITECTURE.md`, `README.md`, `CHANGELOG.md` | The page in the code map and features; the changelog entry |

---

## 8. Milestones (each shippable)

1. **The Compare page with groups.** Route, nav order, the empty state and Add list,
   location rows with line toggles and summary column, band switch, the six metrics
   (3.2), readout, ranges and the moving window, groups (save, open, rename, reorder,
   delete, keep changes), the URL and "Copy link". Frontend only.
2. **Deciding a day.** The day comparison sheet (6), "Compare" on location pages, and the
   share image.
3. **Ranking every location.** `/api/compare`, and the Add list sorted by the chosen
   metric on the chosen days ("most snow", "lowest freezing level", "lightest wind"),
   so finding new candidates for a group doesn't mean opening each one.

---

## 9. Tests and verification

- **Unit** (`lib/compare.test.ts`): lining up Pacific and Mountain time locations (an
  hour apart) by time and by local day; a stale snapshot whose data starts earlier;
  colours that survive turning off the middle line; the 4-line and 8-location limits
  (the toast case changes nothing); URL round trips, unknown ids, duplicates and values
  past the limits dropped; groups read back from bad or old saved data; a group that
  loses an archived location; day cells match `dailyTotals()`; summary values; the
  freezing-level wording above and below a band.
- **Charts** (`lib/charts/__tests__/`): the existing "no mark outside the plot" check
  for every metric of `CompareChart`, at 380 px and desktop width, with 1 to 4 lines,
  including a location whose ratio is all gaps.
- **Components**: the rows turn lines on and off, never repaint a line that stays on,
  and refuse a fifth line; the group menu saves, opens, renames and deletes, and the
  undo brings a group back.
- **End to end** (`e2e/compare.spec.ts`): the tab order on phone and desktop; the empty
  state with nothing ticked; add locations, turn lines on and off, save a group, reload
  and find it open as left; open a copied group link in a fresh browser and save it;
  switch band and metric, scrub; no sideways scroll at 380 px with 8 locations; the page
  still opens offline with the saved snapshots.
- **Palette**: re-run `validate_palette.js --pairs all` for light and dark with the final
  `--cmp4`, and keep the result in this file. Result (23 Nov 2026, all pairs):
  light `#4a8fe7 #dd6b20 #c2479f #5b3fb5` on `#f7f9fc`: every check passes (worst
  colour-blind ΔE 9.4, normal 20.3); dark `#4a8fe7 #dd6b20 #c2479f #34a99a` on `#222d44`:
  every check passes (worst normal ΔE 15.6), with colour-blind ΔE 7.6 between the teal
  and magenta, in the 6–8 band that needs labels; every line has them (the readout rows,
  the values at the line ends and the swatches on the rows). `#36ab9c` kept 8.1 but sat
  just outside the lightness band.
- **Look at it**: screenshots at 380, 768, 1280 and 1440 px, light and dark, with four
  lines on every metric and eight location rows; check that line-end labels never
  overlap and the readout never changes height.
- `npm run check`, `npm run lint`, `npm test` in `frontend/`; `uv run pytest` in
  `backend/` for milestone 3.

---

## 10. Open questions

None. The owner settled the last four on 23 Nov (see "Owner review"): groups stay in
the browser, a new comparison starts at Mid, wind is gusts, and a group holds up to 8
locations.

---

## Built: what changed (milestone 1)

Where the build differs from the plan above, and why:

- **First visit**: you tick locations in the list, then press **Compare** (the list
  stayed in place while you picked; adding the first location used to replace it with
  the chart at once).
- **Snow line and totals**: the snow line is a running total from the start of the
  window (not from now), and a row's summary is worked out from the same steps the chart
  draws, so a line always ends at its row's total. The snow scale is the snowiest window
  anywhere in the forecast, so lines keep their heights as the window moves.
- **The window**: a timeline right under the chart, as on a location's forecast (owner
  review, 23 Nov), with the range buttons directly below it: a column per day with a
  small bar of each drawn location's snow in its line's colour, the window raised across
  it, drag, tap or ‹ ›. The rows below fade the days outside the chart but don't move it.
- **Cloud cover** is one line per location (its percentage), like the other metrics, not
  a lane per location (owner review, 23 Nov).
- **No day cells** (owner review, 24 Nov): the list under the chart is one line per
  location (the line switch, band and elevation, the total for the days shown, Edit and
  Add); the day cells repeated the chart less readably. The timeline's bars still come
  from each location's days (`dayCells`).
- **Selecting a location** (owner review, 24 Nov): a tap on its card, or a click on a
  desktop, picks its line out (one at a time; again to clear, another to switch).
  Pointing with a mouse wins while it lasts; the selection shows again after. A selection
  whose line is turned off is cleared.
- **Share** (milestone 2's share image, early): `lib/share/compareCard.ts` draws the
  chart as shown, from the same window, scale and lines as the page (`chartLines`,
  `lineValues`, `chartAxis` in `compare.ts`, shared by both), with the selected
  location picked out.
- **Day cells**: numbers only (the unit is in the summary column's heading); freezing
  level in thousands ("4.2k").
- **Telling the lines apart** (owner review, 23 Nov): the readout is a card per line on
  every screen, with the line's colour down its edge, its name and its value; two by two
  on phones, where a card is just those two lines (the rows below give each location's
  elevation), and four across on wider screens, with the band and elevation under the
  value. The colour keys are bold (18 × 5 px) and the lines 2.5 px. The plot has no
  labels of its own: names at the line ends were tried and taken out, as they cost the
  plot width and repeated the cards. On a desktop, pointing at a location (its row or its
  card) picks out its line and fades the others.
- **Copy link** is a button in the page's header (on phones the system share sheet).
  Links keep their commas readable (`loc=rainy,crystal`).
- **Compact tab bar**: 248 px (`--tabbar-compact` in `theme.css`, which the map's
  buttons also use), the widest that keeps the Layers button clear of it on a 360 px
  phone.
- **Stale forecasts**: a row says "updated … ago" once its forecast is more than 9 hours
  old (runs are every 3 hours).
- **Back undoes** adding and removing locations; other changes replace the history
  entry. Every change is a navigation to the new address (`goto(resolve(…))`), so the
  address is always what's open.
- **Snow totals** (owner review, 24 Nov): one setting for both charts (`prefs.snowTotal`,
  Settings → Snow total on charts): a running total from now by default, so lines don't
  jump as the window moves, or from the first day shown. `lineValues` and `chartAxis`
  take it; the forecast chart's running total and its scale follow it too.
- **Timeline button** (owner review, 24 Nov): Compare shows or hides its timeline with
  the forecast chart's setting (`prefs.showTimeline`); the plot's height doesn't change.
