<!-- The location's snow station: what it measures now, how the snowpack has moved over
     the last 30 days, and how much new snow each day brought. Measured, not modelled. -->
<script lang="ts">
	import type { Snotel } from '../types.gen';
	import { converters, elevation, snow, type UnitSystem } from '../units';
	import DailySeries from '../charts/DailySeries.svelte';
	import DailyBars from '../charts/DailyBars.svelte';

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
	// New snow on a day: how much deeper the snow was the next morning (as the forecast
	// scorecard counts it); from snow water × 10 where the station has no depth sensor.
	const gains = $derived(
		days.slice(0, -1).map((d, i) => {
			const next = days[i + 1];
			if (d.depth_cm !== null && next.depth_cm !== null)
				return Math.max(0, next.depth_cm - d.depth_cm);
			if (d.swe_mm !== null && next.swe_mm !== null) return Math.max(0, next.swe_mm - d.swe_mm);
			return null;
		})
	);
	const week = $derived.by(() => {
		const now = days.at(-1)?.depth_cm ?? null;
		const then = days.at(-8)?.depth_cm ?? null;
		return now === null || then === null ? null : now - then;
	});
	const signed = (cm: number | null | undefined) => {
		if (cm === null || cm === undefined) return '–';
		return `${cm > 0 ? '+' : ''}${snow(cm, units)}`;
	};
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
				<span class="eyebrow">Snow depth</span>
				<strong class="num">{hasDepth ? snow(station.depth_cm, units) : 'not measured'}</strong>
			</div>
			<div>
				<span class="eyebrow">Last 24 h</span>
				<strong class="num">{hasDepth ? signed(station.change24_cm) : '–'}</strong>
			</div>
			<div>
				<span class="eyebrow">Last 72 h</span>
				<strong class="num">{hasDepth ? signed(station.change72_cm) : '–'}</strong>
			</div>
			<div>
				<span class="eyebrow">Last 7 days</span>
				<strong class="num">{signed(week)}</strong>
			</div>
			<div>
				<span class="eyebrow">Snow water</span>
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
			<DailyBars
				title="New snow each day"
				dates={days.slice(0, -1).map((d) => d.date)}
				values={gains.map((v) => c.snow(v))}
				unit={c.snowUnit}
				digits={c.snowDigits}
				floor={units === 'imperial' ? 2 : 5}
				{width}
			/>
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
		<p class="faint small">
			Last reading {when(station.obs_time)}. Measured, not modelled. Changes are the depth gauge’s:
			settling and wind make them smaller than the snowfall{hasDepth
				? ''
				: '; with no depth gauge here, new snow is the snow-water gain × 10'}.
		</p>
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
		grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
		gap: 10px 8px;
		margin: 12px 0 14px;
	}
	.tiles div {
		display: grid;
		gap: 1px;
	}
	.tiles strong {
		font-size: 1.3rem;
		font-weight: 600;
		letter-spacing: -0.02em;
		line-height: 1.2;
	}
	.charts {
		display: grid;
		gap: 12px 16px;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 270px), 1fr));
	}
</style>
