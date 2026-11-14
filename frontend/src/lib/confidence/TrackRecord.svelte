<!--
  How the forecast has done here: each source's next-day forecasts against what the
  snow station measured. Bias is forecast minus observed (positive = too much snow
  forecast); "big days" are days with at least 3 in (7.6 cm) observed or forecast.
  The day-by-day bars are on the Observed tab.
-->
<script lang="ts">
	import { hscroll } from '../hscroll';
	import type { VerificationOut } from '../types.gen';
	import type { LoadState } from '../load';
	import { closerMethod, closest, headlineRow, sourceName, sourceShort } from '../scores';
	import { monthDay } from '../time';
	import { converters, elevation, type UnitSystem } from '../units';

	interface Props {
		data: VerificationOut | null;
		units: UnitSystem;
		load?: LoadState;
	}

	let { data, units, load = 'ready' }: Props = $props();
	const c = $derived(converters(units));
	// The server's threshold for a big day is 7.62 cm (3 in).
	const bigDay = $derived(units === 'imperial' ? '3 in' : '8 cm');
	const headline = $derived(data?.headline ?? 'cons');
	const name = (s: string) => `${sourceName(s)}${s === headline ? ' · the app’s totals' : ''}`;
	const num = (cm: number | null | undefined) => c.snow(cm ?? null)?.toFixed(c.snowDigits) ?? '–';
	const signed = (cm: number | null | undefined) => {
		const v = c.snow(cm ?? null);
		if (v === null) return '–';
		const text = Math.abs(v).toFixed(c.snowDigits);
		// No sign on a rounded zero ("-0.0").
		return Number(text) === 0 ? text : `${v > 0 ? '+' : '−'}${text}`;
	};
	const best = $derived(data ? closest(data.rows) : null);
	const ours = $derived(data ? headlineRow(data) : null);
	const better = $derived(data ? closerMethod(data) : null);
	// The longest bar is the worst average miss.
	const worst = $derived(Math.max(0.1, ...(data?.rows ?? []).map((r) => r.mae_cm ?? 0)));
	const summary = $derived.by(() => {
		if (!ours || ours.mae_cm === null) return null;
		const miss = `${num(ours.mae_cm)} ${c.snowUnit}`;
		const lean =
			ours.bias_cm === null || Math.abs(ours.bias_cm) < 0.5
				? 'with no lean either way'
				: `and runs ${num(Math.abs(ours.bias_cm))} ${c.snowUnit} ${ours.bias_cm > 0 ? 'high' : 'low'}`;
		const who =
			best && best.source !== ours.source
				? ` ${sourceShort(best.source).replace(/^the /, 'The ')} has been closest (${num(best.mae_cm)} ${c.snowUnit}).`
				: best
					? ' Nothing has been closer.'
					: '';
		return `Day to day, the app’s forecast misses by ${miss} on average ${lean}.${who}`;
	});
</script>

<div class="track">
	<h2>Track record here</h2>
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
		{#if summary}<p class="lede">{summary}</p>{/if}
		<p class="muted small">
			Next-day forecasts since {monthDay(data.since ?? '')} ({data.n_days} days) against {data.station_name}
			{#if data.station_elev_m !== null}
				at {elevation(data.station_elev_m, units)} (mid-mountain is {elevation(
					data.band_elev_m,
					units
				)}){/if}.
			{#if better}<strong>Model snowfall vs temperature-based depth: {better}.</strong>{/if}
		</p>
		<div class="table-wrap" use:hscroll>
			<table class="data scores">
				<thead>
					<tr>
						<th>Source</th>
						<th title="Average size of the miss">Average miss</th>
						<th title="Average forecast minus observed">Bias</th>
						<th title={`Days of ${bigDay} or more: caught / missed / false alarms`}>Big days</th>
						<th title="Days compared">Days</th>
					</tr>
				</thead>
				<tbody>
					{#each data.rows as r (r.source)}
						<tr class:hl={r.source === headline}>
							<th scope="row">{name(r.source)}</th>
							<td class="miss">
								<span class="bar" aria-hidden="true"
									><i
										class:best={best?.source === r.source}
										style:width="{(100 * (r.mae_cm ?? 0)) / worst}%"
									></i></span
								>
								<span class="num">{num(r.mae_cm)}</span>
							</td>
							<td class="num">{signed(r.bias_cm)}</td>
							<td class="num">{r.hits} / {r.misses} / {r.false_alarms}</td>
							<td class="num">{r.n}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<p class="faint small key">
			{c.snowUnit} per day. The app's snow totals use the
			{headline === 'cons_slr' ? 'temperature-based depth' : 'model snowfall'}; models and the
			ensemble are their own 7:1 snowfall. Bias: forecast minus observed. Big days ({bigDay}
			or more): caught / missed / false alarms. The station sits at its own elevation, so read bias over
			weeks, not days.
		</p>
	{/if}
</div>

<style>
	h2 {
		margin: 0 0 6px;
	}
	.small {
		font-size: 0.85rem;
	}
	.lede {
		margin: 0 0 6px;
		font-size: 0.95rem;
	}
	.key {
		margin: 8px 0 0;
	}
	.hl th,
	.hl td {
		font-weight: 600;
	}
	.miss {
		min-width: 130px;
	}
	.bar {
		display: inline-block;
		width: 70px;
		height: 8px;
		margin-right: 6px;
		border-radius: 4px;
		background: var(--surface-2);
		overflow: hidden;
		vertical-align: middle;
	}
	.bar i {
		display: block;
		height: 100%;
		border-radius: 4px;
		background: var(--text-3);
	}
	.bar i.best {
		background: var(--snow);
	}
	/* Phones: a long source name wraps, so the numbers stay on screen. */
	@media (max-width: 640px) {
		.scores th:first-child {
			white-space: normal;
			min-width: 120px;
		}
		.bar {
			display: none;
		}
		.miss {
			min-width: 0;
		}
	}
</style>
