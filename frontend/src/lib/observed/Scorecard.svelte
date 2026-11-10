<!--
  How well the next-day forecast matched the snow station, per source. Bias is
  forecast minus observed (positive = too much snow forecast). "Big days" counts
  days with at least 3 in (7.6 cm) observed or forecast.
-->
<script lang="ts">
	import { hscroll } from '../hscroll';
	import { scaleBand, scaleLinear } from 'd3-scale';
	import type { VerificationOut } from '../types.gen';
	import { MODEL_NAMES } from '../models';
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
	// The server's threshold for a big day is 7.62 cm (3 in).
	const bigDay = $derived(units === 'imperial' ? '3 in' : '8 cm');

	const NAMES: Record<string, string> = {
		cons: 'Consensus (model depth)',
		cons_slr: 'Consensus (snow-ratio depth)',
		ens_p50: 'Ensemble median'
	};
	const name = (s: string) => NAMES[s] ?? MODEL_NAMES[s] ?? s;
	const signed = (cm: number | null | undefined) => {
		const v = c.snow(cm ?? null);
		if (v === null) return '–';
		return `${v > 0 ? '+' : ''}${v.toFixed(c.snowDigits)}`;
	};
	const num = (cm: number | null | undefined) => c.snow(cm ?? null)?.toFixed(c.snowDigits) ?? '–';
	const better = $derived.by(() => {
		const raw = data?.rows.find((r) => r.source === 'cons');
		const slr = data?.rows.find((r) => r.source === 'cons_slr');
		if (!raw || !slr || raw.mae_cm === null || slr.mae_cm === null) return null;
		if (Math.abs(raw.mae_cm - slr.mae_cm) < 0.5) return 'about the same';
		return slr.mae_cm < raw.mae_cm ? 'snow-ratio depth is closer' : 'model depth is closer';
	});

	// Chart: observed vs consensus forecast per day, one scale.
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
	const obs = $derived(pairs.map((p) => c.snow(p.observed_cm)));
	const fc = $derived(pairs.map((p) => c.snow(p.cons_cm)));
	const y = $derived(
		scaleLinear()
			.domain([0, maxOf([...obs, ...fc], units === 'imperial' ? 2 : 5)])
			.range([ih, 0])
			.nice(3)
	);
	const bw = $derived(x.bandwidth() / 2);
</script>

<section class="card">
	<h2>Forecast scorecard</h2>
	{#if load === 'loading'}
		<p class="muted small" aria-live="polite">Loading the scorecard…</p>
	{:else if load === 'error'}
		<p class="muted small" role="alert">Couldn’t load the scorecard. Try again in a moment.</p>
	{:else if !data || !data.station}
		<p class="muted small">The scorecard needs a snow station for this location.</p>
	{:else if !data.ready}
		<p class="muted small">
			The scorecard fills in after about a week of forecasts{data.n_days
				? ` (${data.n_days} day${data.n_days === 1 ? '' : 's'} so far; ${data.needs_days} to go)`
				: ''}. It compares each day's forecast, made the evening before, with what
			{data.station_name ?? 'the station'} measured.
		</p>
	{:else}
		<p class="muted small">
			Next-day forecasts since {monthDay(data.since ?? '')} ({data.n_days} days) against {data.station_name}
			{#if data.station_elev_m !== null}
				at {elevation(data.station_elev_m, units)} (mid-mountain is {elevation(
					data.band_elev_m,
					units
				)}){/if}.
			{#if better}<strong>Raw vs snow-ratio: {better}.</strong>{/if}
		</p>
		<p class="faint small key">
			{c.snowUnit} per day. Bias: forecast minus observed. Error: the average miss. Big days ({bigDay}
			or more): caught / missed / false alarms.
		</p>
		<div class="table-wrap" use:hscroll>
			<table class="data">
				<thead>
					<tr>
						<th>Source</th>
						<th title="Average forecast minus observed">Bias</th>
						<th title="Average size of the miss">Error</th>
						<th title={`Days of ${bigDay} or more: caught / missed / false alarms`}>Big days</th>
						<th title="Days compared">n</th>
					</tr>
				</thead>
				<tbody>
					{#each data.rows as r (r.source)}
						<tr class:hl={r.source === 'cons' || r.source === 'cons_slr'}>
							<th scope="row">{name(r.source)}</th>
							<td class="num">{signed(r.bias_cm)}</td>
							<td class="num">{num(r.mae_cm)}</td>
							<td class="num">{r.hits} / {r.misses} / {r.false_alarms}</td>
							<td class="num">{r.n}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<div bind:clientWidth={measured}>
			<Frame
				title="Observed vs forecast, day by day"
				readout={`${c.snowUnit}`}
				width={W}
				height={H}
				margin={M}
				{y}
				yTicks={y.ticks(3)}
				label="Observed new snow and the consensus forecast for each day"
			>
				{#snippet children({ ih: plotH })}
					{#each pairs as p, i (p.date)}
						{@const x0 = x(p.date) ?? 0}
						{#if (obs[i] ?? 0) > 0}
							<path class="mark obs" d={roundedTopBar(x0, y(obs[i]!), bw, plotH - y(obs[i]!), 2)} />
						{/if}
						{#if (fc[i] ?? 0) > 0}
							<path
								class="mark fc"
								d={roundedTopBar(x0 + bw, y(fc[i]!), bw, plotH - y(fc[i]!), 2)}
							/>
						{/if}
					{/each}
				{/snippet}
				{#snippet below()}
					{#if pairs.length >= 2}
						<text class="tick" x="0" y={ih + 15}>{monthDay(pairs[0].date)}</text>
						<text class="tick" x={iw} y={ih + 15} text-anchor="end"
							>{monthDay(pairs.at(-1)!.date)}</text
						>
					{/if}
				{/snippet}
			</Frame>
			<div class="legend">
				<span><i class="sw obs"></i>Observed</span>
				<span><i class="sw fc"></i>Forecast the evening before</span>
			</div>
		</div>
		<p class="faint small">
			Observed new snow is the station's depth gain over the day{pairs.some((p) => p.from_swe)
				? ' (or its snow-water gain × 10 where it has no depth sensor)'
				: ''}. Settling and wind make it an imperfect check; bias over weeks is what matters.
		</p>
	{/if}
</section>

<style>
	h2 {
		margin: 0 0 4px;
	}
	.small {
		font-size: 0.85rem;
	}
	.key {
		margin: 6px 0 4px;
	}
	.hl th,
	.hl td {
		font-weight: 600;
	}
	.obs {
		fill: var(--snow);
	}
	.fc {
		fill: var(--text-3);
	}
	.tick {
		fill: var(--text-3);
		font-size: 10.5px;
	}
	.legend {
		display: flex;
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
</style>
