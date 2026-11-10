<script lang="ts">
	import ErrorNote from '../lib/components/ErrorNote.svelte';
	import { friendlyError } from '../lib/errors';
	import { resolve } from '$app/paths';
	import { getOverview } from '../lib/api';
	import { prefs } from '../lib/prefs.svelte';
	import { converters, snow, snowNum } from '../lib/units';
	import { dangerWord } from '../lib/conditions';
	import DailyBars from '../lib/components/DailyBars.svelte';
	import { describeDays, dailyTotals } from '../lib/daybars';
	import type { OverviewRow } from '../lib/types.gen';
	import ShareButton from '../lib/share/ShareButton.svelte';
	import { paint } from '../lib/share/canvas';
	import { drawOverviewCard } from '../lib/share/overviewCard';
	import { viewport } from '../lib/viewport.svelte';
	import { stormCycles } from '../lib/stormcycles';
	import { monthDay, weekday } from '../lib/time';

	let rows = $state<OverviewRow[] | null>(null);
	let error = $state<string | null>(null);
	let retry = $state(0);

	$effect(() => {
		void retry; // the Try again button runs this again
		error = null;
		getOverview()
			.then((r) => (rows = r))
			.catch((e: Error) => (error = friendlyError(e)));
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

	// --- Phones: one compact row per location ---
	const phone = $derived(viewport.phone);
	const list = $derived.by(() => {
		const out = (rows ?? []).map((r) => {
			const days = dailyTotals(r.periods ?? [], DAYS);
			return { r, days, total: days.reduce((a, d) => a + d.cm, 0) };
		});
		// "My order" is the order set on the Manage page, which is how the rows arrive.
		return prefs.sort === 'snow' ? [...out].sort((a, b) => b.total - a.total) : out;
	});
	const dayLabels = $derived(list.find((x) => x.days.length)?.days ?? []);
	const barH = (cm: number) => (cm > 0.1 ? Math.max(3, Math.round((cm / barMax) * 34)) : 0);
	const storm = $derived.by(() => {
		const s = stormCycles((rows ?? []).filter((r) => r.run_id != null))[0];
		if (!s) return null;
		const todayDate = (rows ?? []).flatMap((r) => r.periods ?? [])[0]?.date ?? s.start;
		const n = Math.round((Date.parse(s.start) - Date.parse(todayDate)) / 86400e3);
		const day = (d: string) => `${weekday(d)} ${monthDay(d)}`;
		return {
			when: s.start === s.end ? day(s.start) : `${day(s.start)} – ${day(s.end)}`,
			soon: n <= 0 ? 'now' : n === 1 ? 'tomorrow' : `in ${n} days`,
			top: s.locations.slice(0, 2),
			more: Math.max(0, s.locations.length - 2)
		};
	});
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
	<ErrorNote message={error} onretry={() => retry++} />
{:else if !rows}
	<p class="muted" aria-live="polite">Loading…</p>
{:else if !rows.length}
	<p class="card muted">
		No locations yet. The owner can add them under Settings → Manage locations.
	</p>
{:else if phone}
	{#if storm}
		<a class="stormbar" href={resolve('/calendar')}>
			<span class="sb-when">Storm {storm.soon} · {storm.when}</span>
			<span class="sb-where">
				{#each storm.top as l, i (l.id)}{i ? ' · ' : ''}{l.name}
					<strong class="num">{snowNum(l.total_cm, prefs.units)} {c.snowUnit}</strong
					>{/each}{#if storm.more}<span class="faint"> · +{storm.more} more</span>{/if}
			</span>
		</a>
	{/if}
	<div class="lhead">
		<button
			class="sortbtn"
			onclick={() => prefs.setSort(prefs.sort === 'mine' ? 'snow' : 'mine')}
			aria-label="Sort: {prefs.sort === 'mine' ? 'my order' : 'most snow first'}. Tap to change."
		>
			<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"
				><path d="M8 5v14M8 19l-3-3M8 19l3-3M16 19V5M16 5l-3 3M16 5l3 3" /></svg
			>
			{prefs.sort === 'mine' ? 'My order' : 'Most snow'}
		</button>
		<span class="ldays" aria-hidden="true">
			{#each dayLabels as d, i (d.date)}<span class:today={i === 0} class:weekend={d.weekend}
					>{weekday(d.date).slice(0, 1)}</span
				>{/each}
		</span>
		<span class="ltot">{DAYS} days, {c.snowUnit}</span>
	</div>
	<ul class="list">
		{#each list as { r, days, total } (r.id)}
			<li>
				<a class="lrow" href={href(r.id)}>
					<span class="lname">
						<strong>{r.name}</strong>
						{#if r.alerts?.length}
							<small class="alert">{r.alerts[0]}</small>
						{:else}
							<small
								>{r.region}{r.kind === 'backcountry' ? ' · Backcountry' : ''}{#if rated(r)}
									· Avalanche {r.danger?.level}{/if}</small
							>
						{/if}
					</span>
					{#if r.run_id == null}
						<small class="none">No forecast yet</small>
					{:else}
						<span
							class="lbars"
							role="img"
							aria-label={`${r.name}, snow by day: ${describeDays(days, (cm) => snow(cm, prefs.units))}`}
						>
							{#each days as d (d.date)}<i class={d.kind} style:height="{barH(d.cm)}px"></i>{/each}
						</span>
						<span class="ltotal num" class:zero={Number(snowNum(total, prefs.units)) === 0}
							>{snowNum(total, prefs.units)}</span
						>
					{/if}
				</a>
			</li>
		{/each}
	</ul>
	<div class="legend">
		<span><i style:background="var(--snow)"></i>Snow</span>
		<span
			><i style:background="var(--snow-heavy)"></i>{c.snowUnit === 'in' ? '6+ in' : '15+ cm'} in a day</span
		>
		<span><i style:background="var(--mix)"></i>Mixed</span>
		<span><i style:background="var(--rain)"></i>Rain</span>
	</div>
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
	/* --- Phones: rows, not cards --- */
	.stormbar {
		display: grid;
		gap: 2px;
		margin: 0 0 6px;
		padding: 10px 14px;
		border-radius: 14px;
		background: var(--accent-soft);
		color: var(--text);
		text-decoration: none;
		font-size: 0.85rem;
	}
	.sb-when {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--accent-ink);
	}
	.sb-where {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.lhead,
	.lrow {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.lhead {
		font-size: 0.7rem;
		color: var(--text-3);
	}
	/* A quiet one-tap sort: small type, but a full-height touch target. */
	.sortbtn {
		flex: 1 1 auto;
		display: flex;
		align-items: center;
		gap: 5px;
		height: 40px;
		padding: 0;
		border: 0;
		background: none;
		color: var(--text-2);
		font-size: 0.78rem;
		font-weight: 500;
		text-align: left;
		cursor: pointer;
	}
	.sortbtn svg {
		fill: none;
		stroke: var(--accent);
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.ldays,
	.lbars {
		flex: 0 0 105px;
		display: grid;
		grid-template-columns: repeat(7, minmax(0, 1fr));
	}
	.ldays span {
		text-align: center;
	}
	.ldays .weekend {
		color: var(--accent);
	}
	.ldays .today {
		color: var(--text);
		font-weight: 600;
	}
	.ltot,
	.ltotal {
		flex: 0 0 58px;
		text-align: right;
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.list li {
		border-top: 1px solid var(--grid);
	}
	.lrow {
		min-height: 58px;
		color: inherit;
		text-decoration: none;
	}
	.lname {
		flex: 1 1 auto;
		min-width: 0;
		display: grid;
		gap: 1px;
	}
	.lname strong,
	.lname small {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.lname strong {
		font-size: 0.98rem;
		font-weight: 600;
	}
	.list small {
		font-size: 0.76rem;
		color: var(--text-3);
	}
	.list small.alert {
		font-weight: 500;
	}
	.lbars {
		height: 36px;
		align-items: end;
		border-bottom: 1px solid var(--border);
	}
	.lbars i {
		margin: 0 2px;
		border-radius: 2px 2px 0 0;
		background: var(--snow);
	}
	.lbars i.heavy {
		background: var(--snow-heavy);
	}
	.lbars i.mix {
		background: var(--mix);
	}
	.lbars i.rain {
		background: var(--rain);
	}
	.ltotal {
		font-size: 1.4rem;
		font-weight: 600;
		letter-spacing: -0.02em;
	}
	.ltotal.zero {
		color: var(--text-3);
	}
	@media (max-width: 640px) {
		.head {
			margin-bottom: 10px;
		}
		h1 {
			font-size: 1.6rem;
		}
	}
</style>
