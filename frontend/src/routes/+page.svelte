<script lang="ts">
	import { resolve } from '$app/paths';
	import { getOverview } from '../lib/api';
	import { prefs } from '../lib/prefs.svelte';
	import { converters, snowNum } from '../lib/units';
	import { dangerWord } from '../lib/conditions';
	import DailyBars from '../lib/components/DailyBars.svelte';
	import { dailyTotals } from '../lib/daybars';
	import type { OverviewRow } from '../lib/types.gen';
	import ShareButton from '../lib/share/ShareButton.svelte';
	import { paint } from '../lib/share/canvas';
	import { drawOverviewCard } from '../lib/share/overviewCard';

	let rows = $state<OverviewRow[] | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		getOverview()
			.then((r) => (rows = r))
			.catch((e: Error) => (error = e.message));
	});

	const c = $derived(converters(prefs.units));
	// One scale for every card, so bars compare across locations.
	const barMax = $derived(
		Math.max(5, ...(rows ?? []).flatMap((r) => dailyTotals(r.periods ?? [], DAYS).map((d) => d.cm)))
	);
	// The card's total is the sum of its bars, so the two always cover the same days.
	const DAYS = 7;
	const weekTotal = (r: OverviewRow) =>
		dailyTotals(r.periods ?? [], DAYS).reduce((a, d) => a + d.cm, 0);
	const href = (id: string) => resolve('/location/[id]', { id });
	const today = new Date().toLocaleDateString('en-US', {
		weekday: 'long',
		month: 'long',
		day: 'numeric'
	});
	// The newest forecast run among the locations, for the share image's footer.
	const latest = $derived(
		(rows ?? [])
			.map((r) => r.generated_at ?? '')
			.sort()
			.at(-1) ?? ''
	);
	const rated = (r: OverviewRow) => r.danger?.status === 'current' && !!r.danger.level;
</script>

<svelte:head><title>Snow Watch</title></svelte:head>

<div class="head">
	<span class="faint small">{today}</span>
	<div class="titlerow">
		<h1>Where the snow is</h1>
		{#if rows?.length}
			<ShareButton
				label="Share the overview"
				filename="snow-watch-overview"
				render={(shape) =>
					paint(shape, (ctx, p) =>
						drawOverviewCard(
							ctx,
							shape,
							{ rows: rows ?? [], units: prefs.units, days: DAYS, generatedAt: latest },
							p
						)
					)}
			/>
		{/if}
	</div>
</div>

{#if error}
	<p class="card">Can't load the overview: {error}</p>
{:else if !rows}
	<p class="muted">Loading…</p>
{:else if !rows.length}
	<p class="card muted">No locations yet. Add some on the admin page.</p>
{:else}
	<ul class="grid">
		{#each rows as r (r.id)}
			<li>
				<a class="card loc" href={href(r.id)}>
					<div class="top">
						<div class="name">
							<strong>{r.name}</strong>
							<span class="faint small"
								>{r.region}{r.kind === 'backcountry' ? ' · Backcountry' : ''}</span
							>
						</div>
						{#if r.run_id != null}
							<div class="total">
								<span class="big num"
									>{snowNum(weekTotal(r), prefs.units)}<small>{c.snowUnit}</small></span
								>
								<span class="faint small">next {DAYS} days</span>
							</div>
						{/if}
					</div>
					{#if r.run_id == null}
						<span class="faint small">No forecast yet</span>
					{:else}
						<DailyBars
							periods={r.periods ?? []}
							max={barMax}
							units={prefs.units}
							days={DAYS}
							label={`${r.name}: snow for the next ${DAYS} days`}
						/>
					{/if}
					{#if r.alerts?.length || rated(r)}
						<div class="notes">
							{#if r.alerts?.length}<span class="alert"><i></i>{r.alerts[0]}</span>{/if}
							{#if rated(r)}
								<span class="avy"
									><i class="d{r.danger?.level}"></i>Avalanche {r.danger?.level} ·
									{dangerWord(r.danger?.level)}</span
								>
							{/if}
						</div>
					{/if}
				</a>
			</li>
		{/each}
	</ul>
	<div class="legend">
		<span><i style:background="var(--snow)"></i>Snow</span>
		<span
			><i style:background="var(--snow-heavy)"></i>Heavy snow ({c.snowUnit === 'in'
				? '6+ inches'
				: '15+ cm'} in a day)</span
		>
		<span><i style:background="var(--mix)"></i>Mixed</span>
		<span><i style:background="var(--rain)"></i>Rain</span>
		<span>Daily snow ({c.snowUnit === 'in' ? 'inches' : 'cm'})</span>
	</div>
{/if}

<style>
	.head {
		display: grid;
		gap: 2px;
		margin: 4px 0 16px;
	}
	.titlerow {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
	}
	h1 {
		font-family: var(--font-num);
		font-size: 1.9rem;
		font-weight: 600;
		letter-spacing: -0.02em;
		margin: 0;
	}
	.small {
		font-size: 0.8rem;
	}
	.grid {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 12px;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
	}
	.loc {
		display: grid;
		gap: 14px;
		padding: 16px 18px;
		color: inherit;
		text-decoration: none;
		height: 100%;
		align-content: start;
	}
	.loc:hover {
		border-color: var(--accent);
	}
	.top {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 12px;
	}
	.name {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.name strong {
		font-size: 1.02rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.total {
		display: grid;
		justify-items: end;
		gap: 2px;
		flex-shrink: 0;
	}
	.big {
		font-size: 1.9rem;
		font-weight: 600;
		line-height: 1;
		letter-spacing: -0.02em;
	}
	.big small {
		font-family: var(--font-ui);
		font-size: 0.85rem;
		font-weight: 500;
		color: var(--text-2);
		margin-left: 3px;
		letter-spacing: 0;
	}
	.notes {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 14px;
		font-size: 0.8rem;
		color: var(--text-2);
		border-top: 1px solid var(--grid);
		padding-top: 10px;
	}
	.notes span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.notes i {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.alert {
		color: var(--warn-ink);
		font-weight: 600;
	}
	.alert i {
		background: var(--warn);
	}
	.avy i {
		border-radius: 2px;
		outline: 1px solid var(--border);
	}
	.avy i.d1 {
		background: var(--d1);
	}
	.avy i.d2 {
		background: var(--d2);
	}
	.avy i.d3 {
		background: var(--d3);
	}
	.avy i.d4 {
		background: var(--d4);
	}
	.avy i.d5 {
		background: var(--d5);
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 16px;
		margin-top: 14px;
		font-size: 0.75rem;
		color: var(--text-3);
	}
	.legend span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.legend i {
		width: 10px;
		height: 10px;
		border-radius: 3px;
	}
</style>
