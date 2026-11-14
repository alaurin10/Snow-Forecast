<!--
  Each day's snow, model by model: the ensembles' 10–90% range as a bar, the models'
  median as a tick, and every model as a dot in its own colour. Where the dots sit
  together the models agree; where they scatter, that day is uncertain.
-->
<script lang="ts">
	import { scaleBand, scaleLinear } from 'd3-scale';
	import type { DayRead } from '../confidence';
	import { converters, type UnitSystem } from '../units';
	import { MODEL_NAMES, modelColor } from '../models';
	import { weekday } from '../time';
	import Frame from './Frame.svelte';
	import { maxOf } from './geom';

	interface Props {
		days: DayRead[];
		models: string[];
		units: UnitSystem;
		width?: number;
	}

	let { days: allDays, models, units, width: fixedWidth }: Props = $props();
	let measured = $state(0);

	const W = $derived(fixedWidth ?? measured);
	const c = $derived(converters(units));
	const M = { top: 10, right: 8, bottom: 22, left: 34 };
	const H = 240;
	const iw = $derived(Math.max(0, W - M.left - M.right));
	// A phone has room for ten days of dots; wider screens show every day there is.
	const days = $derived(iw < 520 ? allDays.slice(0, 10) : allDays);
	const shown = $derived(
		models.filter((m) => days.some((d) => d.models[m] !== null && d.models[m] !== undefined))
	);
	const x = $derived(
		scaleBand<string>()
			.domain(days.map((d) => d.date))
			.range([0, iw])
			.paddingInner(0.15)
	);
	const y = $derived(
		scaleLinear()
			.domain([
				0,
				maxOf(
					days.flatMap((d) => [c.snow(d.hi), ...shown.map((m) => c.snow(d.models[m] ?? null))]),
					units === 'imperial' ? 2 : 5
				)
			])
			.range([H - M.top - M.bottom, 0])
			.nice(4)
	);
	const bw = $derived(x.bandwidth());
	// Dots sit side by side inside the day's column, in the legend's order.
	const step = $derived(Math.min(9, bw / (shown.length + 1)));
	const every = $derived(bw < 30 ? 2 : 1);
	const yy = (cm: number | null | undefined) => y(c.snow(cm ?? null) ?? 0);
</script>

<div bind:clientWidth={measured}>
	<div class="legend">
		{#each shown as m (m)}
			<span><i class="dot" style="background: {modelColor(m)}"></i>{MODEL_NAMES[m] ?? m}</span>
		{/each}
		<span><i class="bandsw"></i>Ensembles 10–90%</span>
		<span><i class="med"></i>Models’ median</span>
	</div>
	<Frame
		title="Each day, model by model"
		readout={`snow per day, ${c.snowUnit}`}
		width={W}
		height={H}
		margin={M}
		{y}
		yTicks={y.ticks(4)}
		label="Each model's snowfall for each day, with the ensemble range"
	>
		{#each days as d (d.date)}
			{@const x0 = x(d.date) ?? 0}
			{@const cx = x0 + bw / 2}
			{#if d.lo !== null && d.hi !== null}
				<rect
					class="mark band"
					x={cx - Math.min(bw, 26) / 2}
					y={yy(d.hi)}
					width={Math.min(bw, 26)}
					height={Math.max(2, yy(d.lo) - yy(d.hi))}
					rx="4"
				/>
			{/if}
			{#if d.median !== null}
				<line class="mark median" x1={x0} x2={x0 + bw} y1={yy(d.median)} y2={yy(d.median)} />
			{/if}
			{#each shown as m, k (m)}
				{@const v = d.models[m]}
				{#if v !== null && v !== undefined}
					<circle
						class="mark dot"
						cx={cx + (k - (shown.length - 1) / 2) * step}
						cy={yy(v)}
						r="3.5"
						fill={modelColor(m)}
					/>
				{/if}
			{/each}
		{/each}
		{#snippet below({ ih })}
			{#each days as d, i (d.date)}
				{#if i % every === 0}
					<text class="tick" x={(x(d.date) ?? 0) + bw / 2} y={ih + 15} text-anchor="middle"
						>{i === 0 ? 'Today' : weekday(d.date)}</text
					>
				{/if}
			{/each}
		{/snippet}
	</Frame>
</div>

<style>
	.band {
		fill: var(--ens);
	}
	.median {
		stroke: var(--text);
		stroke-width: 2;
		stroke-linecap: round;
	}
	circle.dot {
		stroke: var(--surface);
		stroke-width: 1;
	}
	.tick {
		fill: var(--text-3);
		font-size: 10.5px;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		font-size: 0.78rem;
		color: var(--text-2);
		margin-bottom: 6px;
	}
	i.dot {
		display: inline-block;
		width: 9px;
		height: 9px;
		border-radius: 50%;
		margin-right: 5px;
	}
	.bandsw {
		display: inline-block;
		width: 10px;
		height: 12px;
		background: var(--ens);
		border-radius: 3px;
		margin-right: 5px;
		vertical-align: -2px;
	}
	.med {
		display: inline-block;
		width: 14px;
		border-top: 2px solid var(--text);
		margin-right: 5px;
		vertical-align: 3px;
	}
</style>
