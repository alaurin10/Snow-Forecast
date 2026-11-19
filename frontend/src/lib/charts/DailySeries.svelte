<!-- One observed daily series (snow depth or snow water) as an area over the last 30 days.
     Days sit on the same bands as DailyBars and DailyRange, so stacked charts line up and
     can share one crosshair (`index`). -->
<script lang="ts">
	import { scaleBand, scaleLinear } from 'd3-scale';
	import Frame from './Frame.svelte';
	import { bandIndex, bandPath, linePath, maxOf } from './geom';
	import { monthDay } from '../time';

	interface Props {
		title: string;
		dates: string[];
		/** Already in display units. */
		values: (number | null)[];
		unit: string;
		digits?: number;
		color?: string;
		width?: number;
		height?: number;
		/** The day under the shared crosshair, or null. */
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
		color = 'var(--snow)',
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
			.domain([0, maxOf(values, 1)])
			.range([ih, 0])
			.nice(3)
	);
	const xs = $derived(dates.map((d) => (x(d) ?? 0) + x.bandwidth() / 2));
	const ys = $derived(values.map((v) => (v === null ? null : y(v))));
	const last = $derived([...values].reverse().find((v) => v !== null) ?? null);
	const fmt = (v: number | null) => (v === null ? '–' : `${v.toFixed(digits)} ${unit}`);
	const readout = $derived(
		index !== null && dates[index]
			? `${monthDay(dates[index])}: ${fmt(values[index])}`
			: last === null
				? 'no data'
				: `latest ${fmt(last)}`
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
		label={`${title}, daily, ${unit}`}
		crossX={index === null ? null : xs[index]}
		onpointer={onindex ? (px) => onindex(bandIndex(x, dates.length, px)) : undefined}
		{onleave}
	>
		{#snippet children({ ih: plotH })}
			{#if values.some((v) => v !== null)}
				<path
					class="mark area"
					style:fill={color}
					d={bandPath(
						xs,
						ys.map((v) => (v === null ? null : plotH)),
						ys
					)}
				/>
				<path class="mark line" style:stroke={color} d={linePath(xs, ys)} />
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
	.area {
		opacity: 0.18;
	}
	.line {
		fill: none;
		stroke-width: 2;
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
