# Frontend redesign: build spec

Status: ready to build. Owner review notes are folded in (see "Decisions from review").
Visual reference: the "Snow Watch redesign options" canvas (private to the owner). Use it
for **colour, glass, card shape and type only**. Its desktop layouts and its moving sky
were rejected; this document overrides it wherever they differ.

## 1. Goals

1. One design language (Liquid Glass over a weather sky) shared by phone and desktop.
2. Phone keeps today's structure (it was redesigned recently and is liked). It gets the
   new skin and a few touch refinements.
3. Desktop stops being a stretched phone page, but stays **calm**: one column, one job per
   screen, sections behind tabs. It uses its extra width for bigger charts, readouts for
   every metric at once, and tables with every column, not for more panels side by side.
4. Several themes, each with light and dark. Dark must be comfortable, never near-black.
5. Nothing the app shows today is removed.

## 2. Decisions from review (hard rules)

- **The sky is static.** It shows the location's weather *now* (time of day plus current
  conditions). It changes only when the location changes (900 ms crossfade) or when the
  data refreshes. Scrubbing the chart, hovering rows, or changing range/metric never
  changes the sky.
- **Rain never goes below the axis.** Keep today's rule (`ForecastChart.svelte`): rain is
  a green bar rising from the baseline on its own small scale (max ~12% of plot height)
  with its value labelled above, only for all-rain steps; mixed steps show their snow
  part in purple.
- **Keep every chart stat.** All six metrics stay: snow and rain, temperature (with model
  spread and 32°F line), wind (with gusts), cloud cover (low/mid/high lanes), freezing
  level (with spread and base/mid/summit lines), snow ratio (with its four zones). Keep
  the running snow-total line and right axis, the lower cloud-cover and
  chance-of-precipitation panel, the 1/3/5/10/15-day ranges, the phone overview strip,
  the "Less certain" marker, and the period readout.
- **Desktop is not a dashboard.** No three-column workspace, no merged "board", no storm
  timeline page. Keep Forecast / Models / Backcountry / Observed as tabs.
- **Learn from the phone.** Desktop components are the phone components given more room:
  the same outlook card, day rows, segmented controls and chart card.

## 3. Design language

### 3.1 Surfaces (two layers)

| Layer | Used for | Recipe (light / dark) |
|---|---|---|
| Sky | Full-window backdrop | See 3.3 |
| Glass | Floating controls only: header nav, tab bar, segmented controls, chips, sheets, location pill | Light `rgba(255,255,255,.5)`, rim `rgba(255,255,255,.8)`, `blur(22px) saturate(1.7)`, shadow `0 12px 32px rgba(24,44,84,.16)`, inset top highlight. Dark `rgba(26,36,60,.46)`, rim `rgba(255,255,255,.2)` |
| Panel | All content: chart card, outlook card, day list, heads up | **Frost** (chosen default): light `rgba(255,255,255,.72)`, dark `rgba(26,36,58,.70)`, `blur(34px)`. Offer "Solid" (`.95`/`.96` opaque) as the reduce-transparency fallback |

Text never sits on bare sky except the hero title and the hero number (both ≥ 30 px).
Small text that is on the sky today (region line, "likely" range) goes in a glass pill.

Contrast was computed over every scene: Frost and Solid pass 4.5:1 at all three ink
levels; Clear glass fails for the faintest ink, so Clear is not offered.

### 3.2 Tokens (replace `frontend/src/lib/theme.css`)

Define once, select with `data-theme` (family) and `data-mode` (light/dark) on `<html>`.
Fix today's duplication (dark block written twice, lines 78–163).

- Ink: light `#0d1b30`, `.76` and `.68` alpha for secondary/tertiary; dark `#f3f6fc`,
  `.80` and `.70`.
- Wells (inactive segment track, metric card): light `rgba(13,27,48,.055)`, dark
  `rgba(255,255,255,.08)`. Selected segment: light `rgba(255,255,255,.95)` + soft shadow,
  dark `rgba(255,255,255,.2)`.
- Rules: light `rgba(13,27,48,.11)`, dark `rgba(255,255,255,.13)`.
- Night shading in charts: light `rgba(30,40,90,.06)`, dark `rgba(0,0,10,.18)`.
- Data colours, identical in every theme and mode (unchanged from today): snow `#4a8fe7`,
  heavy `#dd6b20`, mix `#9b6be0`, rain `#26965f`, temperature `#e5484d`, freezing level
  `#c2479f`, wind `#14a3a3`; avalanche scale unchanged. Rain label ink: light `#1d7a4c`,
  dark `#5fd39a`.
- Snow heat ramp (day/night cells, calendar): light `#d5e5fb #a9cbf5 #6aa5ee #2f6fd0
  #173f86`; dark `#1f3a66 #2b5a9e #4a8fe7 #8fbdf3 #d3e6fc` (more snow is lighter in dark).
- Radius: controls are capsules; cards 24–28 px; inner cells 12–18 px; nested corners
  share a centre (inner radius = outer − padding).
- Type: Inter for text and tables, Manrope for numerals and headings (replaces Space
  Grotesk). Scale: 12, 13.5, 15, 17, 22, 30, 54 (desktop title), 100 (desktop hero
  number) / 124 (phone hero number, weight 300). Tabular numerals everywhere.
- Spacing: 4-px base; gaps 8 / 12 / 16 / 24.
- Breakpoints: three named tiers only, phone ≤ 640, tablet 641–1099, desktop ≥ 1100.
  Replace the nine ad hoc widths. Extend `lib/viewport.svelte.ts` with `tablet` and
  `desktop`. Tablet uses the phone layouts with two-up cards where they fit.

### 3.3 Sky

- New `lib/sky.ts`: `pickScene(hourly, sun, now) → { scene, night }`, a pure function with
  unit tests. Scenes: clear, clear night, alpenglow (±75 min of sunrise/sunset when clear
  or partly cloudy), partly cloudy, overcast, light snow, heavy snow (≥ 0.9 in in 3 h),
  rain and snow, rain, fog (`wcode` 45/48). Input is the current hour only.
- New `lib/components/Sky.svelte`, mounted once in `+layout.svelte` behind everything,
  `position: fixed`. Layers: three-stop gradient, sun/moon glow, stars (night), 2–3 soft
  cloud blobs, a two-tone ridgeline, slow snow (rain shows as clouds and palette, no
  streaks, to keep it calm).
- Palettes per scene, light and dark: copy the `scenes()` table from the canvas
  (`Main.dc.html`). Dark mode uses the dark palette (blue-slate, never black).
- The Overview shows the first location in "my order"; a location page shows that
  location; Map, Calendar and More show the first location.
- Motion: clouds drift (60–80 s), snow falls slowly (14–30 s per pass). Particles pause
  when the tab is hidden. All of it stops under `prefers-reduced-motion` or Motion: Off.

### 3.4 Themes

Under More → Appearance: Theme (Live Sky, Alpenglow, Glacier, Larch, Granite) and Mode
(match device, light, dark). Fixed themes replace the sky with a still three-stop gradient
and change the accent only. Values are in the canvas `themes()` table. Saved per device in
`lib/prefs.svelte.ts` (new keys `themeFamily`, `motion`; keep `theme` as the mode).

### 3.5 Motion

- Segmented controls: the selected capsule slides (`340ms cubic-bezier(.3,1.35,.5,1)`).
- Press: scale .97, spring back.
- Phone tab bar shrinks to icons on scroll down, grows back on scroll up.
- Desktop header: keep today's nav-to-page-controls swap (`pagebar.svelte.ts`), now as a
  glass morph.
- Charts: bars rise (640 ms) and lines fade in on first draw and when the metric or range
  changes. Never on hover. The crosshair follows the pointer with an 80 ms ease.
- Hero number counts to the new value when the location or band changes.
- Preference Motion: Full / Subtle (no particles, no count-up) / Off.

## 4. Shared components (build these first)

| New component | Replaces / used by |
|---|---|
| `Glass.svelte` (wrapper with `variant="glass" or "panel"`) | every card and floating control |
| `Segmented.svelte` (sliding capsule, keyboard arrows) | `.seg` in `theme.css`; units, elevation, range, tabs, sort |
| `OutlookCard.svelte` (3 cells phone / 4 cells desktop) | `.mout` and `.outlook` in `location/[id]/+page.svelte` |
| `HeatCell.svelte` (snow amount, "rain", or dash) | `.heat` cells in `DayList`, `PeriodGrid`, calendar |
| `Skeleton.svelte` | every "Loading…" |

`ForecastChart.svelte` keeps its data logic (`forecast.ts`, `buildSteps`) untouched; only
its markup and styles change (section 6).

## 5. Phone (≤ 640 px): keep the structure, new skin

Files: `routes/+page.svelte`, `routes/location/[id]/+page.svelte`, `lib/components/DayList.svelte`,
`routes/calendar/+page.svelte`, `routes/+layout.svelte`.

- **Overview:** unchanged order (date, title, share; storm card; sort + rows with 7 bars
  and total; legend). Storms become a sideways-swiping row of glass cards (one per storm
  cycle from `stormcycles.ts`). Rows sit in one Frost panel. Each row gets a small sky dot
  (that location's scene now) and shows an alert in the subtitle when there is one.
- **Location:** unchanged order (back, name, share; elevation numbers; section tabs;
  chart card; outlook 3-up; day by day; heads up; about; links). Optional hero: a large
  "next 5 days" number on the sky above the chart, collapsing into a glass title bar on
  scroll. Build it behind a flag; the owner liked both.
- **Chart card:** exactly today's phone chart (readout, plot with total line, overview
  strip, six metric chips, range and share), restyled: Frost panel, 26 px radius, chips
  as wells with the selected chip raised.
- **Day by day:** today's rows (day/date, icon, high/low, wind, day and night heat cells,
  chevron), inside one panel, 54 px rows. Expanding a row shows both halves' snow level,
  chance, precipitation, ratio, wind, gust and cloud.
- **Tab bar:** floating glass capsule, shrinks on scroll.
- **Calendar:** keep the current phone calendar; apply heat ramp and panel.

## 6. Desktop (≥ 1100 px): one calm column

Content column `max-width: 1280px`, centred, 24 px side padding. Sky behind.

### 6.1 Location page, Forecast tab (top to bottom)

1. **Glass header bar:** brand · nav capsule (Overview, Map, Calendar, More) · location
   pill (‹ prev, "Jump to" with Ctrl K, next ›) · units segmented.
2. **Hero on the sky:** "← All locations"; name (54 px); a glass pill with region and
   updated time. Right side: next-5-days number (100 px, weight 300) with the likely range
   under it, and the elevation segmented control showing name + elevation.
3. **Outlook card** (phone's 3-up, four cells): Next storm (accent tint; amount, when,
   heaviest period and snow level) · Days 6–10 (and last 24 h, SLR alternative) · Now
   (temperature, wind and gusts, freezing level) · Avalanche (rating chip or "No rating").
4. **Section tabs** (glass segmented, 500 px): Forecast, Models, Backcountry, Observed.
5. **Chart card** (full width):
   - Header: "Forecast", step note ("Every 6 hours · hover or use the arrow keys"), range
     segmented, Share.
   - **Six metric cards in one row** (today's desktop cards): label with colour key, value
     at the hovered step, one-line detail (chance and running total; models' range;
     gusts; low/mid/high cloud; freezing-level range and position vs base/summit; snow
     ratio word). Clicking a card charts that metric.
   - Axis titles left/right and the hovered period in the centre.
   - Plot 310 px tall with left axis, right axis (snow total, precip only), night shading,
     bars from the baseline, rain labels, crosshair and a dot on the line.
   - Lower panel 64 px: cloud cover area and chance-of-precipitation bars.
   - Day labels under the plot, weekends in the accent. Legend for the current metric.
6. **Day by day card:** one row per day, the phone row widened: day + date + rating ·
   icon · high/low · day and night heat cells · then eight right-aligned columns, each
   showing day over night: snow ratio, snow level, chance, precipitation (in of water),
   wind (dir + speed), gust, cloud, rain. Pointing at a row shades that day on the chart;
   the hovered chart step highlights its row. This replaces the two-rows-per-day
   `PeriodGrid` table on desktop.
7. **Bottom row, two cards:** Heads up (flags in two columns, "NEW" badge) · About this
   forecast + links as capsules.

### 6.2 Other tabs

Same column, same cards, one panel per block: Models (agreement, chance of each amount,
trend), Backcountry (`BackcountryTab.svelte`), Observed (`StationPanel`, `Scorecard`).
Only restyle; no layout merging.

### 6.3 Overview

Same order as phone: date and title on the sky, storms as a row of glass cards, then one
panel of rows. Each row: sky dot · name, scene and temperature (or alert) · avalanche chip
· seven daily bars (wider, with the amount under each bar) · 7-day total · next 5 days with
likely range. Sort segmented (My order / Most snow) and Ctrl K in the header. Hover lifts
the row; click opens. No preview pane. Calendar stays its own page.

### 6.4 Keyboard and pointer

Ctrl/⌘ K opens a location palette; arrow keys move the chart crosshair (plot is
focusable); `[` and `]` switch location; hover previews never change the sky.

## 7. Build order (each stage shippable)

1. Tokens, themes, prefs, `viewport` tiers, fonts. Visual parity check on every page.
2. `Sky.svelte` + `sky.ts` with tests; static per location; reduced motion.
3. Shared components (section 4); swap them in everywhere.
4. Phone pages (section 5).
5. Desktop location page (6.1) including the new desktop day table.
6. Desktop overview (6.3), other tabs (6.2), keyboard (6.4).
7. Share images in `lib/share/` follow the chosen theme; Map controls (`MapView.svelte`)
   adopt glass.

## 8. Must not change

The API, `forecast.ts` step logic, data colours, every metric and column listed above, the
phone page structure, the existing tests (update snapshots only where markup changes).

## 9. Verification per stage

- `npm run check`, `npm run lint`, `npm test` in `frontend/`.
- `frontend/scripts/screenshots.mjs` at 380, 768, 1280 and 1440 px, light and dark, for
  each theme family; it also fails on sideways scroll.
- Manual: scrub the chart fast and confirm the background does not change; confirm no bar
  goes below the axis; tick off all six metrics and every day-table column.
