<!-- One observed daily series (snow depth or snow water) as an area over the last 30 days. -->
<script lang="ts">
	import { scaleLinear } from 'd3-scale';
	import Frame from './Frame.svelte';
	import { bandPath, linePath, maxOf } from './geom';
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
	}

	let {
		title,
		dates,
		values,
		unit,
		digits = 0,
		color = 'var(--snow)',
		width: fixedWidth
	}: Props = $props();
	let measured = $state(0);

	const W = $derived(fixedWidth ?? measured);
	const M = { top: 8, right: 12, bottom: 22, left: 36 };
	const H = 140;
	const ih = H - M.top - M.bottom;
	const iw = $derived(Math.max(0, W - M.left - M.right));
	const x = $derived(
		scaleLinear()
			.domain([0, Math.max(1, dates.length - 1)])
			.range([0, iw])
	);
	const y = $derived(
		scaleLinear()
			.domain([0, maxOf(values, 1)])
			.range([ih, 0])
			.nice(3)
	);
	const xs = $derived(dates.map((_, i) => x(i)));
	const ys = $derived(values.map((v) => (v === null ? null : y(v))));
	const last = $derived([...values].reverse().find((v) => v !== null) ?? null);
</script>

<div bind:clientWidth={measured}>
	<Frame
		{title}
		readout={last === null ? 'no data' : `latest ${last.toFixed(digits)} ${unit}`}
		width={W}
		height={H}
		margin={M}
		{y}
		yTicks={y.ticks(3)}
		label={`${title}, daily, ${unit}`}
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
