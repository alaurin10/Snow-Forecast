<!--
  Did the forecast get it right? The simple answer: the forecast's total beside what the
  station measured over the same days, on one scale, and one sentence on how it leans.
  The day-by-day check is further down the tab.
-->
<script lang="ts">
	import type { LoadState } from '../load';
	import type { VerificationOut } from '../types.gen';
	import { snow, water, type UnitSystem } from '../units';
	import { forecastVerdict } from './read';

	interface Props {
		data: VerificationOut | null;
		units: UnitSystem;
		load?: LoadState;
	}

	let { data, units, load = 'ready' }: Props = $props();
	const v = $derived(data ? forecastVerdict(data, units) : null);
	const top = $derived(v ? Math.max(v.forecast, v.observed, 1e-6) : 1);
	const fmt = (n: number) => (v?.kind === 'water' ? water(n, units) : snow(n, units));
	const leanWord = $derived(
		v ? { close: 'About right', high: 'Ran high', low: 'Ran low' }[v.lean] : ''
	);
</script>

<section class="card" aria-labelledby="verdict-h">
	<div class="head">
		<h2 id="verdict-h">Did the forecast get it right?</h2>
		{#if v}<span class="pill {v.lean}">{leanWord}</span>{/if}
	</div>
	{#if load === 'loading'}
		<p class="muted small" aria-live="polite">Loading the comparison…</p>
	{:else if load === 'error'}
		<p class="muted small" role="alert">Couldn’t load the comparison. Try again in a moment.</p>
	{:else if !data || !data.station}
		<p class="muted small">Checking the forecast needs a snow station for this location.</p>
	{:else if !data.ready}
		<p class="muted small">
			This fills in after about a week of forecasts{data.n_days
				? ` (${data.n_days} day${data.n_days === 1 ? '' : 's'} so far; ${data.needs_days} to go)`
				: ''}.
		</p>
	{:else if !v}
		<p class="muted small">No days to compare yet.</p>
	{:else}
		<p class="muted small sub">
			{v.kind === 'snow' ? 'New snow' : 'Precipitation'} over the last {v.days} day{v.days === 1
				? ''
				: 's'} checked, forecast the evening before each.
		</p>
		<div class="bars">
			<span class="lab">Forecast</span>
			<span class="track"><i class="fc" style:width="{(100 * v.forecast) / top}%"></i></span>
			<span class="val num">{fmt(v.forecast)}</span>
			<span class="lab">{v.kind === 'snow' ? 'Measured' : 'Gauge'}</span>
			<span class="track"><i class="obs" style:width="{(100 * v.observed) / top}%"></i></span>
			<span class="val num">{fmt(v.observed)}</span>
		</div>
		<p class="sentence">{v.sentence}</p>
	{/if}
</section>

<style>
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 6px 12px;
		margin-bottom: 2px;
	}
	.head h2 {
		margin: 0;
	}
	.pill {
		padding: 3px 11px;
		border-radius: 999px;
		background: var(--surface-2);
		font-size: 0.8rem;
		font-weight: 600;
		white-space: nowrap;
	}
	.small {
		font-size: 0.85rem;
	}
	.sub {
		margin: 2px 0 12px;
	}
	.bars {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 8px 12px;
	}
	.lab {
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--text-2);
	}
	.track {
		height: 14px;
		border-radius: 7px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.track i {
		display: block;
		height: 100%;
		min-width: 2px;
		border-radius: 7px;
	}
	.fc {
		background: var(--text-3);
	}
	.obs {
		background: var(--snow);
	}
	.val {
		font-family: var(--font-num);
		font-size: 1.05rem;
		font-weight: 650;
		text-align: right;
		min-width: 4.5em;
	}
	.sentence {
		margin: 12px 0 0;
		font-size: 0.92rem;
	}
</style>
