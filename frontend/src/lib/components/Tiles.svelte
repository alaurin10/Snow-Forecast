<script lang="ts">
	import type { BandOut } from '../types.gen';
	import { converters, elevation, speed, type UnitSystem } from '../units';

	let { band, units }: { band: BandOut; units: UnitSystem } = $props();
	const c = $derived(converters(units));
	const f = (v: number | null, d = 0) => (v === null ? '–' : v.toFixed(d));
	const w5 = $derived(band.windows['next5']);
	const w10 = $derived(band.windows['d6_10']);
	const h = $derived(band.hourly);
</script>

<div class="tiles">
	<div class="tile">
		<div class="lbl">Last 24 h</div>
		<div class="v num">
			{f(c.snow(band.stats.last24_cm), c.snowDigits)}<small>{c.snowUnit}</small>
		</div>
		<div class="sub faint">model</div>
	</div>
	<div class="tile hero">
		<div class="lbl">Next 5 days</div>
		<div class="v num">{f(c.snow(w5.snow_cm), c.snowDigits)}<small>{c.snowUnit}</small></div>
		<div class="sub muted">
			{#if w5.ens}{f(c.snow(w5.ens.p10), c.snowDigits)}–{f(c.snow(w5.ens.p90), c.snowDigits)} likely range{w5
					.ens.estimated
					? ' (est.)'
					: ''}{:else}no ensemble range{/if}
		</div>
	</div>
	<div class="tile">
		<div class="lbl">Days 6–10</div>
		<div class="v num">{f(c.snow(w10.snow_cm), c.snowDigits)}<small>{c.snowUnit}</small></div>
		<div class="sub muted">
			{#if w10.ens}{f(c.snow(w10.ens.p10), c.snowDigits)}–{f(c.snow(w10.ens.p90), c.snowDigits)} likely{/if}
		</div>
	</div>
	<div class="tile">
		<div class="lbl">Now</div>
		<div class="v num">{f(c.temp(h.temp_c[0]))}<small>{c.tempUnit}</small></div>
		<div class="sub muted">
			snow level {elevation(h.snow_level_m[0], units)} · {speed(h.wind_kmh[0], units)}
		</div>
	</div>
</div>

<style>
	.tiles {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
	}
	@media (min-width: 768px) {
		.tiles {
			grid-template-columns: repeat(4, minmax(0, 1fr));
		}
	}
	.tile {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 10px 12px;
		min-width: 0;
	}
	.hero {
		border-color: var(--snow);
	}
	.lbl {
		font-size: 0.78rem;
		color: var(--text-2);
		font-weight: 600;
	}
	.v {
		font-size: 2rem;
		font-weight: 600;
		line-height: 1.1;
	}
	.v small {
		font-size: 0.9rem;
		color: var(--text-2);
		margin-left: 3px;
		font-weight: 500;
	}
	.sub {
		font-size: 0.76rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
