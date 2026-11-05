<script lang="ts">
	import { resolve } from '$app/paths';
	import { getOverview } from '../lib/api';
	import { prefs, type KindFilter, type SortKey } from '../lib/prefs.svelte';
	import { converters, snowNum } from '../lib/units';
	import { arrange } from '../lib/overview';
	import Sparkline from '../lib/charts/Sparkline.svelte';
	import type { OverviewRow } from '../lib/types.gen';

	let rows = $state<OverviewRow[] | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		getOverview()
			.then((r) => (rows = r))
			.catch((e: Error) => (error = e.message));
	});

	const c = $derived(converters(prefs.units));
	const shown = $derived(rows ? arrange(rows, prefs.sort, prefs.kind) : []);
	// One scale for every sparkline, so heights compare across locations.
	const sparkMax = $derived(
		Math.max(2.54, ...(rows ?? []).flatMap((r) => (r.periods ?? []).map((p) => p.snow_cm ?? 0)))
	);
	const sorts: [SortKey, string][] = [
		['next5', 'Next 5 days'],
		['d6_10', 'Days 6–10'],
		['last24', 'Last 24 h'],
		['name', 'Name']
	];
	const kinds: [KindFilter, string][] = [
		['all', 'All'],
		['resort', 'Resorts'],
		['backcountry', 'Backcountry']
	];
	const range = (r: OverviewRow) =>
		r.next5_p10_cm != null && r.next5_p90_cm != null
			? `${snowNum(r.next5_p10_cm, prefs.units)}–${snowNum(r.next5_p90_cm, prefs.units)} likely`
			: 'no range';
	const href = (id: string) => resolve('/location/[id]', { id });
</script>

<svelte:head><title>Snow Watch</title></svelte:head>

<div class="head">
	<h1>Overview</h1>
	<div class="filters">
		<div class="seg" role="group" aria-label="Sort by">
			{#each sorts as [key, label] (key)}
				<button aria-pressed={prefs.sort === key} onclick={() => prefs.setSort(key)}>{label}</button
				>
			{/each}
		</div>
		<div class="seg" role="group" aria-label="Show">
			{#each kinds as [key, label] (key)}
				<button aria-pressed={prefs.kind === key} onclick={() => prefs.setKind(key)}>{label}</button
				>
			{/each}
		</div>
	</div>
</div>

{#if error}
	<p class="card">Can't load the overview: {error}</p>
{:else if !rows}
	<p class="muted">Loading…</p>
{:else if !shown.length}
	<p class="card muted">No locations match.</p>
{:else}
	<!-- Phones: cards -->
	<ul class="cards">
		{#each shown as r (r.id)}
			<li>
				<a class="card loc" href={href(r.id)}>
					<div class="top">
						<div class="name">
							<strong>{r.name}</strong>
							<span class="muted small"
								>{r.region} · {r.kind === 'backcountry' ? 'Backcountry' : 'Resort'}</span
							>
						</div>
						{#if r.alerts?.length}<span class="chip" title={r.alerts.join(', ')}>{r.alerts[0]}</span
							>{/if}
					</div>
					{#if r.run_id == null}
						<div class="faint">No forecast yet</div>
					{:else}
						<div class="nums">
							<div>
								<span class="big num">{snowNum(r.next5_cm, prefs.units)}</span><span class="unit"
									>{c.snowUnit}</span
								>
								<div class="faint small">next 5 days · {range(r)}</div>
							</div>
							<div>
								<span class="mid num">{snowNum(r.d6_10_cm, prefs.units)}</span><span class="unit"
									>{c.snowUnit}</span
								>
								<div class="faint small">days 6–10</div>
							</div>
							<div>
								<span class="mid num">{snowNum(r.last24_cm, prefs.units)}</span><span class="unit"
									>{c.snowUnit}</span
								>
								<div class="faint small">last 24 h</div>
							</div>
						</div>
						<Sparkline
							periods={r.periods ?? []}
							max={sparkMax}
							label={`${r.name}: 10-day snowfall`}
						/>
					{/if}
				</a>
			</li>
		{/each}
	</ul>

	<!-- Desktop: a dense table -->
	<div class="card tablecard">
		<table class="data overview">
			<thead>
				<tr>
					<th>Location</th>
					<th>Last 24 h</th>
					<th>Next 5 days</th>
					<th>Days 6–10</th>
					<th class="sparkcol">Day and night, 10 days</th>
					<th>Alerts</th>
				</tr>
			</thead>
			<tbody>
				{#each shown as r (r.id)}
					<tr>
						<td>
							<a href={href(r.id)}><strong>{r.name}</strong></a>
							<div class="faint small">
								{r.region} · {r.kind === 'backcountry' ? 'Backcountry' : 'Resort'}
							</div>
						</td>
						<td class="num">{snowNum(r.last24_cm, prefs.units)} {c.snowUnit}</td>
						<td>
							<span class="tbig num">{snowNum(r.next5_cm, prefs.units)}</span>
							{c.snowUnit}
							<div class="faint small">{range(r)}</div>
						</td>
						<td class="num">{snowNum(r.d6_10_cm, prefs.units)} {c.snowUnit}</td>
						<td class="sparkcol"
							><Sparkline
								periods={r.periods ?? []}
								max={sparkMax}
								width={300}
								label={`${r.name}: 10-day snowfall`}
							/></td
						>
						<td
							>{#if r.alerts?.length}<span class="chip">{r.alerts.join(', ')}</span>{:else}<span
									class="faint">–</span
								>{/if}</td
						>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 10px;
		margin: 4px 0 12px;
	}
	h1 {
		font-size: 1.3rem;
		margin: 0;
	}
	.filters {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.cards {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		gap: 12px;
		grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
	}
	.loc {
		display: grid;
		gap: 10px;
		color: inherit;
		text-decoration: none;
	}
	.loc:hover {
		border-color: var(--snow);
	}
	.top {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		align-items: flex-start;
	}
	.name {
		display: grid;
		min-width: 0;
	}
	.small {
		font-size: 0.78rem;
	}
	.nums {
		display: flex;
		gap: 22px;
		align-items: flex-end;
		flex-wrap: wrap;
	}
	.big {
		font-size: 2.2rem;
		font-weight: 600;
		line-height: 1;
	}
	.mid {
		font-size: 1.35rem;
		font-weight: 600;
	}
	.unit {
		color: var(--text-2);
		margin-left: 3px;
	}
	.chip {
		font-size: 0.75rem;
		background: var(--surface-2);
		border: 1px solid var(--temp);
		border-radius: 999px;
		padding: 2px 8px;
		white-space: nowrap;
	}
	.tablecard {
		display: none;
		padding: 6px 8px;
	}
	.overview td {
		vertical-align: middle;
	}
	.overview td:first-child a {
		color: var(--text);
		text-decoration: none;
	}
	.tbig {
		font-size: 1.4rem;
		font-weight: 600;
	}
	.sparkcol {
		width: 316px;
	}
	@media (min-width: 1100px) {
		.cards {
			display: none;
		}
		.tablecard {
			display: block;
		}
	}
</style>
