<!--
  The station's last 30 days in detail: the snowpack (depth, or snow water), the new
  snow each day, and each day's low and high temperature, stacked on one time axis.
  Pointing at any chart marks the same day on all three.
-->
<script lang="ts">
	import { converters, type UnitSystem } from '../units';
	import DailySeries from '../charts/DailySeries.svelte';
	import DailyBars from '../charts/DailyBars.svelte';
	import DailyRange from '../charts/DailyRange.svelte';
	import type { StationRead } from './read';

	interface Props {
		read: StationRead;
		units: UnitSystem;
		/** Fixed chart width (tests); otherwise each chart measures its container. */
		width?: number;
	}

	let { read, units, width }: Props = $props();
	const c = $derived(converters(units));
	const days = $derived(read.days);
	const dates = $derived(days.map((d) => d.date));
	let view = $state<'depth' | 'water'>('depth');
	const showDepth = $derived(read.hasDepth && view === 'depth');
	const hasTemps = $derived(days.some((d) => d.tmin_c !== null || d.tmax_c !== null));
	let index = $state<number | null>(null);
	const onindex = (i: number) => (index = i);
	const onleave = () => (index = null);
</script>

<section class="card" aria-labelledby="pack-h">
	<div class="cardhead">
		<h2 id="pack-h">The last {days.length} days</h2>
		{#if read.hasDepth}
			<div class="seg" role="group" aria-label="Snowpack chart">
				<button aria-pressed={view === 'depth'} onclick={() => (view = 'depth')}>Depth</button>
				<button aria-pressed={view === 'water'} onclick={() => (view = 'water')}>Snow water</button>
			</div>
		{/if}
	</div>
	<div class="charts">
		{#if showDepth}
			<DailySeries
				title="Snow depth"
				{dates}
				values={days.map((d) => c.snow(d.depth_cm))}
				unit={c.snowUnit}
				digits={c.snowDigits}
				{width}
				{index}
				{onindex}
				{onleave}
			/>
		{:else}
			<DailySeries
				title="Snow water"
				{dates}
				values={days.map((d) => c.water(d.swe_mm))}
				unit={c.waterUnit}
				digits={c.waterDigits}
				color="var(--level)"
				{width}
				{index}
				{onindex}
				{onleave}
			/>
		{/if}
		<DailyBars
			title="New snow each day"
			{dates}
			values={days.map((d) => c.snow(d.new_cm))}
			unit={c.snowUnit}
			digits={c.snowDigits}
			floor={units === 'imperial' ? 2 : 5}
			height={120}
			{width}
			{index}
			{onindex}
			{onleave}
		/>
		{#if hasTemps}
			<DailyRange
				title="Low and high temperature"
				{dates}
				lo={days.map((d) => c.temp(d.tmin_c))}
				hi={days.map((d) => c.temp(d.tmax_c))}
				unit={c.tempUnit}
				freezing={c.freezing}
				height={120}
				{width}
				{index}
				{onindex}
				{onleave}
			/>
		{/if}
	</div>
	<details class="how">
		<summary>How this is measured</summary>
		<p>
			Readings from the station’s own sensors: measured, not modelled. New snow is how much deeper
			the snow was the next morning{read.hasDepth
				? ''
				: ' (with no depth gauge here, the snow-water gain × 10)'}, so settling and wind make it
			smaller than the snowfall, and a day that settled more than it snowed counts as none. Snow
			water is the water in the snowpack if it all melted. Temperatures are each day’s low and high
			at the station’s own elevation.
		</p>
	</details>
</section>

<style>
	.cardhead {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 8px 12px;
		margin-bottom: 10px;
	}
	.cardhead h2 {
		margin: 0;
	}
	.charts {
		display: grid;
		gap: 14px;
	}
</style>
