<script lang="ts">
	import { resolve } from '$app/paths';
	import { getOverview } from '../../lib/api';
	import { prefs } from '../../lib/prefs.svelte';
	import { converters, snow, snowNum, water } from '../../lib/units';
	import { bucket, EDGES_CM } from '../../lib/calendar';
	import { dayPairs, HEAVY_CM, type DayPair } from '../../lib/daybars';
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

	type Cell = {
		pair: DayPair;
		kind: 'none' | 'snow' | 'heavy' | 'mix' | 'rain';
		key: string | null;
		rain_mm: number;
	};
	// A day only counts as wet with at least 1 mm (0.04 in) of rain, so drizzle stays quiet.
	const WET_MM = 1;
	const cellOf = (pair: DayPair, rain_mm: number): Cell => {
		const snowy = pair.total >= EDGES_CM[0];
		const wet = rain_mm >= WET_MM;
		let kind: Cell['kind'] = 'none';
		if (snowy) kind = wet ? 'mix' : pair.total >= HEAVY_CM ? 'heavy' : 'snow';
		else if (wet) kind = 'rain';
		return { pair, kind, key: null, rain_mm };
	};
	const grid = $derived(
		shown.map((r) => {
			const periods = r.periods ?? [];
			const cells = dayPairs(periods, 10).map((pair) => {
				const rain = periods
					.filter((p) => p.date === pair.date)
					.reduce((a, p) => a + (p.rain_mm ?? 0), 0);
				const cell = cellOf(pair, rain);
				cell.key =
					periods.find((p) => p.date === pair.date && p.kind === 'day')?.key ??
					periods.find((p) => p.date === pair.date)?.key ??
					null;
				return cell;
			});
			return {
				r,
				cells: new Map(cells.map((x) => [x.pair.date, x])),
				total: cells.reduce((a, x) => a + x.pair.total, 0)
			};
		})
	);
	// Column dates: the longest run any location has.
	const dates = $derived(
		[...new Set(grid.flatMap((g) => [...g.cells.keys()]))].sort().slice(0, 10)
	);
	const today = $derived(
		shown.flatMap((r) => r.periods ?? []).find((p) => p.label === 'Today' || p.label === 'Tonight')
			?.date ?? null
	);
	// Across all locations: the most any of them gets each day.
	const peak = $derived(
		dates.map((d) => {
			let best = { cm: 0, name: '' };
			for (const g of grid) {
				const cm = g.cells.get(d)?.pair.total ?? 0;
				if (cm > best.cm) best = { cm, name: g.r.name };
			}
			return { date: d, ...best };
		})
	);
	const peakMax = $derived(Math.max(2.54, ...peak.map((p) => p.cm)));

	const cycles = $derived(
		stormCycles(shown).filter((x) => !dates.length || x.start <= dates.at(-1)!)
	);
	const startsIn = (d: string) => {
		if (!today) return '';
		const days = Math.round((Date.parse(d) - Date.parse(today)) / 86400e3);
		return days <= 0 ? 'under way' : days === 1 ? 'starts tomorrow' : `starts in ${days} days`;
	};
	const dayName = (d: string) => `${weekday(d)} ${monthDay(d)}`;
	const cellHref = (id: string, key: string | null) =>
		key
			? `${resolve('/location/[id]', { id })}?period=${encodeURIComponent(key)}`
			: resolve('/location/[id]', { id });
	const show = (cm: number) => Number(snowNum(cm, prefs.units)) > 0;

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

<div class="head">
	<h1>Calendar</h1>
	<p class="muted">
		The next 10 days across all your locations: which storms are coming, and where the snow lands.
	</p>
</div>

{#if error}
	<p class="card">Can't load the calendar: {error}</p>
{:else if !rows}
	<p class="muted">Loading…</p>
{:else}
	<section class="block">
		<h2>Storm cycles</h2>
		{#if cycles.length}
			<div class="cycles">
				{#each cycles as cy (cy.start + cy.end)}
					{@const top = cy.locations.slice(0, 5)}
					<article class="card cycle">
						<div class="cy-head">
							<div>
								<strong
									>{dayName(cy.start)}{cy.end !== cy.start ? ` → ${dayName(cy.end)}` : ''}</strong
								>
								<span class="faint small">{startsIn(cy.start)}</span>
							</div>
							<div class="cy-max">
								<span class="faint small">up to</span>
								<span class="num big"
									>{snowNum(cy.max_cm, prefs.units)}<small>{c.snowUnit}</small></span
								>
							</div>
						</div>
						<ul class="cy-locs">
							{#each top as l (l.id)}
								<li>
									<a href={resolve('/location/[id]', { id: l.id })}>{l.name}</a>
									<span class="cy-bar" aria-hidden="true"
										><span
											class:heavy={l.total_cm >= HEAVY_CM}
											style:width="{((l.total_cm / cy.max_cm) * 100).toFixed(0)}%"
										></span></span
									>
									<span class="num">{snow(l.total_cm, prefs.units)}</span>
									{#if l.wet}<span class="wet" title="Some rain or mixed precipitation">+ rain</span
										>{/if}
								</li>
							{/each}
						</ul>
						{#if cy.locations.length > top.length}
							<span class="faint small">and {cy.locations.length - top.length} more</span>
						{/if}
					</article>
				{/each}
			</div>
		{:else}
			<p class="card muted">No storms of {snow(5, prefs.units)} or more in the next 10 days.</p>
		{/if}
	</section>

	<section class="block">
		<h2>Snow by day</h2>
		<div class="card gridcard">
			<div class="scroller">
				<table class="cal">
					<thead>
						<tr>
							<th class="locname"><span class="sr">Location</span></th>
							{#each dates as d (d)}
								<th class="date" class:weekend={['Sat', 'Sun'].includes(weekday(d))}>
									<span>{d === today ? 'Today' : weekday(d)}</span>
									<small>{monthDay(d)}</small>
								</th>
							{/each}
							<th class="tot">10 days</th>
							<th class="tot">Depth</th>
						</tr>
						<tr class="peakrow">
							<th class="locname faint">Most anywhere</th>
							{#each peak as p (p.date)}
								<td title={p.cm > 0 ? `${p.name}: ${snow(p.cm, prefs.units)}` : 'No snow'}>
									<span class="pk" aria-hidden="true"
										><span
											class:heavy={p.cm >= HEAVY_CM}
											style:height="{Math.max(p.cm > 0 ? 2 : 0, (p.cm / peakMax) * 30)}px"
										></span></span
									>
									<span class="pkv num">{show(p.cm) ? snowNum(p.cm, prefs.units) : ''}</span>
								</td>
							{/each}
							<td></td>
							<td></td>
						</tr>
					</thead>
					<tbody>
						{#each grid as g (g.r.id)}
							<tr>
								<th class="locname" scope="row">
									<a href={resolve('/location/[id]', { id: g.r.id })}>{g.r.name}</a>
									<small class="faint">{g.r.region}</small>
								</th>
								{#each dates as d (d)}
									{@const cell = g.cells.get(d)}
									<td>
										{#if cell}
											{@const p = cell.pair}
											<!-- cellHref() builds the URL with resolve() and adds ?period= -->
											<!-- eslint-disable svelte/no-navigation-without-resolve -->
											<a
												class="tile b{cell.kind === 'rain' ? 0 : bucket(p.total)} k-{cell.kind}"
												href={cellHref(g.r.id, cell.key)}
												aria-label={`${g.r.name}, ${dayName(d)}: ${snow(p.total, prefs.units)}${cell.kind === 'rain' ? `, ${water(cell.rain_mm, prefs.units)} of rain` : cell.kind === 'mix' ? ', mixed with rain' : ''}`}
											>
												<span class="v num"
													>{cell.kind === 'rain'
														? water(cell.rain_mm, prefs.units)
														: show(p.total)
															? snowNum(p.total, prefs.units)
															: ''}{#if cell.kind === 'rain'}<small>rain</small>{/if}</span
												>
												{#if show(p.total)}
													<span class="split" aria-hidden="true">
														<i style:flex={Math.max(0.0001, p.day?.cm ?? 0)}></i>
														<i class="n" style:flex={Math.max(0.0001, p.night?.cm ?? 0)}></i>
													</span>
												{/if}
											</a>
											<!-- eslint-enable svelte/no-navigation-without-resolve -->
										{:else}
											<span class="tile empty"></span>
										{/if}
									</td>
								{/each}
								<td class="tot num">{snowNum(g.total, prefs.units)}</td>
								<td class="tot num faint"
									>{g.r.snow_depth_cm == null ? '–' : snowNum(g.r.snow_depth_cm, prefs.units)}</td
								>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<div class="legend">
				<span class="sw b0"></span><span>none</span>
				{#each legend as l (l.b)}<span class="sw b{l.b}"></span><span>{l.text}</span>{/each}
				<span class="faint">{c.snowUnit} of snow per day</span>
				<span class="sw k-heavy-sw"></span><span>6+ {c.snowUnit === 'in' ? 'in' : '15 cm'} day</span
				>
				<span class="sw k-mix-sw"></span><span>mixed</span>
				<span class="sw k-rain-sw"></span><span>rain</span>
				<span class="faint"
					>Thin bar: day then night · Depth: measured snow depth nearby (SNOTEL)</span
				>
			</div>
		</div>
	</section>
{/if}

<style>
	.head {
		margin: 4px 0 16px;
	}
	h1 {
		font-family: var(--font-num);
		font-size: 1.9rem;
		font-weight: 600;
		letter-spacing: -0.02em;
		margin: 0 0 4px;
	}
	.head p {
		margin: 0;
		font-size: 0.9rem;
	}
	h2 {
		font-family: var(--font-num);
		font-size: 1.15rem;
		font-weight: 600;
		margin: 0 0 10px;
	}
	.block {
		margin-bottom: 22px;
	}
	.small {
		font-size: 0.78rem;
	}
	/* Storm cycles */
	.cycles {
		display: grid;
		gap: 12px;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
	}
	.cycle {
		display: grid;
		gap: 12px;
		align-content: start;
		padding: 16px 18px;
	}
	.cy-head {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		align-items: flex-start;
	}
	.cy-head > div:first-child {
		display: grid;
		gap: 2px;
	}
	.cy-max {
		display: grid;
		justify-items: end;
	}
	.big {
		font-size: 1.7rem;
		font-weight: 600;
		line-height: 1;
	}
	.big small {
		font-size: 0.8rem;
		font-weight: 500;
		margin-left: 2px;
		color: var(--text-2);
	}
	.cy-locs {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 7px;
		font-size: 0.85rem;
	}
	.cy-locs li {
		display: grid;
		grid-template-columns: minmax(0, 1.2fr) minmax(40px, 1fr) auto auto;
		gap: 8px;
		align-items: center;
	}
	.cy-locs a {
		color: var(--text);
		text-decoration: none;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.cy-bar {
		height: 6px;
		border-radius: 3px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.cy-bar span {
		display: block;
		height: 100%;
		border-radius: 3px;
		background: var(--snow);
	}
	.cy-bar span.heavy {
		background: var(--snow-heavy);
	}
	.wet {
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--rain);
	}
	/* Snow by day */
	.gridcard {
		padding: 12px 0 12px 12px;
	}
	.scroller {
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
	}
	.cal {
		border-collapse: separate;
		border-spacing: 4px 4px;
		font-variant-numeric: tabular-nums;
	}
	.cal th,
	.cal td {
		padding: 0;
		text-align: center;
	}
	.locname {
		position: sticky;
		left: 0;
		z-index: 1;
		background: var(--surface);
		text-align: left !important;
		padding-right: 10px !important;
		min-width: 150px;
		max-width: 190px;
	}
	th.locname a {
		display: block;
		color: var(--text);
		font-weight: 600;
		font-size: 0.9rem;
		text-decoration: none;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	th.locname small {
		display: block;
		font-size: 0.72rem;
		font-weight: 400;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.date {
		font-size: 0.8rem;
		font-weight: 600;
		padding-bottom: 4px !important;
	}
	.date span,
	.date small {
		display: block;
	}
	.date small {
		font-size: 0.68rem;
		font-weight: 400;
		color: var(--text-3);
	}
	.date.weekend span {
		color: var(--accent);
	}
	.peakrow th {
		font-size: 0.72rem;
		font-weight: 500;
	}
	.peakrow td {
		vertical-align: bottom;
	}
	.pk {
		display: flex;
		justify-content: center;
		align-items: flex-end;
		height: 30px;
	}
	.pk span {
		width: 60%;
		border-radius: 3px 3px 0 0;
		background: var(--snow);
	}
	.pk span.heavy {
		background: var(--snow-heavy);
	}
	.pkv {
		display: block;
		font-size: 0.68rem;
		color: var(--text-2);
		height: 14px;
	}
	.tile {
		position: relative;
		display: grid;
		place-items: center;
		width: 56px;
		height: 46px;
		border-radius: 10px;
		text-decoration: none;
		overflow: hidden;
	}
	.tile.empty {
		background: var(--surface-2);
		opacity: 0.5;
	}
	.tile .v {
		font-size: 0.88rem;
		font-weight: 600;
	}
	.split {
		position: absolute;
		left: 6px;
		right: 6px;
		bottom: 5px;
		display: flex;
		gap: 2px;
		height: 3px;
	}
	.split i {
		border-radius: 2px;
		background: currentColor;
		opacity: 0.55;
	}
	.split i.n {
		opacity: 0.85;
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
	.k-heavy {
		box-shadow: inset 0 0 0 2px var(--snow-heavy);
	}
	.k-mix {
		box-shadow: inset 4px 0 0 var(--mix);
	}
	.k-rain {
		background: color-mix(in srgb, var(--rain) 18%, var(--surface));
		color: var(--rain);
	}
	.k-rain .v {
		font-size: 0.68rem;
		line-height: 1.1;
	}
	.k-rain .v small {
		display: block;
		font-size: 0.62rem;
		font-weight: 500;
	}
	.tot {
		font-size: 0.85rem;
		font-weight: 600;
		padding: 0 10px !important;
		white-space: nowrap;
	}
	th.tot {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--text-3);
		vertical-align: bottom;
		padding-bottom: 4px !important;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 8px;
		padding: 12px 12px 0 4px;
		font-size: 0.75rem;
		color: var(--text-2);
	}
	.sw {
		width: 14px;
		height: 14px;
		border-radius: 4px;
	}
	.sw:not(:first-child) {
		margin-left: 6px;
	}
	.k-heavy-sw {
		box-shadow: inset 0 0 0 2px var(--snow-heavy);
		background: var(--c3);
	}
	.k-mix-sw {
		box-shadow: inset 4px 0 0 var(--mix);
		background: var(--c2);
	}
	.k-rain-sw {
		background: color-mix(in srgb, var(--rain) 30%, var(--surface));
	}
	.sr {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
	@media (max-width: 600px) {
		.locname {
			min-width: 108px;
			max-width: 120px;
		}
		.tile {
			width: 46px;
			height: 42px;
		}
	}
</style>
