<!--
  Did the forecast verify? Each day's measured new snow at the station beside what the
  app forecast the evening before, for the last 30 days. The per-model scores are on the
  Confidence tab.
-->
<script lang="ts">
	import { scaleBand, scaleLinear } from 'd3-scale';
	import type { VerificationOut } from '../types.gen';
	import { headlineRow } from '../scores';
	import { converters, type UnitSystem } from '../units';
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
	const headline = $derived(data?.headline ?? 'cons');
	const ours = $derived(data ? headlineRow(data) : null);
	const num = (cm: number | null | undefined) => c.snow(cm ?? null)?.toFixed(c.snowDigits) ?? '–';
	const lean = $derived.by(() => {
		if (!ours || ours.bias_cm === null) return null;
		if (Math.abs(ours.bias_cm) < 0.5) return 'no lean either way';
		return `${num(Math.abs(ours.bias_cm))} ${c.snowUnit} a day too ${ours.bias_cm > 0 ? 'much' : 'little'}`;
	});

	const W = $derived(fixedWidth ?? measured);
	const M = { top: 8, right: 8, bottom: 22, left: 32 };
	const H = 190;
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
	const fc = $derived(
		pairs.map((p) => c.snow(headline === 'cons_slr' ? p.cons_slr_cm : p.cons_cm))
	);
	const y = $derived(
		scaleLinear()
			.domain([0, maxOf([...obs, ...fc], units === 'imperial' ? 2 : 5)])
			.range([ih, 0])
			.nice(3)
	);
	const bw = $derived(x.bandwidth() / 2);
</script>

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
				: ''}: each day’s measured new snow beside what was forecast the evening before.
		</p>
	{:else}
		<p class="muted small">
			Each day’s new snow at {data.station_name ?? 'the station'} beside the forecast made the evening
			before{#if ours && ours.mae_cm !== null}. Over {data.n_days} days the forecast has missed by {num(
					ours.mae_cm
				)}
				{c.snowUnit} a day on average{lean ? `, with ${lean}` : ''}{/if}.
		</p>
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
				: ''}. Settling and wind make it an imperfect check; the lean over weeks is what matters.
			Each model’s score is on the Confidence tab.
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
