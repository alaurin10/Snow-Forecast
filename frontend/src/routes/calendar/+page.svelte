<script lang="ts">
	import { resolve } from '$app/paths';
	import { getOverview } from '../../lib/api';
	import { prefs } from '../../lib/prefs.svelte';
	import { converters, snowNum } from '../../lib/units';
	import { bucket, labelled, EDGES_CM } from '../../lib/calendar';
	import { arrange } from '../../lib/overview';
	import { weekday } from '../../lib/time';
	import type { OverviewRow } from '../../lib/types.gen';

	let rows = $state<OverviewRow[] | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		getOverview()
			.then((r) => (rows = r))
			.catch((e: Error) => (error = e.message));
	});

	const c = $derived(converters(prefs.units));
	const shown = $derived(rows ? arrange(rows, prefs.sort, prefs.kind) : []);
	// The column layout comes from the location with the most periods.
	const cols = $derived(
		(shown.find((r) => (r.periods ?? []).length === 20)?.periods ?? shown[0]?.periods ?? []).map(
			(p) => ({ key: p.key, date: p.date, kind: p.kind })
		)
	);
	const dates = $derived(
		cols.reduce<{ date: string; span: number }[]>((acc, col) => {
			const last = acc.at(-1);
			if (last && last.date === col.date) last.span++;
			else acc.push({ date: col.date, span: 1 });
			return acc;
		}, [])
	);
	const legend = $derived(
		[1, 2, 3, 4, 5].map((b) => {
			const lo = EDGES_CM[b - 1];
			const hi = EDGES_CM[b];
			const f = (cm: number) => (prefs.units === 'imperial' ? cm / 2.54 : cm).toFixed(0);
			return { b, text: hi ? `${b === 1 ? '<' : `${f(lo)}–`}${f(hi)}` : `${f(lo)}+` };
		})
	);
	const cellHref = (id: string, key: string) =>
		`${resolve('/location/[id]', { id })}?period=${encodeURIComponent(key)}`;
</script>

<svelte:head><title>Calendar · Snow Watch</title></svelte:head>

<div class="head">
	<h1>Calendar</h1>
	<p class="muted small">
		When and where: snow per day and night, {c.snowUnit}. Tap a cell for that period.
	</p>
</div>

{#if error}
	<p class="card">Can't load the calendar: {error}</p>
{:else if !rows}
	<p class="muted">Loading…</p>
{:else}
	<div class="card gridcard">
		<div class="scroller">
			<table class="cal">
				<thead>
					<tr>
						<th class="locname"></th>
						{#each dates as d (d.date)}
							<th colspan={d.span} class="date">{weekday(d.date)}</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each shown as r (r.id)}
						<tr>
							<th class="locname" scope="row"
								><a href={resolve('/location/[id]', { id: r.id })}>{r.name}</a></th
							>
							{#each cols as col (col.key)}
								{@const p = (r.periods ?? []).find((x) => x.key === col.key)}
								{@const b = bucket(p?.snow_cm)}
								<td
									class="cell"
									class:night={col.kind === 'night'}
									class:dayfirst={col.kind === 'day'}
								>
									{#if p}
										<!-- cellHref() builds the URL with resolve() and adds ?period= -->
										<!-- eslint-disable svelte/no-navigation-without-resolve -->
										<a
											href={cellHref(r.id, p.key)}
											class="b{b}"
											aria-label={`${r.name}, ${p.label}: ${snowNum(p.snow_cm, prefs.units)} ${c.snowUnit}`}
											>{labelled(p.snow_cm) ? snowNum(p.snow_cm, prefs.units) : ''}</a
										>
										<!-- eslint-enable svelte/no-navigation-without-resolve -->
									{:else}
										<span class="b0 empty">·</span>
									{/if}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<div class="legend">
			<span class="sw b0"></span><span>none</span>
			{#each legend as l (l.b)}
				<span class="sw b{l.b}"></span><span>{l.text}</span>
			{/each}
			<span class="faint">{c.snowUnit}; each date has a day then a night column</span>
		</div>
	</div>
{/if}

<style>
	.head h1 {
		font-size: 1.3rem;
		margin: 4px 0 2px;
	}
	.small {
		font-size: 0.85rem;
		margin: 0 0 12px;
	}
	@media (max-width: 600px) {
		.locname {
			max-width: 104px;
		}
	}
	.gridcard {
		padding: 10px 0 10px 10px;
	}
	.scroller {
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
	}
	.cal {
		border-collapse: separate;
		border-spacing: 0 3px;
		font-variant-numeric: tabular-nums;
	}
	.locname {
		position: sticky;
		left: 0;
		z-index: 1;
		background: var(--surface);
		text-align: left;
		font-weight: 600;
		font-size: 0.85rem;
		padding: 0 10px 0 0;
		min-width: 96px;
		max-width: 150px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.locname a {
		color: var(--text);
		text-decoration: none;
	}
	.date {
		font-size: 0.75rem;
		color: var(--text-2);
		font-weight: 600;
		padding: 0 0 2px;
		text-align: center;
		border-left: 3px solid var(--surface);
	}
	.cell {
		padding: 0;
	}
	.cell.dayfirst {
		border-left: 3px solid var(--surface);
	}
	.cell a,
	.cell span {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		margin-left: 1px;
		border-radius: 5px;
		font-size: 0.78rem;
		font-weight: 600;
		text-decoration: none;
	}
	.b0 {
		background: var(--c0);
		color: var(--text-3);
	}
	.b1 {
		background: var(--c1);
		color: var(--c-ink-light);
	}
	.b2 {
		background: var(--c2);
		color: var(--c-ink-light);
	}
	.b3 {
		background: var(--c3);
		color: var(--c-ink-dark);
	}
	.b4 {
		background: var(--c4);
		color: var(--c-ink-dark);
	}
	.b5 {
		background: var(--c5);
		color: var(--c-ink-dark);
	}
	.empty {
		background: transparent !important;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		font-size: 0.78rem;
		color: var(--text-2);
		padding: 10px 10px 0 0;
	}
	.legend .sw {
		width: 14px;
		height: 14px;
		border-radius: 3px;
		display: inline-block;
	}
	.legend span:not(.sw) {
		margin-right: 6px;
	}
</style>
