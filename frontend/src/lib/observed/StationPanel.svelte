<!-- The nearest snow station: what it measures now and its last 30 days. -->
<script lang="ts">
	import type { Snotel } from '../types.gen';
	import { converters, elevation, snow, type UnitSystem } from '../units';
	import DailySeries from '../charts/DailySeries.svelte';

	interface Props {
		station: Snotel | null;
		bandLabel: string;
		bandElev: number;
		units: UnitSystem;
		/** Fixed chart width (tests); otherwise each chart measures its container. */
		width?: number;
	}

	let { station, bandLabel, bandElev, units, width }: Props = $props();
	const c = $derived(converters(units));
	const days = $derived((station?.daily ?? []).slice(-30));
	const hasDepth = $derived(days.some((d) => d.depth_cm !== null));
	const when = (iso: string | null | undefined) =>
		iso
			? new Date(iso).toLocaleString('en-US', {
					weekday: 'short',
					hour: 'numeric',
					minute: '2-digit'
				})
			: '–';
</script>

<section class="card">
	<h2>Snow station</h2>
	{#if station}
		<p class="muted small">
			<strong>{station.name ?? station.triplet}</strong> · {station.network ?? 'NRCS SNOTEL'}
			{#if station.elev_m !== null}· {elevation(station.elev_m, units)}{/if}
			{#if station.distance_km !== null && station.distance_km !== undefined}· {units === 'imperial'
					? `${(station.distance_km * 0.621371).toFixed(1)} mi`
					: `${station.distance_km.toFixed(1)} km`} away{/if}
			{#if station.elev_m !== null}
				· {bandLabel} is {elevation(Math.abs(bandElev - station.elev_m), units)}
				{bandElev >= station.elev_m ? 'higher' : 'lower'}{/if}
		</p>
		<div class="tiles">
			<div>
				<span class="k">Snow depth</span>
				<strong class="num">{hasDepth ? snow(station.depth_cm, units) : 'not measured'}</strong>
			</div>
			<div>
				<span class="k">Last 24 h</span>
				<strong class="num">{hasDepth ? snow(station.change24_cm, units) : '–'}</strong>
			</div>
			<div>
				<span class="k">Last 72 h</span>
				<strong class="num">{hasDepth ? snow(station.change72_cm, units) : '–'}</strong>
			</div>
			<div>
				<span class="k">Snow water</span>
				<strong class="num"
					>{station.swe_mm === null
						? '–'
						: `${c.water(station.swe_mm)?.toFixed(c.waterDigits)} ${c.waterUnit}`}</strong
				>
			</div>
		</div>
		<div class="charts">
			{#if hasDepth}
				<DailySeries
					title="Snow depth, 30 days"
					dates={days.map((d) => d.date)}
					values={days.map((d) => c.snow(d.depth_cm))}
					unit={c.snowUnit}
					digits={c.snowDigits}
					{width}
				/>
			{/if}
			<DailySeries
				title="Snow water, 30 days"
				dates={days.map((d) => d.date)}
				values={days.map((d) => c.water(d.swe_mm))}
				unit={c.waterUnit}
				digits={c.waterDigits}
				color="var(--level)"
				{width}
			/>
		</div>
		<p class="faint small">Last reading {when(station.obs_time)}. Measured, not modelled.</p>
	{:else}
		<p class="muted small">
			No snow station is set for this location. The owner can pick one on the Manage page.
		</p>
	{/if}
</section>

<style>
	h2 {
		margin: 0 0 4px;
	}
	.small {
		font-size: 0.85rem;
	}
	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
		gap: 8px;
		margin: 8px 0;
	}
	.tiles div {
		display: grid;
		gap: 2px;
	}
	.k {
		color: var(--text-2);
		font-size: 0.8rem;
	}
	.charts {
		display: grid;
		gap: 10px;
	}
	@media (min-width: 900px) {
		.charts {
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
