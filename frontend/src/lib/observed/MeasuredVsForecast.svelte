<!--
  The forecast check, day by day, for the last 30 days, each day against what the app
  forecast the evening before. New snow: the station's depth gain beside the consensus
  as settled snow; days the depth can't measure (bare ground, above freezing all day)
  are shaded and left out of the score. Precipitation: the gauge's catch beside the
  forecast's water, snow and rain alike. Three numbers sum each up; the per-model
  scores are on the Confidence tab.
-->
<script lang="ts">
	import { scaleBand, scaleLinear } from 'd3-scale';
	import type { VerificationOut } from '../types.gen';
	import { depthRow, waterRow } from '../scores';
	import { converters, elevation, type UnitSystem } from '../units';
	import { monthDay } from '../time';
	import type { LoadState } from '../load';
	import Frame from '../charts/Frame.svelte';
	import { maxOf, roundedTopBar } from '../charts/geom';
	import { forecastSnow, forecastWater, snowAtStation, waterAtStation } from './read';

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
	const atStation = $derived(data ? snowAtStation(data) : false);
	const wAtStation = $derived(data ? waterAtStation(data) : false);
	const where = $derived(
		data?.station_elev_m != null
			? `the station’s own elevation (${elevation(data.station_elev_m, units)})`
			: 'the station’s own spot'
	);
	const num = (cm: number | null | undefined) => c.snow(cm ?? null)?.toFixed(c.snowDigits) ?? '–';
	const wnum = (mm: number | null | undefined) =>
		c.water(mm ?? null)?.toFixed(c.waterDigits) ?? '–';
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
	const H = 180;
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
	const obs = $derived(pairs.map((p) => (p.skip ? null : c.snow(p.observed_cm))));
	const fc = $derived(pairs.map((p) => c.snow(data ? forecastSnow(data, p) : null)));
	const y = $derived(
		scaleLinear()
			.domain([0, maxOf([...obs, ...fc], units === 'imperial' ? 2 : 5)])
			.range([ih, 0])
			.nice(3)
	);
	const hasSnow = $derived((data?.n_days ?? 0) > 0);
	const hasWater = $derived(pairs.some((p) => p.observed_water_mm != null));
	const wObs = $derived(pairs.map((p) => c.water(p.observed_water_mm ?? null)));
	const wFc = $derived(pairs.map((p) => c.water(data ? forecastWater(data, p) : null)));
	const yw = $derived(
		scaleLinear()
			.domain([0, maxOf([...wObs, ...wFc], units === 'imperial' ? 0.5 : 10)])
			.range([ih, 0])
			.nice(3)
	);
	const ratio = $derived(data?.settled_ratio ?? 8);

	let choice = $state<'snow' | 'water' | null>(null);
	// New snow first; the gauge alone while the depth can't check anything.
	const view = $derived(choice ?? (hasSnow || !hasWater ? 'snow' : 'water'));

	interface Stat {
		label: string;
		value: string;
		unit?: string;
	}
	const lean = (bias: number | null, near: number, f: (v: number) => string, unit: string) => {
		if (bias === null) return { value: '–' };
		if (Math.abs(bias) < near) return { value: 'None' };
		return { value: `${bias > 0 ? '+' : '−'}${f(Math.abs(bias))}`, unit: `${unit}/day` };
	};
	const stats = $derived.by<Stat[]>(() => {
		if (view === 'snow') {
			if (!snowRow) return [];
			return [
				{ label: 'Typical miss', value: num(snowRow.mae_cm), unit: `${c.snowUnit}/day` },
				{ label: 'Lean', ...lean(snowRow.bias_cm, 0.5, num, c.snowUnit) },
				{ label: 'Days scored', value: String(snowRow.n) }
			];
		}
		if (!rainRow) return [];
		return [
			{ label: 'Typical miss', value: wnum(rainRow.mae_mm), unit: `${c.waterUnit}/day` },
			{ label: 'Lean', ...lean(rainRow.bias_mm, 1, wnum, c.waterUnit) },
			{ label: 'Days scored', value: String(rainRow.n) }
		];
	});
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

<section class="card" aria-labelledby="check-h">
	<div class="cardhead">
		<h2 id="check-h">Forecast check, day by day</h2>
		{#if data?.ready && hasSnow && hasWater}
			<div class="seg" role="group" aria-label="What to check">
				<button aria-pressed={view === 'snow'} onclick={() => (choice = 'snow')}>New snow</button>
				<button aria-pressed={view === 'water'} onclick={() => (choice = 'water')}
					>Precipitation</button
				>
			</div>
		{/if}
	</div>
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
		{#if stats.length}
			<div class="stats">
				{#each stats as s (s.label)}
					<div>
						<span class="eyebrow">{s.label}</span>
						<span class="stat num"
							>{s.value}{#if s.unit}<small>{s.unit}</small>{/if}</span
						>
					</div>
				{/each}
			</div>
		{/if}
		<div bind:clientWidth={measured}>
			{#if view === 'snow'}
				{#if hasSnow}
					<p class="muted small lede">
						The depth gain at {data.station_name ?? 'the station'} beside the forecast for {atStation
							? where
							: 'mid-mountain'}{settled ? `, as settled snow (${ratio}:1)` : ''}.
					</p>
					<Frame
						title="Observed vs forecast new snow"
						readout={`${c.snowUnit} a day`}
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
						<span><i class="sw obs"></i>Measured</span>
						<span><i class="sw fc"></i>Forecast the evening before</span>
						{#if skipped}<span><i class="sw skip"></i>Not measurable</span>{/if}
					</div>
				{:else}
					<p class="muted small">
						The snow depth can’t check the forecast yet: {data.station_name ?? 'the station'} has had
						no snowpack to measure on, or stayed above freezing, on every day so far.
					</p>
				{/if}
			{:else}
				<p class="muted small lede">
					Rain and melted snow in the station’s gauge beside the forecast for {wAtStation
						? where
						: 'mid-mountain'}.
				</p>
				<Frame
					title="Observed vs forecast precipitation"
					readout={`${c.waterUnit} a day`}
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
		<details class="how">
			<summary>How this is measured</summary>
			<p>
				New snow is the station's depth gain over the day{pairs.some((p) => p.from_swe)
					? ' (or its snow-water gain × 10 where it has no depth sensor)'
					: ''}, so the forecast's snow water is shown as settled snow, denser than fresh.{skipped
					? ` ${skipped} day${skipped === 1 ? '' : 's'} (${skipWhy}) can't be measured that way and are left out of its score.`
					: ''}
				The gauge checks the amount, rain or snow, but catches less than falls in wind-driven snow. “Typical
				miss” is the average gap between forecast and measured on a day; “Lean” is whether the forecast
				tends to be too high (+) or too low (−). Each model’s score is on the Confidence tab.
			</p>
		</details>
	{/if}
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
	.small {
		font-size: 0.85rem;
	}
	.lede {
		margin: 0 0 8px;
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 8px;
		margin: 0 0 12px;
	}
	.stats div {
		display: grid;
		gap: 1px;
	}
	.stat {
		font-family: var(--font-num);
		font-size: 1.35rem;
		font-weight: 600;
		letter-spacing: -0.02em;
		line-height: 1.2;
	}
	.stat small {
		font-family: var(--font-ui);
		font-size: 0.74rem;
		font-weight: 500;
		letter-spacing: 0;
		margin-left: 3px;
		color: var(--text-2);
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
