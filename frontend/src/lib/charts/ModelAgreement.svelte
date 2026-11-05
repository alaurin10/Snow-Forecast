<!--
  Do the models agree? Running snow totals for 15–16 days: each model as a thin
  line that stops where its data ends, the pooled ensemble 10–90% band where
  every ensemble has data, and the GEFS band (dashed) carrying on after that.
-->
<script lang="ts">
	import { scaleLinear } from 'd3-scale';
	import type { DailyRow } from '../types.gen';
	import { converters, type UnitSystem } from '../units';
	import { MODEL_NAMES, modelColor } from '../models';
	import { weekday } from '../time';
	import Frame from './Frame.svelte';
	import { bandPath, linePath, maxOf } from './geom';

	interface Props {
		daily: DailyRow[];
		models: string[];
		units: UnitSystem;
		width?: number;
	}

	let { daily, models, units, width: fixedWidth }: Props = $props();
	let measured = $state(0);

	const W = $derived(fixedWidth ?? measured);
	const c = $derived(converters(units));
	const M = { top: 10, right: 52, bottom: 22, left: 34 };
	const H = 240;
	const iw = $derived(Math.max(0, W - M.left - M.right));
	const n = $derived(daily.length);
	const x = $derived(
		scaleLinear()
			.domain([0, Math.max(1, n - 1)])
			.range([0, iw])
	);
	const xs = $derived(daily.map((_, i) => x(i)));
	const shown = $derived(
		models.filter((m) =>
			daily.some((d) => d.models_cum[m] !== null && d.models_cum[m] !== undefined)
		)
	);
	const series = $derived(
		shown.map((m) => ({ m, v: daily.map((d) => c.snow(d.models_cum[m] ?? null)) }))
	);
	const pLo = $derived(daily.map((d) => c.snow(d.pooled_cum?.p10 ?? null)));
	const pHi = $derived(daily.map((d) => c.snow(d.pooled_cum?.p90 ?? null)));
	const pMid = $derived(daily.map((d) => c.snow(d.pooled_cum?.p50 ?? null)));
	// After the pooled band stops: the GEFS band, joined at the pooled band's last day.
	const lastPooled = $derived(pHi.reduce<number>((acc, v, i) => (v !== null ? i : acc), -1));
	const tail = $derived(
		daily.map((d, i) => {
			const g = d.ens_cum['gfs_seamless'];
			return i >= lastPooled && lastPooled < n - 1 && g
				? [c.snow(g.p10), c.snow(g.p90)]
				: [null, null];
		})
	);
	const y = $derived(
		scaleLinear()
			.domain([
				0,
				maxOf(
					[...series.flatMap((s) => s.v), ...pHi, ...tail.map((t) => t[1])],
					units === 'imperial' ? 2 : 5
				)
			])
			.range([H - M.top - M.bottom, 0])
			.nice(4)
	);
	const yy = (arr: (number | null)[]) => arr.map((v) => (v === null ? null : y(v)));
	const ends = $derived.by(() => {
		// End labels at each line's last point, nudged apart so they don't collide.
		const raw = series
			.map((s) => {
				const i = s.v.reduce<number>((acc, v, k) => (v !== null ? k : acc), -1);
				return i < 0 ? null : { m: s.m, x: x(i), y: y(s.v[i]!) };
			})
			.filter((e): e is { m: string; x: number; y: number } => e !== null)
			.sort((a, b) => a.y - b.y);
		for (let k = 1; k < raw.length; k++) {
			if (raw[k].y - raw[k - 1].y < 11) raw[k].y = raw[k - 1].y + 11;
		}
		return raw;
	});
	const every = $derived(iw < 420 ? 2 : 1);
</script>

<div bind:clientWidth={measured}>
	<div class="legend">
		{#each shown as m (m)}
			<span><i class="ln" style="background: {modelColor(m)}"></i>{MODEL_NAMES[m] ?? m}</span>
		{/each}
		<span><i class="bandsw"></i>Ensembles 10–90%</span>
		{#if lastPooled < n - 1}<span><i class="dash"></i>GEFS only</span>{/if}
	</div>
	<Frame
		title="Do the models agree?"
		readout={`running total, ${c.snowUnit}`}
		width={W}
		height={H}
		margin={M}
		{y}
		yTicks={y.ticks(4)}
		label="Running snowfall totals for each model and the ensemble range"
	>
		{#snippet children({ iw })}
			<path class="mark pooled" d={bandPath(xs, yy(pLo), yy(pHi))} />
			<path class="mark median" d={linePath(xs, yy(pMid))} />
			<path class="mark tail" d={linePath(xs, yy(tail.map((t) => t[0])))} />
			<path class="mark tail" d={linePath(xs, yy(tail.map((t) => t[1])))} />
			{#each series as s (s.m)}
				<path class="mark model" stroke={modelColor(s.m)} d={linePath(xs, yy(s.v))} />
			{/each}
			{#each ends as e (e.m)}
				<circle cx={e.x} cy={e.y} r="2.5" fill={modelColor(e.m)} />
				<text class="end" x={Math.min(e.x + 5, iw + 6)} y={e.y} dy="0.32em"
					>{MODEL_NAMES[e.m] ?? e.m}</text
				>
			{/each}
		{/snippet}
		{#snippet below({ ih })}
			{#each daily as d, i (d.date)}
				{#if i % every === 0}
					<text class="tick" x={x(i)} y={ih + 15} text-anchor="middle"
						>{i === 0 ? 'Today' : weekday(d.date)}</text
					>
				{/if}
			{/each}
		{/snippet}
	</Frame>
</div>

<style>
	.pooled {
		fill: var(--ens);
	}
	.median {
		fill: none;
		stroke: var(--ens-line);
		stroke-width: 1.5;
		stroke-dasharray: 1 0;
	}
	.tail {
		fill: none;
		stroke: var(--ens-line);
		stroke-width: 1.2;
		stroke-dasharray: 4 3;
	}
	.model {
		fill: none;
		stroke-width: 2;
		stroke-linejoin: round;
	}
	.end {
		fill: var(--text-2);
		font-size: 10.5px;
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
	.ln {
		display: inline-block;
		width: 14px;
		height: 2px;
		margin-right: 5px;
		vertical-align: 3px;
	}
	.bandsw {
		display: inline-block;
		width: 14px;
		height: 10px;
		background: var(--ens);
		border-radius: 2px;
		margin-right: 5px;
		vertical-align: -1px;
	}
	.dash {
		display: inline-block;
		width: 14px;
		border-top: 1.5px dashed var(--ens-line);
		margin-right: 5px;
		vertical-align: 3px;
	}
</style>
