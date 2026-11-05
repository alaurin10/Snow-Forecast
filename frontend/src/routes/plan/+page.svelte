<script lang="ts">
	import { resolve } from '$app/paths';
	import { getPlan, getSnapshot } from '../../lib/api';
	import { prefs, type PlanSort } from '../../lib/prefs.svelte';
	import { newSnow, sortPlan } from '../../lib/plan';
	import { reasonText, skyWord } from '../../lib/conditions';
	import { snow, speed, temperature } from '../../lib/units';
	import { weekday, monthDay } from '../../lib/time';
	import type { PlanOut, Snapshot } from '../../lib/types.gen';
	import DangerChip from '../../lib/components/DangerChip.svelte';
	import RatingChip from '../../lib/components/RatingChip.svelte';
	import DayNightBars from '../../lib/charts/DayNightBars.svelte';

	let plan = $state<PlanOut | null>(null);
	let error = $state<string | null>(null);
	let date = $state<string | null>(null);
	let mode = $state<'list' | 'compare'>('list');
	let snaps = $state<Record<string, Snapshot>>({});

	$effect(() => {
		const want = date;
		getPlan(want ?? undefined)
			.then((p) => {
				plan = p;
				error = null;
				if (want === null) date = p.date;
			})
			.catch((e: Error) => (error = e.message));
	});

	const units = $derived(prefs.units);
	const rows = $derived(plan ? sortPlan(plan.rows, prefs.planSort) : []);
	const sorts: { key: PlanSort; label: string }[] = [
		{ key: 'rating', label: 'Rating' },
		{ key: 'snow', label: 'New snow' },
		{ key: 'name', label: 'Name' }
	];

	// Compare: stack the day/night bars of 2–4 locations on one scale.
	const picked = $derived(prefs.compare.filter((id) => plan?.rows.some((r) => r.id === id)));
	function toggle(id: string) {
		const now = prefs.compare.includes(id)
			? prefs.compare.filter((x) => x !== id)
			: [...prefs.compare, id];
		prefs.setCompare(now.slice(-4));
	}
	$effect(() => {
		for (const id of picked) {
			if (!snaps[id]) {
				getSnapshot(id)
					.then((s) => (snaps = { ...snaps, [id]: s }))
					.catch(() => {});
			}
		}
	});
	const shared = $derived(
		Math.max(
			0,
			...picked.flatMap((id) =>
				(snaps[id]?.bands[1].periods ?? []).map((p) => Math.max(p.snow_cm ?? 0, p.ens?.p90 ?? 0))
			)
		)
	);
	const keyFor = (s: Snapshot) =>
		s.bands[1].periods.find((p) => p.date === date && p.kind === 'day')?.key ?? null;
	const powderOf = (s: Snapshot) =>
		(s.days ?? []).filter((d) => d.rating === 'Powder').map((d) => d.date);
	const dayLabel = (d: { date: string; label: string }) =>
		d.label === 'Today' ? 'Today' : weekday(d.date);
</script>

<svelte:head><title>Plan a day · Snow Watch</title></svelte:head>

<div class="head">
	<h1>Plan a day</h1>
	<p class="muted small">
		Pick a day to compare every location. Snow is at mid-mountain: the night before plus the day.
	</p>
</div>

{#if error}
	<p class="card">Can't load the plan: {error}</p>
{:else if !plan}
	<p class="muted">Loading…</p>
{:else}
	<div class="dates" role="group" aria-label="Day">
		{#each plan.dates as d (d.date)}
			<button class="date" aria-pressed={d.date === plan.date} onclick={() => (date = d.date)}>
				<strong>{dayLabel(d)}</strong>
				<span class="faint">{monthDay(d.date)}</span>
			</button>
		{/each}
	</div>

	<div class="controls">
		<div class="seg" role="group" aria-label="View">
			<button aria-pressed={mode === 'list'} onclick={() => (mode = 'list')}>All locations</button>
			<button aria-pressed={mode === 'compare'} onclick={() => (mode = 'compare')}>Compare</button>
		</div>
		{#if mode === 'list'}
			<div class="seg" role="group" aria-label="Sort">
				{#each sorts as s (s.key)}
					<button aria-pressed={prefs.planSort === s.key} onclick={() => prefs.setPlanSort(s.key)}
						>{s.label}</button
					>
				{/each}
			</div>
		{/if}
	</div>

	{#if mode === 'list'}
		<!-- Phones: cards -->
		<div class="cards">
			{#each rows as r (r.id)}
				{@const d = r.day}
				<a class="card row" href={resolve('/location/[id]', { id: r.id })}>
					<div class="top">
						<strong class="name">{r.name}</strong>
						{#if d?.rating}<RatingChip rating={d.rating} score={d.score} />{/if}
					</div>
					{#if d}
						<div class="nums">
							<span class="big num">{snow(newSnow(r), units)}</span>
							<span class="muted"
								>{snow(d.overnight_cm, units)} overnight · {snow(d.day_cm, units)} day</span
							>
						</div>
						{#if (d.reasons ?? []).length}
							<div class="muted small">
								{(d.reasons ?? []).map((x) => reasonText(x, units)).join(' · ')}
							</div>
						{/if}
						<div class="facts small">
							<span>Summit gusts {speed(d.gust_max_kmh, units)}</span>
							<span>{temperature(d.tmax_c, units)} / {temperature(d.tmin_c, units)}</span>
							<span>{skyWord(d.wcode)}</span>
							<DangerChip level={r.danger.level} status={r.danger.status} label="Avalanche" />
						</div>
					{:else}
						<div class="muted small">No forecast for this day.</div>
					{/if}
				</a>
			{/each}
		</div>

		<!-- Desktop: one table -->
		<div class="card tablecard">
			<div class="table-wrap">
				<table class="data">
					<thead>
						<tr>
							<th>Location</th>
							<th>New snow</th>
							<th>Overnight / day</th>
							<th>Ski day</th>
							<th>Summit gusts</th>
							<th>High / low</th>
							<th>Sky</th>
							<th>Avalanche</th>
						</tr>
					</thead>
					<tbody>
						{#each rows as r (r.id)}
							{@const d = r.day}
							<tr>
								<th scope="row"><a href={resolve('/location/[id]', { id: r.id })}>{r.name}</a></th>
								<td class="num strong">{d ? snow(newSnow(r), units) : '–'}</td>
								<td class="num"
									>{d ? `${snow(d.overnight_cm, units)} / ${snow(d.day_cm, units)}` : '–'}</td
								>
								<td>
									{#if d?.rating}
										<RatingChip rating={d.rating} score={d.score} />
										<div class="faint reasons">
											{(d.reasons ?? []).map((x) => reasonText(x, units)).join(' · ')}
										</div>
									{:else}<span class="faint">{r.kind === 'backcountry' ? 'Tour' : '–'}</span>{/if}
								</td>
								<td class="num">{d ? speed(d.gust_max_kmh, units) : '–'}</td>
								<td class="num"
									>{d
										? `${temperature(d.tmax_c, units)} / ${temperature(d.tmin_c, units)}`
										: '–'}</td
								>
								<td>{d ? skyWord(d.wcode) : '–'}</td>
								<td><DangerChip level={r.danger.level} status={r.danger.status} /></td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
		<p class="faint small">
			Ski-day ratings are for resorts during lift hours. Tours aren't rated: check the avalanche
			forecast.
		</p>
	{:else}
		<div class="card pick">
			<div class="muted small">Pick 2–4 locations to compare on one scale.</div>
			<div class="chips">
				{#each plan.rows as r (r.id)}
					<label class="pickone">
						<input
							type="checkbox"
							checked={picked.includes(r.id)}
							disabled={!picked.includes(r.id) && picked.length >= 4}
							onchange={() => toggle(r.id)}
						/>
						{r.name}
					</label>
				{/each}
			</div>
		</div>
		{#if picked.length < 2}
			<p class="muted">Pick at least two locations.</p>
		{:else}
			<div class="stack">
				{#each picked as id (id)}
					{@const s = snaps[id]}
					<section class="card">
						{#if s}
							<DayNightBars
								title={s.location.name}
								periods={s.bands[1].periods}
								{units}
								selected={keyFor(s)}
								powder={powderOf(s)}
								maxCm={shared}
							/>
						{:else}
							<p class="muted">Loading…</p>
						{/if}
					</section>
				{/each}
			</div>
			<p class="faint small">Mid-mountain snow; every chart uses the same scale.</p>
		{/if}
	{/if}
{/if}

<style>
	.head h1 {
		font-size: 1.3rem;
		margin: 4px 0 2px;
	}
	.small {
		font-size: 0.85rem;
	}
	.head .small {
		margin: 0 0 10px;
	}
	.dates {
		display: flex;
		gap: 6px;
		overflow-x: auto;
		padding-bottom: 6px;
		margin-bottom: 8px;
		-webkit-overflow-scrolling: touch;
	}
	.date {
		display: grid;
		justify-items: center;
		min-width: 62px;
		padding: 6px 8px;
		border-radius: 10px;
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--text);
		cursor: pointer;
		font: inherit;
		font-size: 0.85rem;
	}
	.date[aria-pressed='true'] {
		border-color: var(--snow);
		box-shadow: inset 0 0 0 1px var(--snow);
	}
	.date .faint {
		font-size: 0.75rem;
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-bottom: 10px;
	}
	.cards {
		display: grid;
		gap: 10px;
	}
	.row {
		display: grid;
		gap: 4px;
		color: var(--text);
		text-decoration: none;
	}
	.top {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
	}
	.name {
		font-size: 1rem;
	}
	.nums {
		display: flex;
		align-items: baseline;
		gap: 8px;
		flex-wrap: wrap;
	}
	.big {
		font-family: var(--font-num);
		font-size: 1.6rem;
		font-weight: 600;
	}
	.facts {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		align-items: center;
		color: var(--text-2);
	}
	.tablecard {
		display: none;
	}
	.strong {
		font-weight: 600;
	}
	.reasons {
		font-size: 0.75rem;
		margin-top: 2px;
		max-width: 260px;
	}
	th a {
		color: var(--text);
	}
	@media (min-width: 1100px) {
		.cards {
			display: none;
		}
		.tablecard {
			display: block;
		}
	}
	.pick {
		display: grid;
		gap: 8px;
		margin-bottom: 10px;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 14px;
	}
	.pickone {
		display: flex;
		gap: 6px;
		align-items: center;
		font-size: 0.9rem;
	}
	.stack {
		display: grid;
		gap: 10px;
	}
</style>
