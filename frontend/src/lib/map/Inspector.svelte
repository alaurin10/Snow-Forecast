<!--
  "This spot": the map panel's content for the tapped spot itself, in three sections in a
  fixed order, one line per row (label left, value right):
  1. Terrain: elevation, slope and the way it faces; when direct sun reaches it on the day
     in question; the likely wind effect there while the wind layer is on.
  2. Snow & weather, from the map's weather on the server: forecast snow for the next day,
     three days and week (at the spot's height, and for the model's area), at a few
     heights around it, the next two days hour by hour, the snow level, the wind, snow on
     the ground and snow that fell.
  3. Avalanche, with the zones loaded: today's published rating for the spot's band and
     its zone, and the concern index's class here while that layer is on.
  Rows keep their height while things load (skeletons), so nothing jumps when the numbers
  arrive; every caveat sits in one "About these numbers" at the foot.
-->
<script lang="ts">
	import type { UnitSystem } from '../units';
	import { elevation as fmtElevation } from '../units';
	import type { PointFacts } from './terrain/messages';
	import { FLAT_DEG, SLOPE_CLASSES, sectorOf, slopeClass } from './terrain/analysis';
	import { metresPerPixel } from './terrain/dem';
	import type { SunFacts } from './terrain/shade';
	import { windWord } from './terrain/wind';
	import { dangerWord } from '../conditions';
	import { BAND_WORDS, DANGER_COLORS, type AvyHere } from './avalanche';
	import { CONCERN_CLASSES, type ConcernFactors } from './terrain/concern';
	import type { PointOut } from '../types.gen';
	import { RAMPS, type PrecipKind } from '../radar';
	import { snow as fmtSnow, speed as fmtSpeed } from '../units';
	import { elevationLadder, snowAtElevation, TERRAIN_NOTE } from './layers/snowtiles';
	import { areaText } from './here';

	type Pending = 'loading' | 'ready' | 'none';

	interface Props {
		lat: number;
		facts: PointFacts | null;
		error: string | null;
		units: UnitSystem;
		/** Direct sun at the spot through a day. */
		sun?: SunFacts | null;
		sunState?: Pending;
		/** Wind effect at the spot (−1 stripped to 1 loaded) and the stretch of forecast it's for. */
		wind?: { value: number; window: string } | null;
		/** 'none' when the wind layer is off (no row). */
		windState?: Pending;
		/** Null while the zones load, or where there is no zone. */
		avy?: AvyHere | null;
		/** The concern index's factors here, while that layer is on. */
		concern?: ConcernFactors | null;
		/** What the map's weather says here; null while it loads or if it couldn't be had. */
		point?: PointOut | null;
		pointState?: 'loading' | 'ready' | 'failed';
		onzone?: () => void;
		/** The glacier the spot is on (its whole area once known), and its own card. */
		glacier?: { name: string; area?: number | null } | null;
		onglacier?: () => void;
		/** The ATES rating mapped here. */
		ates?: { name: string; color?: string } | null;
	}

	let {
		lat,
		facts,
		error,
		units,
		sun = null,
		sunState = 'loading',
		wind = null,
		windState = 'none',
		avy = null,
		concern = null,
		point = null,
		pointState = 'ready',
		onzone,
		glacier = null,
		onglacier,
		ates = null
	}: Props = $props();
	const sign = (n: number) => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : '0');

	const SECTOR_WORDS: Record<string, string> = {
		N: 'north',
		NE: 'northeast',
		E: 'east',
		SE: 'southeast',
		S: 'south',
		SW: 'southwest',
		W: 'west',
		NW: 'northwest'
	};

	const cls = $derived(facts ? slopeClass(facts.slope) : -1);
	const flat = $derived(!!facts && facts.slope < FLAT_DEG);
	const sector = $derived(facts ? sectorOf(facts.aspect) : 'N');
	const land = $derived(!error && !facts?.sea);
	/** How fine the elevation behind the numbers is, in words. */
	const grid = $derived.by(() => {
		if (!facts) return '';
		const m = metresPerPixel(lat, facts.srcZ);
		const fine = m < 1.5 ? `${m.toFixed(1)} m` : `${Math.round(m)} m`;
		return units === 'imperial' ? `${Math.max(1, Math.round(m * 3.28084))} ft` : fine;
	});
	const slopeGrid = $derived(
		facts
			? units === 'imperial'
				? `${Math.round(facts.metresPerPixel * 3.28084)} ft`
				: `${Math.round(facts.metresPerPixel)} m`
			: ''
	);
	const clock = (ms: number) =>
		new Date(ms).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
	const zone = $derived(
		sun?.first != null
			? (new Date(sun.first)
					.toLocaleTimeString('en-US', { timeZoneName: 'short' })
					.split(' ')
					.pop() ?? '')
			: ''
	);
	/** "today", or "Dec 21" for another day. */
	const sunDay = $derived.by(() => {
		if (!sun) return '';
		const [y, m, d] = sun.date;
		const now = new Date();
		if (y === now.getFullYear() && m === now.getMonth() + 1 && d === now.getDate()) return 'today';
		return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric',
			timeZone: 'UTC'
		});
	});
	const sunHours = $derived(
		sun
			? sun.hours < 0.95
				? `${Math.round(sun.hours * 60)} min`
				: `${sun.hours.toFixed(1)} h`
			: ''
	);
	/** The weather numbers worth showing at the spot, or null outside the map's box. */
	const wx = $derived.by(() => {
		if (!point || !point.inside) return null;
		const nowS = Date.now() / 1000;
		const total = (w: number) => point.totals.find((t) => t.window === w)?.cm ?? null;
		const soon = <T extends { t: number }>(xs: T[]) => xs.find((x) => x.t >= nowS - 1800) ?? null;
		const level = soon(point.snow_level);
		const levels = point.snow_level
			.filter((x) => x.t <= nowS + 72 * 3600 && x.value != null)
			.map((x) => x.value!);
		const ridge = soon(point.ridge);
		const gust = soon(point.gust);
		// The next 48 hourly forecast frames, each a cell in its colour.
		const hours = point.rates.filter((r) => r.kind === 'forecast' && r.span_h <= 1).slice(0, 48);
		const strip = hours.map((r) => ({
			t: r.t,
			color: r.type
				? (RAMPS[r.type as PrecipKind].steps.find((s) => s.from === r.low)?.color ?? 'transparent')
				: 'transparent'
		}));
		const firstWet = hours.find((r) => r.type);
		// Snow by elevation: at the spot's own height, and three days' worth at a few
		// heights around it.
		const elevs = point.elevations ?? [];
		const spotM = facts ? (facts.sea ? 0 : facts.elevation) : null;
		const byElev = (w: number) => point.totals.find((t) => t.window === w)?.by_elevation;
		const at = (w: number, m: number | null) => snowAtElevation(byElev(w), elevs, m);
		const here = [at(24, spotM), at(72, spotM), at(168, spotM)] as const;
		const adjusted = here.some((v) => v != null);
		const ladderWindow = byElev(72) ? 72 : byElev(24) ? 24 : 0;
		const ladder =
			spotM != null && ladderWindow && !facts?.sea
				? elevationLadder(spotM, units === 'imperial').map((m) => ({
						m,
						cm: at(ladderWindow, m)
					}))
				: [];
		return {
			snow: here,
			area: [total(24), total(72), total(168)] as const,
			adjusted,
			ladder,
			ladderLabel: ladderWindow === 72 ? '3 days' : '24 h',
			hasTotals: point.totals.length > 0,
			level: level?.value ?? null,
			lowest: levels.length ? Math.min(...levels) : null,
			ridge,
			gust: gust?.value ?? null,
			depth: point.depth?.cm ?? null,
			fell: point.observed.filter((o) => o.cm != null),
			strip,
			firstWet: firstWet
				? `${firstWet.type} from ${new Date((firstWet.t - 3600) * 1000)
						.toLocaleString('en-US', { weekday: 'short', hour: 'numeric' })
						.replace(',', '')}`
				: hours.length
					? 'Dry for the next two days'
					: ''
		};
	});
	const avySection = $derived(land && (!!avy || !!ates || (!!concern && concern.base != null)));
</script>

<div class="insp">
	<section aria-label="Terrain">
		<h3>Terrain</h3>
		{#if error}
			<p class="faint msg">{error}</p>
		{:else if facts?.sea}
			<p class="msg">Water, at sea level.</p>
		{:else}
			<dl class="big">
				<div>
					<dt>Elevation</dt>
					<dd class="num">
						{#if facts}{fmtElevation(facts.elevation, units)}{:else}<span class="skel"></span>{/if}
					</dd>
				</div>
				<div>
					<dt>Slope</dt>
					<dd class="num">
						{#if facts}
							{#if cls >= 0}<i style:background={SLOPE_CLASSES[cls].color} aria-hidden="true"
								></i>{/if}
							{Math.round(facts.slope)}°
						{:else}<span class="skel short"></span>{/if}
					</dd>
				</div>
				<div>
					<dt>Faces</dt>
					<dd>
						{#if !facts}<span class="skel short"></span>
						{:else if flat}
							<span class="faint">flat</span>
						{:else}
							<span title={SECTOR_WORDS[sector]}>{sector}</span>
							<span class="faint num">{Math.round(facts.aspect)}°</span>
						{/if}
					</dd>
				</div>
			</dl>
			<dl class="rows">
				<div>
					<dt>Sun {sunDay}</dt>
					<dd class="num">
						{#if !facts || sunState === 'loading'}<span class="skel"></span>
						{:else if !sun}<span class="faint">–</span>
						{:else if sun.first != null && sun.last != null}
							{clock(sun.first)} – {clock(sun.last)}
							{zone}
							<span class="faint">· {sunHours}</span>
						{:else if sun.sunrise == null}
							<span class="faint">no sunrise or sunset</span>
						{:else}
							No direct sun
						{/if}
					</dd>
				</div>
				{#if windState !== 'none'}
					<div>
						<dt>Wind effect</dt>
						<dd title={wind?.window}>
							{#if windState === 'loading' || !facts}<span class="skel"></span>
							{:else if wind}{windWord(wind.value)}
								<span class="faint">· {wind.window.toLowerCase()}</span>
							{:else}<span class="faint">–</span>{/if}
						</dd>
					</div>
				{/if}
				{#if glacier}
					<div>
						<dt>On a glacier</dt>
						<dd>
							<button class="link" onclick={() => onglacier?.()} title={glacier.name}
								>{glacier.name}{glacier.area ? ` · ${areaText(glacier.area, units)}` : ''} ›</button
							>
						</dd>
					</div>
				{/if}
			</dl>
		{/if}
	</section>

	<section aria-label="Snow and weather">
		<h3>Snow & weather</h3>
		{#if pointState === 'loading'}
			<table class="snow" aria-busy="true" aria-label="Loading the weather here">
				<thead><tr><th></th><th>24 h</th><th>3 days</th><th>7 days</th></tr></thead>
				<tbody
					><tr
						><th>Area</th>{#each [0, 1, 2] as i (i)}<td><span class="skel tiny"></span></td
							>{/each}</tr
					></tbody
				>
			</table>
			<div class="next">
				<div class="cap"><span>Next 48 h</span></div>
				<span class="strip skel-strip"></span>
			</div>
			<dl class="rows">
				{#each ['Snow level', 'Ridge wind', 'On the ground'] as k (k)}
					<div>
						<dt>{k}</dt>
						<dd><span class="skel"></span></dd>
					</div>
				{/each}
			</dl>
		{:else if pointState === 'failed'}
			<p class="faint msg">The weather here couldn't be loaded.</p>
		{:else if !wx}
			<p class="faint msg">Outside the area the map's weather covers.</p>
		{:else}
			{#if wx.hasTotals}
				<table class="snow" aria-label="Forecast snow">
					<thead><tr><th></th><th>24 h</th><th>3 days</th><th>7 days</th></tr></thead>
					<tbody>
						{#if wx.adjusted}
							<tr>
								<th scope="row" title={TERRAIN_NOTE}>Here</th>
								{#each wx.snow as v, i (i)}<td>{fmtSnow(v, units)}</td>{/each}
							</tr>
						{/if}
						<tr class:faint={wx.adjusted}>
							<th scope="row">Area</th>
							{#each wx.area as v, i (i)}<td>{fmtSnow(v, units)}</td>{/each}
						</tr>
					</tbody>
				</table>
				{#if wx.ladder.length}
					<table class="snow" aria-label="Snow by height, {wx.ladderLabel}">
						<thead>
							<tr>
								<th>By height</th>
								{#each wx.ladder as r (r.m)}<th>{fmtElevation(r.m, units)}</th>{/each}
							</tr>
						</thead>
						<tbody>
							<tr>
								<th scope="row">{wx.ladderLabel}</th>
								{#each wx.ladder as r (r.m)}<td>{fmtSnow(r.cm, units)}</td>{/each}
							</tr>
						</tbody>
					</table>
				{/if}
			{/if}
			{#if wx.strip.length}
				<div class="next">
					<div class="cap">
						<span>Next 48 h</span>
						<span class="faint" title={wx.firstWet}>{wx.firstWet}</span>
					</div>
					<span class="strip" role="img" aria-label={wx.firstWet}>
						{#each wx.strip as c (c.t)}<b style:background={c.color}></b>{/each}
					</span>
				</div>
			{/if}
			<dl class="rows">
				{#if wx.level != null}
					<div>
						<dt>Snow level</dt>
						<dd class="num">
							{fmtElevation(wx.level, units)}
							{#if wx.lowest != null && wx.lowest < wx.level - 100}
								<span class="faint">· lowest {fmtElevation(wx.lowest, units)}</span>
							{/if}
						</dd>
					</div>
				{/if}
				{#if wx.ridge?.kmh != null}
					<div>
						<dt>Ridge wind</dt>
						<dd class="num">
							{wx.ridge.dir != null ? `${sectorOf(wx.ridge.dir)} ` : ''}{fmtSpeed(
								wx.ridge.kmh,
								units
							)}
						</dd>
					</div>
				{/if}
				{#if wx.gust != null}
					<div>
						<dt>Gusts</dt>
						<dd class="num">
							{fmtSpeed(wx.gust, units)} <span class="faint">near the ground</span>
						</dd>
					</div>
				{/if}
				{#if wx.depth != null}
					<div>
						<dt>On the ground</dt>
						<dd class="num">{fmtSnow(wx.depth, units)}</dd>
					</div>
				{/if}
				{#if wx.fell.length}
					<div>
						<dt>Fell</dt>
						<dd class="num">
							{#each wx.fell as o, i (o.hours)}{i ? ' · ' : ''}{fmtSnow(o.cm, units)}
								<span class="faint">{o.hours} h</span>{/each}
						</dd>
					</div>
				{/if}
			</dl>
		{/if}
	</section>

	{#if avySection}
		<section aria-label="Avalanche">
			<h3>Avalanche</h3>
			<dl class="rows">
				{#if ates}
					<div>
						<dt>ATES</dt>
						<dd>
							{#if ates.color}<i style:background={ates.color} aria-hidden="true"></i>{/if}
							{ates.name}
						</dd>
					</div>
				{/if}
				{#if avy}
					<div>
						<dt>{BAND_WORDS[avy.band]}</dt>
						<dd>
							{#if avy.level}
								<i style:background={DANGER_COLORS[avy.level]} aria-hidden="true"></i>
								{avy.level} · {dangerWord(avy.level)}
							{:else}
								<span class="faint">{avy.status ?? 'no rating'}</span>
							{/if}
						</dd>
					</div>
					<div>
						<dt>Zone</dt>
						<dd>
							<button class="link" onclick={() => onzone?.()} title={avy.zone}>{avy.zone} ›</button>
						</dd>
					</div>
				{/if}
				{#if concern && concern.base != null}
					<div>
						<dt>Concern <span class="beta">beta</span></dt>
						<dd>
							{#if concern.cls >= 0}
								<i style:background={CONCERN_CLASSES[concern.cls].color} aria-hidden="true"></i>
								{CONCERN_CLASSES[concern.cls].label}
							{:else}
								<span class="faint">not drawn (under 25°)</span>
							{/if}
						</dd>
					</div>
				{/if}
			</dl>
			{#if concern && concern.base != null}
				<details class="how">
					<summary>How?</summary>
					<p class="faint num">
						({concern.base} danger {sign(concern.wind)} wind {sign(concern.sun)} sun) × {concern.slope}
						slope × {concern.match}
						{concern.problem ? `(${concern.problem})` : 'match'} = {concern.score.toFixed(1)}
					</p>
				</details>
			{/if}
		</section>
	{/if}

	<details class="about">
		<summary>About these numbers</summary>
		<div class="faint">
			{#if facts && !facts.sea}
				<p>
					Elevation grid {grid}{facts.fallback ? ' (backup source)' : ''}; slope over {slopeGrid}.
					Sun and wind effect come from the shape of the terrain alone: estimates.
				</p>
			{/if}
			{#if wx}
				<p>
					{#if wx.adjusted}
						From the map's weather: models 2.5–15 km across. “Here” is worked out for this spot's
						height (the model's precipitation, as snow above its snow level); “Area” and the rest
						are for the model's area, not this slope. {TERRAIN_NOTE}
					{:else}
						From the map's weather: models 2.5–15 km across, so numbers for the area, not this
						slope.
					{/if}
				</p>
			{/if}
			{#if avy}
				<p>
					Band from treeline taken as {fmtElevation(avy.treeline.band[0], units)}–{fmtElevation(
						avy.treeline.band[1],
						units
					)}{avy.treeline.own ? ` (your numbers for ${avy.treeline.name})` : ' (approximate)'}.
					Ratings exactly as published; they don't rate any one slope.
				</p>
			{/if}
			{#if concern}<p>Concern index: this app's experimental arithmetic, not a forecast.</p>{/if}
		</div>
	</details>
</div>

<style>
	.insp {
		display: grid;
		gap: 14px;
	}
	section {
		display: grid;
		gap: 6px;
	}
	h3 {
		margin: 0;
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-2);
	}
	p {
		margin: 0;
	}
	.msg {
		font-size: 0.8rem;
	}
	dl {
		margin: 0;
	}
	.big {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 8px;
	}
	.big dt {
		font-size: 0.7rem;
		color: var(--text-2);
	}
	.big dd {
		margin: 0;
		height: 1.5rem;
		font-weight: 650;
		font-size: 1.05rem;
		display: flex;
		align-items: center;
		gap: 5px;
		white-space: nowrap;
	}
	.big dd .faint {
		font-weight: 500;
		font-size: 0.78rem;
	}
	/* One line per row: the label in a fixed column, the value right-aligned. */
	.rows {
		display: grid;
		gap: 2px;
	}
	.rows div {
		display: grid;
		grid-template-columns: 6.5rem minmax(0, 1fr);
		align-items: center;
		gap: 8px;
		min-height: 1.45rem;
	}
	.rows dt {
		font-size: 0.75rem;
		color: var(--text-2);
		white-space: nowrap;
	}
	.rows dd {
		margin: 0;
		text-align: right;
		font-weight: 600;
		font-size: 0.82rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.rows dd .faint {
		font-weight: 500;
		font-size: 0.76rem;
	}
	.num {
		font-variant-numeric: tabular-nums;
	}
	i {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 3px;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.15);
		vertical-align: baseline;
	}
	.rows dd i {
		margin-right: 4px;
	}
	/* The snow tables: a label column, then 24 h, 3 days, 7 days (or a few heights). */
	.snow {
		width: 100%;
		border-collapse: collapse;
		table-layout: fixed;
		font-size: 0.82rem;
		font-variant-numeric: tabular-nums;
	}
	.snow th,
	.snow td {
		height: 1.45rem;
		padding: 0 0 0 8px;
		text-align: right;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.snow th:first-child {
		width: 6.5rem;
		padding-left: 0;
		text-align: left;
	}
	.snow thead th {
		height: 1.1rem;
		font-size: 0.7rem;
		font-weight: 500;
		color: var(--text-2);
	}
	.snow tbody th {
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--text-2);
	}
	.snow td {
		font-weight: 600;
	}
	.snow tr.faint td {
		font-weight: 500;
	}
	.next {
		display: grid;
		gap: 3px;
	}
	.cap {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		font-size: 0.75rem;
		color: var(--text-2);
		min-height: 1.1rem;
	}
	.cap .faint {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.strip {
		display: flex;
		height: 12px;
		width: 100%;
		border-radius: 4px;
		overflow: hidden;
		box-shadow: inset 0 0 0 1px var(--border);
	}
	.strip b {
		flex: 1;
	}
	.skel,
	.skel-strip {
		display: inline-block;
		width: 4.5rem;
		height: 0.8rem;
		border-radius: 4px;
		background: var(--grid);
	}
	.skel.short {
		width: 2.5rem;
	}
	.skel.tiny {
		width: 2.6rem;
		vertical-align: middle;
	}
	.skel-strip {
		display: flex;
		width: 100%;
		height: 12px;
	}
	.link {
		border: 0;
		background: transparent;
		color: var(--accent-ink, var(--accent));
		font: inherit;
		font-weight: 600;
		padding: 0;
		cursor: pointer;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.beta {
		font-size: 0.6rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 0 4px;
		border-radius: 4px;
		background: var(--hover);
	}
	details summary {
		cursor: pointer;
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--accent-ink, var(--accent));
		width: max-content;
	}
	.how p {
		margin-top: 4px;
		font-size: 0.74rem;
	}
	.about {
		border-top: 1px solid var(--border);
		padding-top: 8px;
	}
	.about div {
		display: grid;
		gap: 6px;
		margin-top: 6px;
		font-size: 0.74rem;
	}
	@media (prefers-reduced-motion: no-preference) {
		.skel,
		.skel-strip {
			animation: pulse 1.4s ease-in-out infinite;
		}
	}
	@keyframes pulse {
		50% {
			opacity: 0.45;
		}
	}
</style>
