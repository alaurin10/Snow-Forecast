<!-- How the forecast changed: the next-5-day consensus as issued by recent runs. -->
<script lang="ts">
	import { scaleLinear } from 'd3-scale';
	import type { TrendRun } from '../types.gen';
	import { converters, type UnitSystem } from '../units';
	import Frame from './Frame.svelte';
	import { linePath, maxOf } from './geom';
	import { monthDay } from '../time';

	interface Props {
		runs: TrendRun[];
		units: UnitSystem;
		width?: number;
	}

	let { runs, units, width: fixedWidth }: Props = $props();
	let measured = $state(0);

	const W = $derived(fixedWidth ?? measured);
	const c = $derived(converters(units));
	const M = { top: 10, right: 14, bottom: 22, left: 34 };
	const H = 150;
	const pts = $derived(runs.filter((r) => r.next5_cm !== null));
	const vals = $derived(pts.map((r) => c.snow(r.next5_cm)));
	const iw = $derived(Math.max(0, W - M.left - M.right));
	const x = $derived(
		scaleLinear()
			.domain([0, Math.max(1, pts.length - 1)])
			.range([0, iw])
	);
	const y = $derived(
		scaleLinear()
			.domain([0, maxOf(vals, units === 'imperial' ? 2 : 5)])
			.range([H - M.top - M.bottom, 0])
			.nice(3)
	);
	const label = (iso: string) => `${monthDay(iso.slice(0, 10))} ${iso.slice(11, 13)}Z`;
</script>

<div bind:clientWidth={measured}>
	<Frame
		title="How the forecast changed"
		readout={vals.length
			? `latest ${vals.at(-1)?.toFixed(c.snowDigits)} ${c.snowUnit} · next 5 days`
			: ''}
		width={W}
		height={H}
		margin={M}
		{y}
		yTicks={y.ticks(3)}
		label="Next five day snowfall as forecast by each recent run"
	>
		{#snippet children({ ih })}
			{#if pts.length >= 2}
				<path
					class="mark line"
					d={linePath(
						pts.map((_, i) => x(i)),
						vals.map((v) => (v === null ? null : y(v)))
					)}
				/>
				{#each pts as r, i (r.run_id)}
					<circle class="mark" cx={x(i)} cy={y(vals[i] ?? 0)} r="4" />
				{/each}
			{:else}
				<text class="empty" x="8" y={ih / 2}>Shows once there are two or more runs.</text>
			{/if}
		{/snippet}
		{#snippet below({ ih })}
			{#if pts.length >= 2}
				<text class="tick" x="0" y={ih + 15}>{label(pts[0].issued_at)}</text>
				<text class="tick" x={iw} y={ih + 15} text-anchor="end">{label(pts.at(-1)!.issued_at)}</text
				>
			{/if}
		{/snippet}
	</Frame>
</div>

<style>
	.line {
		fill: none;
		stroke: var(--snow);
		stroke-width: 2;
	}
	circle.mark {
		fill: var(--snow);
		stroke: var(--surface);
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
