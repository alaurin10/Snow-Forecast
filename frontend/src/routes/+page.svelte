<!-- Where the snow is: every location as a row (name, a week of daily snow bars, the
     total), with the storms ahead above. The same rows on every screen; desktops add the
     amounts under the bars, the avalanche rating and the next-5-days range. -->
<script lang="ts">
	import ErrorNote from '../lib/components/ErrorNote.svelte';
	import { friendlyError } from '../lib/errors';
	import { resolve } from '$app/paths';
	import { getOverview } from '../lib/api';
	import { prefs } from '../lib/prefs.svelte';
	import { converters, snow, snowNum } from '../lib/units';
	import { dangerWord } from '../lib/conditions';
	import { describeDays, dailyTotals } from '../lib/daybars';
	import type { OverviewRow } from '../lib/types.gen';
	import ShareButton from '../lib/share/ShareButton.svelte';
	import { paint } from '../lib/share/canvas';
	import { drawOverviewCard } from '../lib/share/overviewCard';
	import { viewport } from '../lib/viewport.svelte';
	import { stormCycles, type StormCycle } from '../lib/stormcycles';
	import LocationDaySheet from '../lib/components/LocationDaySheet.svelte';
	import StormSheet from '../lib/components/StormSheet.svelte';
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
	// The row's total is the sum of its bars, so the two always cover the same days.
	const DAYS = 7;
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
	const wide = $derived(!viewport.phone);

	const list = $derived.by(() => {
		const out = (rows ?? []).map((r) => {
			const days = dailyTotals(r.periods ?? [], DAYS);
			return { r, days, total: days.reduce((a, d) => a + d.cm, 0) };
		});
		// "My order" is the order set on the Manage page, which is how the rows arrive.
		return prefs.sort === 'snow' ? [...out].sort((a, b) => b.total - a.total) : out;
	});
	// One scale for every row, so bars compare across locations.
	const barMax = $derived(Math.max(5, ...list.flatMap((x) => x.days.map((d) => d.cm))));
	// The avalanche column only when some location has a rating to show.
	const anyRated = $derived(list.some((x) => rated(x.r)));
	const dayLabels = $derived(list.find((x) => x.days.length)?.days ?? []);
	const barH = (cm: number, tall: number) =>
		cm > 0.1 ? Math.max(3, Math.round((cm / barMax) * tall)) : 0;
	// A storm, and a day picked from it, open in popups over the overview.
	let openStorm = $state<StormCycle | null>(null);
	let openDay = $state<{ id: string; name: string; date: string } | null>(null);
	const storms = $derived.by(() => {
		const all = stormCycles((rows ?? []).filter((r) => r.run_id != null));
		const todayDate = (rows ?? []).flatMap((r) => r.periods ?? [])[0]?.date ?? '';
		const day = (d: string) => `${weekday(d)} ${monthDay(d)}`;
		return all.slice(0, 4).map((s, k) => {
			const n = todayDate ? Math.round((Date.parse(s.start) - Date.parse(todayDate)) / 86400e3) : 0;
			return {
				key: s.start + s.end,
				cycle: s,
				first: k === 0,
				when: s.start === s.end ? day(s.start) : `${day(s.start)} – ${day(s.end)}`,
				soon: n <= 0 ? 'Now' : n === 1 ? 'Tomorrow' : `In ${n} days`,
				top: s.locations.slice(0, 2),
				more: Math.max(0, s.locations.length - 2)
			};
		});
	});
</script>

<svelte:head><title>Snow Watch</title></svelte:head>

<header class="head">
	<div>
		<span class="date">{today}</span>
		<h1>Where the snow is</h1>
	</div>
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
</header>

{#if error}
	<ErrorNote message={error} onretry={() => retry++} />
{:else if !rows}
	<p class="loading glass" aria-live="polite">Loading…</p>
{:else if !rows.length}
	<p class="card muted">
		No locations yet. The owner can add them under Settings → Manage locations.
	</p>
{:else}
	{#if storms.length}
		<div class="storms" aria-label="Storms ahead">
			{#each storms as s (s.key)}
				<button class="storm glass" class:first={s.first} onclick={() => (openStorm = s.cycle)}>
					<span class="eyebrow">{s.soon}</span>
					<strong>{s.when}</strong>
					<span class="where"
						>{#each s.top as l, i (l.id)}{i ? ' · ' : ''}{l.name}
							<b class="num">{snowNum(l.total_cm, prefs.units)} {c.snowUnit}</b
							>{/each}{#if s.more}<span class="faint"> · +{s.more} more</span>{/if}</span
					>
				</button>
			{/each}
		</div>
	{/if}

	<section class="card listcard" aria-label="Locations">
		<div class="lhead">
			<button
				class="sortbtn"
				onclick={() => prefs.setSort(prefs.sort === 'mine' ? 'snow' : 'mine')}
				aria-label="Sort: {prefs.sort === 'mine' ? 'my order' : 'most snow first'}. Change."
			>
				<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
					><path d="M8 5v14M8 19l-3-3M8 19l3-3M16 19V5M16 5l-3 3M16 5l3 3" /></svg
				>
				{prefs.sort === 'mine' ? 'My order' : 'Most snow'}
			</button>
			{#if wide && anyRated}<span class="lavy"></span>{/if}
			<span class="ldays" aria-hidden="true">
				{#each dayLabels as d, i (d.date)}<span class:today={i === 0} class:weekend={d.weekend}
						>{wide ? d.label : weekday(d.date).slice(0, 1)}</span
					>{/each}
			</span>
			<span class="ltot">{DAYS} days, {c.snowUnit}</span>
			{#if wide}<span class="l5">Next 5 days</span>{/if}
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
									>{r.region}{r.kind === 'backcountry'
										? ' · Backcountry'
										: ''}{#if rated(r) && !wide}
										· Avalanche {r.danger?.level}{/if}</small
								>
							{/if}
						</span>
						{#if wide && anyRated}
							<span class="lavy">
								{#if rated(r)}<span class="danger d{r.danger?.level}"
										>{r.danger?.level} · {dangerWord(r.danger?.level)}</span
									>{/if}
							</span>
						{/if}
						{#if r.run_id == null}
							<small class="none">No forecast yet</small>
						{:else}
							<span
								class="lbars"
								role="img"
								aria-label={`${r.name}, snow by day: ${describeDays(days, (cm) => snow(cm, prefs.units))}`}
							>
								{#each days as d (d.date)}<span class="bar"
										><i class={d.kind} style:height="{barH(d.cm, wide ? 40 : 34)}px"
										></i>{#if wide}<small class="num" class:zero={d.cm < 0.1}
												>{d.cm >= 0.1 ? snowNum(d.cm, prefs.units) : '–'}</small
											>{/if}</span
									>{/each}
							</span>
							<span class="ltotal num" class:zero={Number(snowNum(total, prefs.units)) === 0}
								>{snowNum(total, prefs.units)}</span
							>
							{#if wide}
								<span class="l5 num"
									><b>{snowNum(r.next5_cm, prefs.units)} {c.snowUnit}</b>{#if r.next5_p90_cm}<small
											>{snowNum(r.next5_p10_cm, prefs.units)}–{snowNum(r.next5_p90_cm, prefs.units)} likely</small
										>{/if}</span
								>
							{/if}
						{/if}
					</a>
				</li>
			{/each}
		</ul>
	</section>
	<div class="legend">
		<span><i style:background="var(--snow)"></i>Snow</span>
		<span
			><i style:background="var(--snow-heavy)"></i>{c.snowUnit === 'in' ? '6 in' : '15 cm'} or more in
			a day</span
		>
		<span><i style:background="var(--mix)"></i>Mixed</span>
		<span><i style:background="var(--rain)"></i>Rain</span>
	</div>
{/if}

{#if openStorm}
	<StormSheet
		cycle={openStorm}
		rows={(rows ?? []).filter((r) => r.run_id != null)}
		units={prefs.units}
		onday={(id, name, date) => {
			openStorm = null;
			openDay = { id, name, date };
		}}
		onclose={() => (openStorm = null)}
	/>
{/if}
{#if openDay}
	<LocationDaySheet
		id={openDay.id}
		name={openDay.name}
		date={openDay.date}
		units={prefs.units}
		onclose={() => (openDay = null)}
	/>
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 12px;
		padding: 18px 4px 14px;
	}
	.date {
		font-size: 0.86rem;
		font-weight: 600;
	}
	h1 {
		font-family: var(--font-num);
		font-size: 2.9rem;
		font-weight: 700;
		letter-spacing: -0.03em;
		line-height: 1.05;
		margin: 2px 0 0;
	}
	.loading {
		display: inline-block;
		padding: 8px 16px;
		border-radius: 999px;
		color: var(--text-2);
	}
	.storms {
		display: grid;
		grid-auto-flow: column;
		grid-auto-columns: minmax(200px, 1fr);
		gap: 10px;
		/* Room for the cards' shadow, which the scrolling row would otherwise clip. */
		margin: -4px -12px 2px;
		padding: 4px 12px 14px;
		scroll-padding-inline: 12px;
		overflow-x: auto;
		scroll-snap-type: x mandatory;
		scrollbar-width: none;
	}
	.storms::-webkit-scrollbar {
		display: none;
	}
	.storm {
		border: 1px solid var(--glass-border);
		font: inherit;
		text-align: left;
		cursor: pointer;
		scroll-snap-align: start;
		box-shadow: var(--glass-shadow-sm);
		display: grid;
		gap: 2px;
		padding: 11px 16px;
		border-radius: 22px;
		color: var(--text);
		text-decoration: none;
		font-size: 0.88rem;
		min-width: 0;
	}
	.storm.first {
		background-image: linear-gradient(0deg, var(--accent-soft), var(--accent-soft));
	}
	.storm.first .eyebrow {
		color: var(--accent-ink);
	}
	.where {
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.where b {
		color: var(--text);
		font-weight: 700;
	}
	.listcard {
		padding: 4px 10px 6px;
	}
	.lhead,
	.lrow {
		display: flex;
		align-items: center;
		gap: 14px;
	}
	.lhead {
		padding: 0 8px;
		font-size: 0.74rem;
		color: var(--text-2);
	}
	/* A quiet one-tap sort: small type, but a full-height touch target. */
	.sortbtn {
		flex: 1 1 auto;
		display: flex;
		align-items: center;
		gap: 6px;
		height: 44px;
		padding: 0;
		border: 0;
		background: none;
		color: var(--text);
		font-size: 0.84rem;
		font-weight: 600;
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
		flex: 0 0 112px;
		display: grid;
		grid-template-columns: repeat(7, minmax(0, 1fr));
	}
	.ldays span {
		text-align: center;
	}
	.ldays .weekend {
		color: var(--accent-ink);
	}
	.ldays .today {
		color: var(--text);
		font-weight: 700;
	}
	.ltot,
	.ltotal {
		flex: 0 0 56px;
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
		min-height: 64px;
		padding: 0 8px;
		border-radius: 16px;
		color: inherit;
		text-decoration: none;
		transition: background-color var(--ease);
	}
	.lrow:hover {
		background: var(--hover);
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
		font-size: 1rem;
		font-weight: 600;
	}
	.list small {
		font-size: 0.78rem;
		color: var(--text-2);
	}
	.list small.alert {
		font-weight: 600;
		color: var(--warn-ink);
	}
	.lbars {
		height: 38px;
		align-items: end;
		border-bottom: 1px solid var(--border);
	}
	.bar {
		display: grid;
		align-items: end;
		height: 100%;
	}
	.bar i {
		margin: 0 2px;
		border-radius: 3px 3px 0 0;
		background: var(--snow);
	}
	.bar i.heavy {
		background: var(--snow-heavy);
	}
	.bar i.mix {
		background: var(--mix);
	}
	.bar i.rain {
		background: var(--rain);
	}
	.ltotal {
		font-size: 1.45rem;
		font-weight: 600;
		letter-spacing: -0.02em;
	}
	.ltotal.zero {
		color: var(--text-3);
	}
	.none {
		flex: 0 0 auto;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 16px;
		margin: 12px 8px 0;
		font-size: 0.78rem;
		font-weight: 500;
		color: var(--text);
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

	/* Tablets and desktops: wider bars with the amounts under them, the avalanche rating
	   and the next-5-days range. */
	@media (min-width: 641px) {
		.lrow {
			min-height: 76px;
		}
		.ldays,
		.lbars {
			flex: 0 0 clamp(300px, 36vw, 460px);
			gap: 6px;
		}
		.lbars {
			height: 62px;
			border-bottom: 0;
		}
		.bar {
			grid-template-rows: 1fr auto;
			gap: 3px;
		}
		.bar i {
			margin: 0 22%;
			align-self: end;
		}
		.bar small {
			text-align: center;
			font-size: 0.78rem;
			font-weight: 600;
			color: var(--text);
		}
		.bar small.zero {
			color: var(--text-3);
			font-weight: 400;
		}
		.lavy {
			flex: 0 0 140px;
		}
		.l5 {
			flex: 0 0 120px;
			text-align: right;
			display: grid;
		}
		.l5 b {
			font-weight: 600;
		}
		.l5 small {
			font-size: 0.75rem;
			color: var(--text-2);
		}
		.ltotal {
			font-size: 1.6rem;
		}
	}
	@media (max-width: 1099px) and (min-width: 641px) {
		.lavy {
			display: none;
		}
	}
	/* Beside the rail: narrower bars, so long names have room. */
	@media (min-width: 1100px) {
		.ldays,
		.lbars {
			flex-basis: clamp(280px, calc(30vw - 40px), 440px);
		}
	}
	@media (max-width: 640px) {
		.head {
			padding-top: 6px;
		}
		h1 {
			font-size: 1.9rem;
		}
		.storms {
			grid-auto-columns: 78%;
			margin: -4px -16px 0;
			padding: 4px 16px 14px;
			scroll-padding-inline: 16px;
		}
	}
</style>
