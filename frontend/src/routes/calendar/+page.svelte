<script lang="ts">
	import { hscroll } from '../../lib/hscroll';
	import { resolve } from '$app/paths';
	import { getOverview } from '../../lib/api';
	import { prefs } from '../../lib/prefs.svelte';
	import { converters, snow, snowNum } from '../../lib/units';
	import { bucket, EDGES_CM } from '../../lib/calendar';
	import { dayPairs } from '../../lib/daybars';
	import { stormCycles } from '../../lib/stormcycles';
	import { monthDay, weekday } from '../../lib/time';
	import type { OverviewRow } from '../../lib/types.gen';

	let rows = $state<OverviewRow[] | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		getOverview()
			.then((r) => (rows = r))
			.catch((e: Error) => (error = e.message));
	});

	const c = $derived(converters(prefs.units));
	// In the order set on the admin page.
	const shown = $derived((rows ?? []).filter((r) => r.run_id != null));
	const DAYS = 10;
	// A day counts as rainy with at least 1 mm (0.04 in) of rain and almost no snow.
	const WET_MM = 1;

	const grid = $derived(
		shown.map((r) => {
			const periods = r.periods ?? [];
			const days = dayPairs(periods, DAYS).map((d) => {
				const rain = periods
					.filter((p) => p.date === d.date)
					.reduce((a, p) => a + (p.rain_mm ?? 0), 0);
				return {
					date: d.date,
					cm: d.total,
					rainy: d.total < EDGES_CM[0] && rain >= WET_MM,
					key: periods.find((p) => p.date === d.date)?.key ?? null
				};
			});
			return {
				r,
				days: new Map(days.map((d) => [d.date, d])),
				total: days.reduce((a, d) => a + d.cm, 0)
			};
		})
	);
	const dates = $derived(
		[...new Set(grid.flatMap((g) => [...g.days.keys()]))].sort().slice(0, DAYS)
	);
	const today = $derived(
		shown.flatMap((r) => r.periods ?? []).find((p) => p.label === 'Today' || p.label === 'Tonight')
			?.date ?? null
	);
	const storms = $derived(
		stormCycles(shown).filter((s) => !dates.length || s.start <= dates.at(-1)!)
	);
	const dayName = (d: string) => `${weekday(d)} ${monthDay(d)}`;
	const soon = (d: string) => {
		if (!today) return '';
		const n = Math.round((Date.parse(d) - Date.parse(today)) / 86400e3);
		return n <= 0 ? 'now' : n === 1 ? 'tomorrow' : `in ${n} days`;
	};
	const show = (cm: number) => Number(snowNum(cm, prefs.units)) > 0;
	const cellHref = (id: string, key: string | null) =>
		key
			? `${resolve('/location/[id]', { id })}?period=${encodeURIComponent(key)}`
			: resolve('/location/[id]', { id });
	const legend = $derived(
		[1, 2, 3, 4, 5].map((b) => {
			const lo = EDGES_CM[b - 1];
			const hi = EDGES_CM[b];
			const f = (cm: number) => (prefs.units === 'imperial' ? cm / 2.54 : cm).toFixed(0);
			return { b, text: hi ? `${b === 1 ? '<' : `${f(lo)}–`}${f(hi)}` : `${f(lo)}+` };
		})
	);
</script>

<svelte:head><title>Calendar · Snow Watch</title></svelte:head>

<h1>Calendar</h1>

{#if error}
	<p class="card">Can't load the calendar: {error}</p>
{:else if !rows}
	<p class="muted">Loading…</p>
{:else}
	<section class="card storms">
		<h2>Storms ahead</h2>
		{#if storms.length}
			<ul>
				{#each storms as s (s.start + s.end)}
					<li>
						<span class="when"
							><strong>{dayName(s.start)}{s.end !== s.start ? ` – ${dayName(s.end)}` : ''}</strong>
							<span class="faint">{soon(s.start)}</span></span
						>
						<span class="where">
							{#each s.locations.slice(0, 3) as l, i (l.id)}{i ? ' · ' : ''}{l.name}
								<strong class="num">{snow(l.total_cm, prefs.units)}</strong
								>{/each}{#if s.locations.length > 3}<span class="faint">
									· +{s.locations.length - 3} more</span
								>{/if}
						</span>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="muted">No storms of {snow(5, prefs.units)} or more in the next {DAYS} days.</p>
		{/if}
	</section>

	<section class="card gridcard">
		<div class="scroller" use:hscroll>
			<table class="cal">
				<thead>
					<tr>
						<th class="loc"><span class="sr">Location</span></th>
						{#each dates as d (d)}
							<th class="date" class:weekend={['Sat', 'Sun'].includes(weekday(d))}
								>{d === today ? 'Today' : weekday(d)}<small>{Number(d.slice(8))}</small></th
							>
						{/each}
						<th class="tot">Total</th>
					</tr>
				</thead>
				<tbody>
					{#each grid as g (g.r.id)}
						<tr>
							<th class="loc" scope="row"
								><a href={resolve('/location/[id]', { id: g.r.id })}>{g.r.name}</a></th
							>
							{#each dates as d (d)}
								{@const day = g.days.get(d)}
								<td>
									{#if day}
										<!-- cellHref() builds the URL with resolve() and adds ?period= -->
										<!-- eslint-disable svelte/no-navigation-without-resolve -->
										<a
											class="tile b{bucket(day.cm)}"
											class:rainy={day.rainy}
											href={cellHref(g.r.id, day.key)}
											aria-label={`${g.r.name}, ${dayName(d)}: ${snow(day.cm, prefs.units)}${day.rainy ? ', rain' : ''}`}
											>{show(day.cm) ? snowNum(day.cm, prefs.units) : ''}</a
										>
										<!-- eslint-enable svelte/no-navigation-without-resolve -->
									{/if}
								</td>
							{/each}
							<td class="tot num">{snowNum(g.total, prefs.units)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<div class="legend">
			{#each legend as l (l.b)}<span class="sw b{l.b}"></span><span>{l.text}</span>{/each}
			<span class="faint">{c.snowUnit} of snow per day</span>
			<span class="sw b0 rainy"></span><span>rain</span>
		</div>
	</section>
{/if}

<style>
	h1 {
		font-family: var(--font-num);
		font-size: 1.9rem;
		font-weight: 600;
		letter-spacing: -0.02em;
		margin: 4px 0 16px;
	}
	h2 {
		font-size: 0.95rem;
		margin: 0 0 8px;
	}
	.storms {
		margin-bottom: 14px;
	}
	.storms ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
	}
	.storms li {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 16px;
		padding: 9px 0;
		border-top: 1px solid var(--grid);
		font-size: 0.88rem;
	}
	.storms li:first-child {
		border-top: 0;
	}
	.when {
		display: flex;
		gap: 8px;
		min-width: 230px;
	}
	.where {
		color: var(--text-2);
	}
	.where strong {
		color: var(--text);
		font-weight: 600;
	}
	.storms p {
		margin: 0;
		font-size: 0.88rem;
	}
	.gridcard {
		padding: 12px 0 12px 12px;
	}
	.scroller {
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
	}
	.cal {
		border-collapse: separate;
		border-spacing: 3px;
		font-variant-numeric: tabular-nums;
	}
	.cal th,
	.cal td {
		padding: 0;
		text-align: center;
	}
	.loc {
		position: sticky;
		left: 0;
		z-index: 1;
		background: var(--surface);
		text-align: left !important;
		padding-right: 10px !important;
		max-width: 170px;
	}
	.loc a {
		display: block;
		color: var(--text);
		font-weight: 600;
		font-size: 0.88rem;
		text-decoration: none;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.date {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--text-2);
		padding-bottom: 4px !important;
	}
	.date small {
		display: block;
		font-weight: 400;
		color: var(--text-3);
	}
	.date.weekend {
		color: var(--accent);
	}
	.tile {
		display: grid;
		place-items: center;
		width: 48px;
		height: 38px;
		border-radius: 9px;
		font-size: 0.85rem;
		font-weight: 600;
		text-decoration: none;
	}
	.tile.rainy {
		background: color-mix(in srgb, var(--rain) 22%, var(--surface));
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
	.tot {
		font-size: 0.85rem;
		font-weight: 600;
		padding: 0 12px !important;
	}
	th.tot {
		font-size: 0.72rem;
		color: var(--text-3);
		vertical-align: bottom;
		padding-bottom: 4px !important;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		padding: 12px 12px 0 4px;
		font-size: 0.75rem;
		color: var(--text-2);
	}
	.sw {
		width: 14px;
		height: 14px;
		border-radius: 4px;
	}
	.sw.rainy {
		margin-left: 10px;
		background: color-mix(in srgb, var(--rain) 30%, var(--surface));
	}
	.sr {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
	/* Wide screens: the grid fills the card and full names fit. */
	@media (min-width: 900px) {
		.cal {
			width: 100%;
		}
		.loc {
			max-width: 240px;
		}
		.cal td:not(.tot) .tile {
			width: 100%;
			min-width: 48px;
		}
	}
	/* Phones: names wrap onto two lines rather than cut to a few letters. */
	@media (max-width: 600px) {
		.loc {
			max-width: 96px;
			min-width: 96px;
		}
		.loc a {
			white-space: normal;
			display: -webkit-box;
			-webkit-box-orient: vertical;
			-webkit-line-clamp: 2;
			line-clamp: 2;
			font-size: 0.8rem;
			line-height: 1.2;
		}
		.tile {
			width: 42px;
		}
	}
</style>
