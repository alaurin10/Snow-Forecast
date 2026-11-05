<script lang="ts">
	import { resolve } from '$app/paths';
	import { getOverview } from '../lib/api';
	import { prefs, type KindFilter, type SortKey } from '../lib/prefs.svelte';
	import { converters, snowNum } from '../lib/units';
	import { arrange } from '../lib/overview';
	import DayBars from '../lib/components/DayBars.svelte';
	import DangerChip from '../lib/components/DangerChip.svelte';
	import FlagBadges from '../lib/components/FlagBadges.svelte';
	import MapView from '../lib/components/MapView.svelte';
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
	// One scale for every row, so bar heights compare across locations.
	const barMax = $derived(
		Math.max(2.54, ...(rows ?? []).flatMap((r) => (r.periods ?? []).map((p) => p.snow_cm ?? 0)))
	);
	const sorts: [SortKey, string][] = [
		['next5', 'Next 5 days'],
		['d6_10', 'Days 6–10'],
		['last24', 'Last 24 hours'],
		['name', 'Name']
	];
	const kinds: [KindFilter, string][] = [
		['all', 'All'],
		['resort', 'Resorts'],
		['backcountry', 'Backcountry']
	];
	const href = (id: string) => resolve('/location/[id]', { id });
	// Shown elsewhere on the row: alerts and danger have their own marks; best day is gone.
	const HIDDEN = ['nws_alert', 'avalanche_danger', 'best_day'];
	const today = new Date().toLocaleDateString('en-US', {
		weekday: 'long',
		month: 'long',
		day: 'numeric'
	});

	// Storm watch: each active alert once, with the places it covers.
	const watch = $derived.by(() => {
		const byEvent: Record<string, string[]> = {};
		for (const r of rows ?? []) for (const a of r.alerts ?? []) (byEvent[a] ??= []).push(r.name);
		return Object.entries(byEvent).map(([event, names]) => ({ event, names }));
	});
	const leaders = $derived(
		[...(rows ?? [])]
			.filter((r) => (r.next5_cm ?? 0) > 0)
			.sort((a, b) => (b.next5_cm ?? 0) - (a.next5_cm ?? 0))
			.slice(0, 2)
	);
	// Likely-range bar, on one scale for all rows.
	const rangeMax = $derived(Math.max(10, ...(rows ?? []).map((r) => r.next5_p90_cm ?? 0)));
	const pctOf = (cm: number | null | undefined) => `${(((cm ?? 0) / rangeMax) * 100).toFixed(1)}%`;
	const pctSpan = (r: OverviewRow) =>
		`${((((r.next5_p90_cm ?? 0) - (r.next5_p10_cm ?? 0)) / rangeMax) * 100).toFixed(1)}%`;
</script>

<svelte:head><title>Snow Watch</title></svelte:head>

<div class="head">
	<div class="title">
		<span class="faint small">{today}</span>
		<h1>Where the snow is</h1>
	</div>
	<div class="filters">
		<label class="rank"
			>Rank by
			<select value={prefs.sort} onchange={(e) => prefs.setSort(e.currentTarget.value as SortKey)}>
				{#each sorts as [key, label] (key)}<option value={key}>{label}</option>{/each}
			</select>
		</label>
		<div class="seg" role="group" aria-label="Show">
			{#each kinds as [key, label] (key)}
				<button aria-pressed={prefs.kind === key} onclick={() => prefs.setKind(key)}>{label}</button
				>
			{/each}
		</div>
		<div class="seg" role="group" aria-label="View">
			<button aria-pressed={prefs.view === 'list'} onclick={() => prefs.setView('list')}
				>List</button
			>
			<button aria-pressed={prefs.view === 'map'} onclick={() => prefs.setView('map')}>Map</button>
		</div>
	</div>
</div>

{#if watch.length || leaders.length}
	<div class="watch">
		<span class="watch-lbl">Storm watch</span>
		{#each watch as w (w.event)}
			<span class="pill warn"
				><span class="dot"></span><strong>{w.event}</strong>
				<span class="muted">{w.names.join(', ')}</span></span
			>
		{/each}
		{#if leaders.length}
			<span class="pill"
				><span class="dot accent"></span><strong>Most snow</strong>
				<span class="muted"
					>{leaders
						.map((r) => `${r.name} ${snowNum(r.next5_cm, prefs.units)} ${c.snowUnit}`)
						.join(', ')}</span
				></span
			>
		{/if}
	</div>
{/if}

{#if error}
	<p class="card">Can't load the overview: {error}</p>
{:else if !rows}
	<p class="muted">Loading…</p>
{:else if !shown.length}
	<p class="card muted">No locations match.</p>
{:else if prefs.view === 'map'}
	<MapView rows={shown} units={prefs.units} {href} />
{:else}
	<section class="list">
		<div class="row header" aria-hidden="true">
			<span>#</span>
			<span>Location</span>
			<span>Next 5 days</span>
			<span>Day and night, 10 days</span>
			<span class="r">6–10</span>
			<span class="r">24 h</span>
			<span>Avalanche</span>
		</div>
		{#each shown as r, i (r.id)}
			<a class="row" href={href(r.id)}>
				<span class="rank-n num">{i + 1}</span>
				<div class="loc">
					<span class="name"
						>{r.name}{#if r.alerts?.length}<span
								class="alert-dot"
								title={r.alerts.join(', ')}
								aria-label="Active alert: {r.alerts.join(', ')}"
							></span>{/if}</span
					>
					<span class="faint small"
						>{r.region}{r.kind === 'backcountry' ? ' · Backcountry' : ''}</span
					>
					<FlagBadges
						flags={r.flags ?? []}
						runId={r.run_id}
						units={prefs.units}
						exclude={HIDDEN}
						max={2}
					/>
				</div>
				{#if r.run_id == null}
					<span class="faint small nodata">No forecast yet</span>
				{:else}
					<div class="next5">
						<span class="big num"
							>{snowNum(r.next5_cm, prefs.units)}<small>{c.snowUnit}</small></span
						>
						{#if r.next5_p10_cm != null && r.next5_p90_cm != null}
							<div class="range-wrap">
								<div class="range" aria-hidden="true">
									<span class="span" style:left={pctOf(r.next5_p10_cm)} style:width={pctSpan(r)}
									></span>
									<span class="mid" style:left={pctOf(r.next5_cm)}></span>
								</div>
								<span class="faint tiny"
									>{snowNum(r.next5_p10_cm, prefs.units)}–{snowNum(r.next5_p90_cm, prefs.units)} likely</span
								>
							</div>
						{/if}
					</div>
					<div class="barcell">
						<DayBars periods={r.periods ?? []} max={barMax} label={`${r.name}: 10-day snowfall`} />
					</div>
					<span class="stats">
						<span class="r num mid6"
							><span class="mlabel faint">6–10 </span>{snowNum(r.d6_10_cm, prefs.units)}</span
						>
						<span class="r num muted l24"
							><span class="mlabel faint">24 h </span>{snowNum(r.last24_cm, prefs.units)}</span
						>
					</span>
				{/if}
				<span class="avy">
					{#if r.danger && r.danger.status !== 'none'}<DangerChip
							level={r.danger.level}
							status={r.danger.status}
						/>{:else}<span class="faint">–</span>{/if}
				</span>
			</a>
		{/each}
		<div class="legend">
			<span><i class="sw snow"></i>Snow</span>
			<span><i class="sw heavy"></i>Heavy snow (6+ in in a day)</span>
			<span><i class="sw mix"></i>Mixed</span>
			<span><i class="sw rain"></i>Rain</span>
			<span><i class="sw night"></i>Shaded half = night</span>
			<span>One scale for all bars · days 6–10 faded · weekend days in the accent color</span>
		</div>
	</section>
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		flex-wrap: wrap;
		gap: 12px;
		margin: 4px 0 14px;
	}
	.title {
		display: grid;
		gap: 2px;
	}
	h1 {
		font-family: var(--font-num);
		font-size: 1.9rem;
		font-weight: 600;
		letter-spacing: -0.02em;
		margin: 0;
	}
	.small {
		font-size: 0.78rem;
	}
	.tiny {
		font-size: 0.7rem;
	}
	.filters {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		align-items: center;
	}
	.rank {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 3px 4px 3px 12px;
		border-radius: 999px;
		background: var(--surface-2);
		border: 1px solid var(--border);
		font-size: 0.82rem;
		color: var(--text-2);
	}
	.rank select {
		font: inherit;
		font-weight: 600;
		color: var(--text);
		background: var(--surface);
		border: 0;
		border-radius: 999px;
		padding: 5px 10px;
	}
	.watch {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		margin-bottom: 14px;
		font-size: 0.82rem;
	}
	.watch-lbl {
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--text-3);
	}
	.pill {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		padding: 6px 12px;
		border-radius: 999px;
		background: var(--accent-soft);
	}
	.pill.warn {
		background: var(--warn-bg);
	}
	.pill strong {
		font-weight: 600;
	}
	.dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--warn);
		flex-shrink: 0;
	}
	.dot.accent {
		background: var(--accent);
	}
	.list {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		overflow: hidden;
	}
	/* Phones: name and total on top, bars underneath. */
	.row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		grid-template-areas:
			'loc next5'
			'bars bars'
			'avy stats';
		gap: 6px 12px;
		align-items: center;
		padding: 12px 14px;
		border-bottom: 1px solid var(--grid);
		color: inherit;
		text-decoration: none;
	}
	.row:hover {
		background: color-mix(in srgb, var(--surface-2) 45%, transparent);
	}
	.row.header {
		display: none;
	}
	.rank-n {
		display: none;
	}
	.loc {
		grid-area: loc;
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.name {
		display: flex;
		align-items: center;
		gap: 6px;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.alert-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--warn);
		flex-shrink: 0;
	}
	.next5 {
		grid-area: next5;
		display: flex;
		align-items: center;
		gap: 10px;
		justify-content: flex-end;
	}
	.nodata {
		grid-area: next5;
	}
	.big {
		font-size: 1.45rem;
		font-weight: 600;
		letter-spacing: -0.01em;
		white-space: nowrap;
	}
	.big small {
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--text-2);
		margin-left: 2px;
	}
	.range-wrap {
		display: grid;
		gap: 3px;
	}
	.range {
		position: relative;
		height: 5px;
		width: 72px;
		background: var(--surface-2);
		border-radius: 3px;
	}
	.range .span {
		position: absolute;
		top: 0;
		bottom: 0;
		border-radius: 3px;
		background: color-mix(in srgb, var(--snow) 35%, var(--surface));
	}
	.range .mid {
		position: absolute;
		top: -2px;
		width: 2px;
		height: 9px;
		background: var(--snow);
	}
	.barcell {
		grid-area: bars;
		min-width: 0;
	}
	.mid6,
	.l24 {
		font-size: 0.95rem;
		font-weight: 600;
		white-space: nowrap;
	}
	.stats {
		grid-area: stats;
		justify-self: end;
		display: flex;
		gap: 16px;
	}
	.mlabel {
		font-family: var(--font-ui);
		font-size: 0.7rem;
		font-weight: 500;
		margin-right: 4px;
	}
	.avy {
		grid-area: avy;
	}
	.r {
		text-align: right;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 16px;
		padding: 12px 16px;
		font-size: 0.75rem;
		color: var(--text-3);
	}
	.legend span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.sw {
		width: 10px;
		height: 10px;
		border-radius: 2px;
	}
	.sw.snow {
		background: var(--snow);
	}
	.sw.heavy {
		background: var(--snow-heavy);
	}
	.sw.mix {
		background: var(--mix);
	}
	.sw.rain {
		background: var(--rain);
	}
	.sw.night {
		width: 8px;
		height: 12px;
		background: var(--surface-2);
		border: 1px solid var(--border);
	}
	/* Desktop: one dense line per location. */
	@media (min-width: 1100px) {
		.row {
			grid-template-columns: 24px minmax(200px, 1.3fr) 160px minmax(260px, 2fr) 56px 56px 150px;
			grid-template-areas: none;
			gap: 16px;
			padding: 9px 20px;
		}
		.row > * {
			grid-area: auto;
		}
		.row.header {
			display: grid;
			padding: 12px 20px 10px;
			font-size: 0.75rem;
			font-weight: 600;
			color: var(--text-3);
			background: color-mix(in srgb, var(--surface-2) 30%, var(--surface));
			border-bottom: 1px solid var(--border);
		}
		.row.header:hover {
			background: color-mix(in srgb, var(--surface-2) 30%, var(--surface));
		}
		.rank-n {
			display: block;
			font-size: 0.85rem;
			font-weight: 600;
			color: var(--text-3);
		}
		.next5 {
			justify-content: flex-start;
		}
		.stats {
			display: contents;
		}
		.mlabel {
			display: none;
		}
	}
</style>
