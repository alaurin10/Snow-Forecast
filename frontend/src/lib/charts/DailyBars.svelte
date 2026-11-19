<!-- One observed daily series as bars (new snow each day) over the last 30 days. Shares
     its day bands, and optionally a crosshair, with DailySeries and DailyRange. -->
<script lang="ts">
	import { scaleBand, scaleLinear } from 'd3-scale';
	import Frame from './Frame.svelte';
	import { bandIndex, maxOf, roundedTopBar } from './geom';
	import { monthDay } from '../time';

	interface Props {
		title: string;
		dates: string[];
		/** Already in display units. */
		values: (number | null)[];
		unit: string;
		digits?: number;
		/** The least the y-axis reaches, so a week of dustings isn't drawn as a storm. */
		floor?: number;
		width?: number;
		height?: number;
		index?: number | null;
		onindex?: (i: number) => void;
		onleave?: () => void;
	}

	let {
		title,
		dates,
		values,
		unit,
		digits = 0,
		floor = 1,
		width: fixedWidth,
		height = 140,
		index = null,
		onindex,
		onleave
	}: Props = $props();
	let measured = $state(0);

	const W = $derived(fixedWidth ?? measured);
	const M = { top: 8, right: 12, bottom: 22, left: 36 };
	const ih = $derived(height - M.top - M.bottom);
	const iw = $derived(Math.max(0, W - M.left - M.right));
	const x = $derived(scaleBand<string>().domain(dates).range([0, iw]).paddingInner(0.25));
	const y = $derived(
		scaleLinear()
			.domain([0, maxOf(values, floor)])
			.range([ih, 0])
			.nice(3)
	);
	const total = $derived(values.reduce<number>((acc, v) => acc + (v ?? 0), 0));
	const any = $derived(values.some((v) => v !== null));
	const readout = $derived(
		index !== null && dates[index]
			? `${monthDay(dates[index])}: ${values[index] === null ? '–' : `${values[index]!.toFixed(digits)} ${unit}`}`
			: any
				? `${total.toFixed(digits)} ${unit} in all`
				: 'no data'
	);
</script>

<div bind:clientWidth={measured}>
	<Frame
		{title}
		{readout}
		width={W}
		{height}
		margin={M}
		{y}
		yTicks={y.ticks(3)}
		label={`${title}, ${unit}`}
		crossX={index === null || !dates[index] ? null : (x(dates[index]) ?? 0) + x.bandwidth() / 2}
		onpointer={onindex ? (px) => onindex(bandIndex(x, dates.length, px)) : undefined}
		{onleave}
	>
		{#snippet children({ ih: plotH })}
			{#if any}
				{#each dates as d, i (d)}
					{@const v = values[i]}
					{#if v !== null && v > 0}
						<path
							class="mark bar"
							d={roundedTopBar(x(d) ?? 0, y(v), x.bandwidth(), plotH - y(v), 2)}
						/>
					{/if}
				{/each}
			{:else}
				<text class="empty" x="8" y={plotH / 2}>No readings from this station.</text>
			{/if}
		{/snippet}
		{#snippet below()}
			{#if dates.length >= 2}
				<text class="tick" x="0" y={ih + 15}>{monthDay(dates[0])}</text>
				<text class="tick" x={iw} y={ih + 15} text-anchor="end">{monthDay(dates.at(-1)!)}</text>
			{/if}
		{/snippet}
	</Frame>
</div>

<style>
	.bar {
		fill: var(--snow);
	}
	.tick {
		fill: var(--text-3);
		font-size: 10.5px;
	}
	.empty {
		fill: var(--text-3);
		font-size: 12px;
	}
</style>
