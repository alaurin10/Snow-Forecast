<!--
  Terrain facts for a tapped spot: elevation, slope and the way it faces, with the
  detail of the data behind them; when direct sun first and last reaches it on the day
  in question; and the likely wind effect there when a location's wind is in range.
  With the avalanche zones loaded: the forecast zone, the elevation band the spot is in
  and today's published rating for that band, and, while the concern index is on, each
  of its factors there. And what the map's weather says there (from the server): forecast
  snow for the next day, three days and week, the next two days hour by hour, the snow
  level, the wind, snow on the ground and snow that fell.
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
	import type { HereItem } from './here';

	interface Props {
		lat: number;
		lon: number;
		facts: PointFacts | null;
		error: string | null;
		units: UnitSystem;
		/** Direct sun at the spot through a day; null while it's being worked out or can't be. */
		sun?: SunFacts | null;
		/** Wind effect at the spot (−1 stripped to 1 loaded) and the stretch of forecast it's for. */
		wind?: { value: number; window: string } | null;
		/** Null while the zones load, or where there is no zone. */
		avy?: AvyHere | null;
		/** The concern index's factors here, while that layer is on. */
		concern?: ConcernFactors | null;
		/** What the map's weather says here; null while it loads or if it couldn't be had. */
		point?: PointOut | null;
		pointState?: 'loading' | 'ready' | 'failed';
		/** Map features at the spot: a run or route (with its profile), a hut, a glacier, ATES. */
		here?: HereItem[];
		online?: (item: HereItem) => void;
		onzone?: () => void;
		onclose: () => void;
	}

	let {
		lat,
		lon,
		facts,
		error,
		units,
		sun = null,
		wind = null,
		avy = null,
		concern = null,
		point = null,
		pointState = 'ready',
		here = [],
		online,
		onzone,
		onclose
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
			snow: adjusted ? here : ([total(24), total(72), total(168)] as const),
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
	const coords = $derived(
		`${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? 'E' : 'W'}`
	);
</script>

<div class="insp glass" role="dialog" aria-label="This spot">
	<header>
		<strong>This spot</strong>
		<button class="x" onclick={onclose} aria-label="Close">✕</button>
	</header>
	{#if error}
		<p class="faint">{error}</p>
	{:else if !facts}
		<p class="faint">Measuring…</p>
	{:else if facts.sea}
		<p>Water, at sea level.</p>
	{:else}
		<dl>
			<div>
				<dt>Elevation</dt>
				<dd class="num">{fmtElevation(facts.elevation, units)}</dd>
			</div>
			<div>
				<dt>Slope</dt>
				<dd class="num">
					{#if cls >= 0}<i style:background={SLOPE_CLASSES[cls].color} aria-hidden="true"></i>{/if}
					{Math.round(facts.slope)}°
				</dd>
			</div>
			<div>
				<dt>Faces</dt>
				<dd>
					{#if flat}
						<span class="faint">flat</span>
					{:else}
						<span title={SECTOR_WORDS[sector]}>{sector}</span>
						<span class="faint num">{Math.round(facts.aspect)}°</span>
					{/if}
				</dd>
			</div>
		</dl>
		{#if sun || wind || avy}
			<ul class="more">
				{#if sun}
					<li>
						<span class="k">Sun {sunDay}</span>
						{#if sun.first != null && sun.last != null}
							<span class="num">{clock(sun.first)} – {clock(sun.last)} {zone}</span>
							<span class="faint num">{sunHours} direct</span>
						{:else if sun.sunrise == null}
							<span class="faint">no sunrise or sunset</span>
						{:else}
							<span>No direct sun</span>
						{/if}
					</li>
				{/if}
				{#if wind}
					<li>
						<span class="k">Wind effect</span>
						<span>{windWord(wind.value)}</span>
						<span class="faint">{wind.window.toLowerCase()}</span>
					</li>
				{/if}
				{#if avy}
					<li>
						<span class="k">Avalanche</span>
						{#if avy.level}
							<span
								><i style:background={DANGER_COLORS[avy.level]} aria-hidden="true"></i>
								{BAND_WORDS[avy.band]}
								{avy.level} · {dangerWord(avy.level)}</span
							>
						{:else}
							<span>{BAND_WORDS[avy.band]} · {avy.status ?? 'no rating'}</span>
						{/if}
						<button class="link" onclick={() => onzone?.()}>{avy.zone} ›</button>
					</li>
				{/if}
				{#if concern && concern.base != null}
					<li>
						<span class="k">Concern</span>
						{#if concern.cls >= 0}
							<span
								><i style:background={CONCERN_CLASSES[concern.cls].color} aria-hidden="true"></i>
								{CONCERN_CLASSES[concern.cls].label}</span
							>
						{:else}
							<span class="faint">not drawn (under 25°)</span>
						{/if}
						<span class="faint num"
							>({concern.base} danger {sign(concern.wind)} wind {sign(concern.sun)} sun) × {concern.slope}
							slope × {concern.match}
							{concern.problem ? `(${concern.problem})` : 'match'} = {concern.score.toFixed(
								1
							)}</span
						>
					</li>
				{/if}
			</ul>
		{/if}
		<p class="faint small">
			Elevation grid {grid}{facts.fallback ? ' (backup source)' : ''}; slope over {slopeGrid}.
			{#if sun || wind}Sun and wind from terrain shape alone: estimates.{/if}
			{#if avy}
				Band from treeline taken as {fmtElevation(avy.treeline.band[0], units)}–{fmtElevation(
					avy.treeline.band[1],
					units
				)}{avy.treeline.own ? ` (your numbers for ${avy.treeline.name})` : ' (approximate)'}.
			{/if}
			{#if concern}Concern index: experimental, not a forecast.{/if}
		</p>
	{/if}
	{#if here.length}
		<ul class="more here" aria-label="On the map here">
			{#each here as h, i (i)}
				<li>
					<span class="k">{h.kind}</span>
					<span
						>{#if h.color}<i style:background={h.color} aria-hidden="true"></i>{/if}{h.name}</span
					>
					{#if h.detail}<span class="faint">{h.detail}</span>{/if}
					{#if h.line}
						<button class="link" onclick={() => online?.(h)}>Profile ›</button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
	<section class="wx" aria-label="Weather here">
		{#if pointState === 'loading'}
			<p class="faint small">Loading the weather here…</p>
		{:else if pointState === 'failed'}
			<p class="faint small">The weather here couldn't be loaded.</p>
		{:else if !wx}
			<p class="faint small">Outside the area the map's weather covers.</p>
		{:else}
			<ul class="more">
				{#if wx.hasTotals}
					<li>
						<span class="k">Snow</span>
						<span class="num"
							>{fmtSnow(wx.snow[0], units)}
							<span class="faint">24 h</span> · {fmtSnow(wx.snow[1], units)}
							<span class="faint">3 days</span> · {fmtSnow(wx.snow[2], units)}
							<span class="faint">7 days</span></span
						>
						{#if wx.adjusted}
							<span class="faint small" title={TERRAIN_NOTE}
								>at this spot's height, adjusted to terrain. The model's area: {fmtSnow(
									wx.area[0],
									units
								)} · {fmtSnow(wx.area[1], units)} · {fmtSnow(wx.area[2], units)}</span
							>
						{/if}
					</li>
					{#if wx.ladder.length}
						<li>
							<span class="k">By height</span>
							<span class="num"
								>{#each wx.ladder as r, i (r.m)}{i ? ' · ' : ''}<span class="faint"
										>{fmtElevation(r.m, units)}</span
									>
									{fmtSnow(r.cm, units)}{/each}
								<span class="faint">{wx.ladderLabel}</span></span
							>
						</li>
					{/if}
				{/if}
				{#if wx.strip.length}
					<li class="strip-row">
						<span class="k">Next 48 h</span>
						<span class="strip" role="img" aria-label={wx.firstWet}>
							{#each wx.strip as c (c.t)}<b style:background={c.color}></b>{/each}
						</span>
						<span class="faint">{wx.firstWet}</span>
					</li>
				{/if}
				{#if wx.level != null}
					<li>
						<span class="k">Snow level</span>
						<span class="num">{fmtElevation(wx.level, units)}</span>
						{#if wx.lowest != null && wx.lowest < wx.level - 100}
							<span class="faint num">lowest {fmtElevation(wx.lowest, units)} in 3 days</span>
						{/if}
					</li>
				{/if}
				{#if wx.ridge?.kmh != null || wx.gust != null}
					<li>
						<span class="k">Wind</span>
						{#if wx.ridge?.kmh != null}
							<span class="num"
								>{wx.ridge.dir != null ? `${sectorOf(wx.ridge.dir)} ` : ''}{fmtSpeed(
									wx.ridge.kmh,
									units
								)}
								<span class="faint">at ridge level</span></span
							>
						{/if}
						{#if wx.gust != null}
							<span class="faint num">gusts {fmtSpeed(wx.gust, units)} near the ground</span>
						{/if}
					</li>
				{/if}
				{#if wx.depth != null}
					<li>
						<span class="k">On the ground</span>
						<span class="num">{fmtSnow(wx.depth, units)}</span>
					</li>
				{/if}
				{#if wx.fell.length}
					<li>
						<span class="k">Fell</span>
						<span class="num"
							>{#each wx.fell as o, i (o.hours)}{i ? ' · ' : ''}{fmtSnow(o.cm, units)}
								<span class="faint">{o.hours} h</span>{/each}</span
						>
					</li>
				{/if}
			</ul>
			<p class="faint small">
				{#if wx.adjusted}
					From the map's weather: models 2.5–15 km across. Snow is worked out for this spot's height
					(the model's precipitation, as snow above its snow level); the rest is for the area, not
					this slope.
				{:else}
					From the map's weather: models 2.5–15 km across, so numbers for the area, not this slope.
				{/if}
			</p>
		{/if}
	</section>
	<p class="faint small coords">{coords}</p>
</div>

<style>
	.insp {
		display: grid;
		gap: 6px;
		padding: 10px 12px;
		border-radius: 14px;
		font-size: 0.85rem;
		color: var(--text);
		width: 100%;
		max-width: 340px;
		pointer-events: auto;
		/* Solid enough to read over busy satellite imagery. */
		background: color-mix(in srgb, var(--surface) 92%, transparent);
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.x {
		border: 0;
		background: transparent;
		color: var(--text-2);
		font-size: 0.9rem;
		width: 32px;
		height: 28px;
		margin: -4px -6px -4px 0;
		cursor: pointer;
	}
	p {
		margin: 0;
	}
	dl {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 8px;
		margin: 0;
	}
	dt {
		font-size: 0.7rem;
		color: var(--text-2);
	}
	dd {
		margin: 0;
		font-weight: 650;
		font-size: 1rem;
		display: flex;
		align-items: center;
		gap: 5px;
		white-space: nowrap;
	}
	dd .faint {
		font-weight: 500;
		font-size: 0.78rem;
	}
	i {
		width: 10px;
		height: 10px;
		border-radius: 3px;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.15);
	}
	.more {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 2px;
		font-size: 0.82rem;
	}
	.more li {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 2px 8px;
	}
	.more .k {
		font-size: 0.7rem;
		color: var(--text-2);
		min-width: 5.2rem;
	}
	.more .faint {
		font-size: 0.76rem;
	}
	.small {
		font-size: 0.72rem;
	}
	.link {
		border: 0;
		background: transparent;
		color: var(--accent);
		font: inherit;
		font-size: 0.78rem;
		font-weight: 600;
		padding: 0;
		cursor: pointer;
	}
	.coords {
		font-variant-numeric: tabular-nums;
	}
	.wx {
		display: grid;
		gap: 4px;
		border-top: 1px solid var(--border);
		padding-top: 6px;
	}
	.strip {
		display: inline-flex;
		height: 10px;
		width: 120px;
		border-radius: 3px;
		overflow: hidden;
		box-shadow: inset 0 0 0 1px var(--border);
	}
	.strip b {
		flex: 1;
	}
</style>
