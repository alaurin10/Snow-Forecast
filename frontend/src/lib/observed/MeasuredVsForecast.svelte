<!--
  Did the forecast verify? Two checks for the last 30 days, each against what the app
  forecast the evening before. New snow: the station's depth gain beside the consensus
  as settled snow; days the depth can't measure (bare ground, above freezing all day)
  are shaded and left out of the score. Precipitation: the gauge's catch beside the
  forecast's water, snow and rain alike. The per-model scores are on the Confidence tab.
-->
<script lang="ts">
	import { scaleBand, scaleLinear } from 'd3-scale';
	import type { VerificationOut, VerificationPair } from '../types.gen';
	import { depthRow, waterRow } from '../scores';
	import { converters, elevation, type UnitSystem } from '../units';
	import { monthDay } from '../time';
	import type { LoadState } from '../load';
	import Frame from '../charts/Frame.svelte';
	import { maxOf, roundedTopBar } from '../charts/geom';

	interface Props {
		data: VerificationOut | null;
		units: UnitSystem;
		width?: number;
		load?: LoadState;
	}

	let { data, units, width: fixedWidth, load = 'ready' }: Props = $props();
	let measured = $state(0);
	const c = $derived(converters(units));
	const snowRow = $derived(data ? depthRow(data) : null);
	const rainRow = $derived(data ? waterRow(data) : null);
	const settled = $derived(snowRow?.source === 'cons_settled' || snowRow?.source === 'stn_settled');
	// The forecast for the station's own spot and elevation, once it has a week of days.
	const atStation = $derived(snowRow?.source === 'stn_settled');
	const wAtStation = $derived(rainRow?.source === 'stn_cons');
	const where = $derived(
		data?.station_elev_m != null
			? ` for the station’s own elevation (${elevation(data.station_elev_m, units)})`
			: ' for the station’s own spot'
	);
	const num = (cm: number | null | undefined) => c.snow(cm ?? null)?.toFixed(c.snowDigits) ?? '–';
	const wnum = (mm: number | null | undefined) =>
		c.water(mm ?? null)?.toFixed(c.waterDigits) ?? '–';
	const snowLean = $derived.by(() => {
		if (!snowRow || snowRow.bias_cm === null) return null;
		if (Math.abs(snowRow.bias_cm) < 0.5) return 'no lean either way';
		return `${num(Math.abs(snowRow.bias_cm))} ${c.snowUnit} a day too ${snowRow.bias_cm > 0 ? 'much' : 'little'}`;
	});
	const waterLean = $derived.by(() => {
		if (!rainRow || rainRow.bias_mm === null) return null;
		if (Math.abs(rainRow.bias_mm) < 1) return 'no lean either way';
		return `${wnum(Math.abs(rainRow.bias_mm))} ${c.waterUnit} a day too ${rainRow.bias_mm > 0 ? 'much' : 'little'}`;
	});
	const skipped = $derived((data?.skipped_bare ?? 0) + (data?.skipped_warm ?? 0));
	const skipWhy = $derived.by(() => {
		const bare = data?.skipped_bare ?? 0;
		const warm = data?.skipped_warm ?? 0;
		const parts = [
			bare ? `${bare} with no snowpack on the ground` : '',
			warm ? `${warm} above freezing all day` : ''
		].filter(Boolean);
		return parts.join(' and ');
	});

	const W = $derived(fixedWidth ?? measured);
	const M = { top: 8, right: 8, bottom: 22, left: 32 };
	const H = 170;
	const ih = H - M.top - M.bottom;
	const iw = $derived(Math.max(0, W - M.left - M.right));
	const pairs = $derived(data?.pairs ?? []);
	const x = $derived(
		scaleBand<string>()
			.domain(pairs.map((p) => p.date))
			.range([0, iw])
			.paddingInner(0.25)
	);
	const bw = $derived(x.bandwidth() / 2);
	const fcSnow = (p: VerificationPair) =>
		atStation
			? p.stn_settled_cm
			: (p.cons_settled_cm ?? (data?.headline === 'cons_slr' ? p.cons_slr_cm : p.cons_cm));
	const obs = $derived(pairs.map((p) => (p.skip ? null : c.snow(p.observed_cm))));
	const fc = $derived(pairs.map((p) => c.snow(fcSnow(p) ?? null)));
	const y = $derived(
		scaleLinear()
			.domain([0, maxOf([...obs, ...fc], units === 'imperial' ? 2 : 5)])
			.range([ih, 0])
			.nice(3)
	);
	const hasWater = $derived(pairs.some((p) => p.observed_water_mm != null));
	const wObs = $derived(pairs.map((p) => c.water(p.observed_water_mm ?? null)));
	const wFc = $derived(
		pairs.map((p) => c.water((wAtStation ? p.stn_water_mm : p.cons_water_mm) ?? null))
	);
	const yw = $derived(
		scaleLinear()
			.domain([0, maxOf([...wObs, ...wFc], units === 'imperial' ? 0.5 : 10)])
			.range([ih, 0])
			.nice(3)
	);
	const ratio = $derived(data?.settled_ratio ?? 8);
</script>

{#snippet dates()}
	{#if pairs.length >= 2}
		<text class="tick" x="0" y={ih + 15}>{monthDay(pairs[0].date)}</text>
		<text class="tick" x={iw} y={ih + 15} text-anchor="end">{monthDay(pairs.at(-1)!.date)}</text>
	{/if}
{/snippet}

{#snippet bars(ob: (number | null)[], fo: (number | null)[], ys: typeof y, plotH: number)}
	{#each pairs as p, i (p.date)}
		{@const x0 = x(p.date) ?? 0}
		{#if (ob[i] ?? 0) > 0}
			<path class="mark obs" d={roundedTopBar(x0, ys(ob[i]!), bw, plotH - ys(ob[i]!), 2)} />
		{/if}
		{#if (fo[i] ?? 0) > 0}
			<path class="mark fc" d={roundedTopBar(x0 + bw, ys(fo[i]!), bw, plotH - ys(fo[i]!), 2)} />
		{/if}
	{/each}
{/snippet}

<section class="card">
	<h2>Measured against the forecast</h2>
	{#if load === 'loading'}
		<p class="muted small" aria-live="polite">Loading the comparison…</p>
	{:else if load === 'error'}
		<p class="muted small" role="alert">Couldn’t load the comparison. Try again in a moment.</p>
	{:else if !data || !data.station}
		<p class="muted small">Comparing needs a snow station for this location.</p>
	{:else if !data.ready}
		<p class="muted small">
			This fills in after about a week of forecasts{data.n_days
				? ` (${data.n_days} day${data.n_days === 1 ? '' : 's'} so far; ${data.needs_days} to go)`
				: ''}: each day’s measured new snow and precipitation beside what was forecast the evening
			before.
		</p>
	{:else}
		<div bind:clientWidth={measured}>
			<h3>New snow</h3>
			{#if data.n_days > 0}
				<p class="muted small">
					The depth gain at {data.station_name ?? 'the station'} beside the forecast made the evening
					before{atStation ? where : ''}{settled
						? `, as settled snow (${ratio}:1)`
						: ''}{#if snowRow && snowRow.mae_cm !== null}. Over {snowRow.n} days it has missed by {num(
							snowRow.mae_cm
						)}
						{c.snowUnit} a day on average{snowLean ? `, with ${snowLean}` : ''}{/if}.
				</p>
				<Frame
					title="Observed vs forecast new snow, day by day"
					readout={`${c.snowUnit}`}
					width={W}
					height={H}
					margin={M}
					{y}
					yTicks={y.ticks(3)}
					label="Observed new snow and the consensus forecast for each day"
				>
					{#snippet children({ ih: plotH })}
						{#each pairs as p (p.date)}
							{#if p.skip}
								<rect
									class="skip"
									x={x(p.date) ?? 0}
									y="0"
									width={x.bandwidth()}
									height={plotH}
									rx="2"
								/>
							{/if}
						{/each}
						{@render bars(obs, fc, y, plotH)}
					{/snippet}
					{#snippet below()}{@render dates()}{/snippet}
				</Frame>
				<div class="legend">
					<span><i class="sw obs"></i>Observed</span>
					<span><i class="sw fc"></i>Forecast the evening before</span>
					{#if skipped}<span><i class="sw skip"></i>Not measurable</span>{/if}
				</div>
			{:else}
				<p class="muted small">
					The snow depth can’t check the forecast yet: {data.station_name ?? 'the station'} has had no
					snowpack to measure on, or stayed above freezing, on every day so far. The precipitation below
					still can.
				</p>
			{/if}

			{#if hasWater}
				<h3>Precipitation</h3>
				<p class="muted small">
					Rain and melted snow in the station’s gauge beside the forecast’s{wAtStation
						? where
						: ''}{#if rainRow && rainRow.mae_mm !== null}. Over {rainRow.n} days it has missed by {wnum(
							rainRow.mae_mm
						)}
						{c.waterUnit} a day on average{waterLean ? `, with ${waterLean}` : ''}{/if}.
				</p>
				<Frame
					title="Observed vs forecast precipitation, day by day"
					readout={`${c.waterUnit}`}
					width={W}
					height={H}
					margin={M}
					y={yw}
					yTicks={yw.ticks(3)}
					yFormat={(v) => (units === 'imperial' ? v.toFixed(v % 1 ? 1 : 0) : String(v))}
					label="Precipitation in the station's gauge and the consensus forecast for each day"
				>
					{#snippet children({ ih: plotH })}{@render bars(wObs, wFc, yw, plotH)}{/snippet}
					{#snippet below()}{@render dates()}{/snippet}
				</Frame>
				<div class="legend">
					<span><i class="sw obs"></i>Gauge</span>
					<span><i class="sw fc"></i>Forecast the evening before</span>
				</div>
			{/if}
		</div>
		<p class="faint small">
			New snow is the station's depth gain over the day{pairs.some((p) => p.from_swe)
				? ' (or its snow-water gain × 10 where it has no depth sensor)'
				: ''}, so the forecast's snow water is shown as settled snow, denser than fresh.{skipped
				? ` ${skipped} day${skipped === 1 ? '' : 's'} (${skipWhy}) can't be measured that way and are left out of its score.`
				: ''}
			The gauge checks the amount, rain or snow, but catches less than falls in wind-driven snow. Each
			model’s score is on the Confidence tab.
		</p>
	{/if}
</section>

<style>
	h2 {
		margin: 0 0 4px;
	}
	h3 {
		margin: 14px 0 2px;
		font-size: 0.95rem;
	}
	.small {
		font-size: 0.85rem;
	}
	.obs {
		fill: var(--snow);
	}
	.fc {
		fill: var(--text-3);
	}
	.skip {
		fill: var(--text-3);
		opacity: 0.12;
	}
	.tick {
		fill: var(--text-3);
		font-size: 10.5px;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
		font-size: 0.78rem;
		color: var(--text-2);
		margin-top: 4px;
	}
	.sw {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 2px;
		margin-right: 4px;
	}
	.sw.obs {
		background: var(--snow);
	}
	.sw.fc {
		background: var(--text-3);
	}
	.sw.skip {
		background: var(--text-3);
		opacity: 0.3;
	}
</style>
