<!-- Each day's low to high temperature as a floating bar, with the freezing line drawn
     across. A day whose high went above freezing is tinted warm. Shares its day bands,
     and optionally a crosshair, with DailySeries and DailyBars. -->
<script lang="ts">
	import { scaleBand, scaleLinear } from 'd3-scale';
	import Frame from './Frame.svelte';
	import { bandIndex, finite } from './geom';
	import { monthDay } from '../time';

	interface Props {
		title: string;
		dates: string[];
		/** Already in display units. */
		lo: (number | null)[];
		hi: (number | null)[];
		unit: string;
		/** Freezing, in display units (0 or 32). */
		freezing: number;
		width?: number;
		height?: number;
		index?: number | null;
		onindex?: (i: number) => void;
		onleave?: () => void;
	}

	let {
		title,
		dates,
		lo,
		hi,
		unit,
		freezing,
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
	const all = $derived(finite([...lo, ...hi]));
	const any = $derived(all.length > 0);
	// Always show the freezing line, with a little room either side of it.
	const span = $derived(unit === '°F' ? 10 : 5);
	const y = $derived(
		scaleLinear()
			.domain([Math.min(freezing - span, ...all), Math.max(freezing + span, ...all)])
			.range([ih, 0])
			.nice(4)
	);
	const r = (v: number) => Math.round(v);
	const readout = $derived.by(() => {
		if (index !== null && dates[index]) {
			const l = lo[index];
			const h = hi[index];
			const v = l === null || h === null ? '–' : `${r(l)}° to ${r(h)}${unit}`;
			return `${monthDay(dates[index])}: ${v}`;
		}
		if (!any) return 'no data';
		const h = finite(hi.slice(-7));
		return h.length ? `highest this week ${r(Math.max(...h))}${unit}` : '';
	});
</script>

<div bind:clientWidth={measured}>
	<Frame
		{title}
		{readout}
		width={W}
		{height}
		margin={M}
		{y}
		yTicks={y.ticks(4)}
		label={`${title}, daily low and high, ${unit}`}
		crossX={index === null || !dates[index] ? null : (x(dates[index]) ?? 0) + x.bandwidth() / 2}
		onpointer={onindex ? (px) => onindex(bandIndex(x, dates.length, px)) : undefined}
		{onleave}
	>
		{#snippet children({ iw: plotW })}
			{#if any}
				<line class="freeze" x1="0" x2={plotW} y1={y(freezing)} y2={y(freezing)} />
				{#each dates as d, i (d)}
					{@const l = lo[i]}
					{@const h = hi[i]}
					{#if l !== null && h !== null}
						{@const top = y(Math.max(l, h))}
						<rect
							class="mark day"
							class:warm={h > freezing}
							x={x(d) ?? 0}
							y={top}
							width={x.bandwidth()}
							height={Math.max(2, y(Math.min(l, h)) - top)}
							rx={Math.min(3, x.bandwidth() / 2)}
						/>
					{/if}
				{/each}
			{:else}
				<text class="empty" x="8" y={ih / 2}>No temperatures from this station.</text>
			{/if}
		{/snippet}
		{#snippet below()}
			{#if dates.length >= 2}
				<text class="tick" x="0" y={ih + 15}>{monthDay(dates[0])}</text>
				<text class="tick" x={iw} y={ih + 15} text-anchor="end">{monthDay(dates.at(-1)!)}</text>
			{/if}
		{/snippet}
	</Frame>
	{#if any}
		<div class="legend">
			<span><i class="sw warm"></i>High above freezing</span>
			<span><i class="sw"></i>Below freezing all day</span>
			<span><i class="sw line"></i>Freezing</span>
		</div>
	{/if}
</div>

<style>
	.day {
		fill: var(--snow);
		opacity: 0.75;
	}
	.day.warm {
		fill: var(--temp);
	}
	.freeze {
		stroke: var(--text-2);
		stroke-width: 1;
		stroke-dasharray: 3 3;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		margin-top: 4px;
		font-size: 0.78rem;
		color: var(--text-2);
	}
	.sw {
		display: inline-block;
		width: 10px;
		height: 10px;
		margin-right: 4px;
		border-radius: 2px;
		background: var(--snow);
		opacity: 0.75;
		vertical-align: -1px;
	}
	.sw.warm {
		background: var(--temp);
	}
	.sw.line {
		height: 0;
		border-top: 1.5px dashed var(--text-2);
		background: none;
		border-radius: 0;
		vertical-align: 3px;
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
