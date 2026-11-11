<!--
  Terrain facts for a tapped spot: elevation, slope and the way it faces, with the
  detail of the data behind them; when direct sun first and last reaches it on the day
  in question; and the likely wind effect there when a location's wind is in range.
  More facts (forecast snow, the avalanche rating) join it in later milestones.
-->
<script lang="ts">
	import type { UnitSystem } from '../units';
	import { elevation as fmtElevation } from '../units';
	import type { PointFacts } from './terrain/messages';
	import { FLAT_DEG, SLOPE_CLASSES, sectorOf, slopeClass } from './terrain/analysis';
	import { metresPerPixel } from './terrain/dem';
	import type { SunFacts } from './terrain/shade';
	import { windWord } from './terrain/wind';

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
		onclose: () => void;
	}

	let { lat, lon, facts, error, units, sun = null, wind = null, onclose }: Props = $props();

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
	const coords = $derived(
		`${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? 'E' : 'W'}`
	);
</script>

<div class="insp glass" role="dialog" aria-label="Terrain here">
	<header>
		<strong>Terrain here</strong>
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
		{#if sun || wind}
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
			</ul>
		{/if}
		<p class="faint small">
			Elevation grid {grid}{facts.fallback ? ' (backup source)' : ''}; slope over {slopeGrid}.
			{#if sun || wind}Sun and wind from terrain shape alone: estimates.{/if}
		</p>
	{/if}
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
	.coords {
		font-variant-numeric: tabular-nums;
	}
</style>
