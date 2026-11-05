<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { ApiError, getAvalanche, getSnapshot, getTrend, getVerification } from '../../../lib/api';
	import { prefs, type BandName } from '../../../lib/prefs.svelte';
	import { crosshair } from '../../../lib/crosshair.svelte';
	import type {
		AvalancheView,
		Flag,
		PeriodOut,
		Snapshot,
		TrendOut,
		VerificationOut
	} from '../../../lib/types.gen';
	import { elevation, snow, type UnitSystem } from '../../../lib/units';
	import { ENSEMBLE_NAMES } from '../../../lib/models';
	import { dateOf, weekday } from '../../../lib/time';
	import DayNightBars from '../../../lib/charts/DayNightBars.svelte';
	import HourlyStack from '../../../lib/charts/HourlyStack.svelte';
	import ModelAgreement from '../../../lib/charts/ModelAgreement.svelte';
	import Exceedance from '../../../lib/charts/Exceedance.svelte';
	import TrendChart from '../../../lib/charts/TrendChart.svelte';
	import PeriodSheet from '../../../lib/charts/PeriodSheet.svelte';
	import Tiles from '../../../lib/components/Tiles.svelte';
	import PeriodTable from '../../../lib/components/PeriodTable.svelte';
	import BandTable from '../../../lib/components/BandTable.svelte';
	import RatingChip from '../../../lib/components/RatingChip.svelte';
	import BackcountryTab from '../../../lib/backcountry/BackcountryTab.svelte';
	import StationPanel from '../../../lib/observed/StationPanel.svelte';
	import Scorecard from '../../../lib/observed/Scorecard.svelte';
	import TrendDays from '../../../lib/components/TrendDays.svelte';
	import Webcams from '../../../lib/components/Webcams.svelte';
	import { flagText, flagTitle, isNew } from '../../../lib/flags';
	import DangerPyramid from '../../../lib/backcountry/DangerPyramid.svelte';
	import { reasonText } from '../../../lib/conditions';

	type Tab = 'forecast' | 'models' | 'backcountry' | 'observed';

	const id = $derived(page.params.id ?? '');
	let snap = $state<Snapshot | null>(null);
	let trend = $state<TrendOut | null>(null);
	let error = $state<string | null>(null);
	let tab = $state<Tab>('forecast');
	let selected = $state<PeriodOut | null>(null);
	let avy = $state<AvalancheView | null>(null);
	let scores = $state<VerificationOut | null>(null);

	$effect(() => {
		const current = id;
		snap = null;
		error = null;
		crosshair.reset();
		getSnapshot(current)
			.then((s) => {
				snap = s;
				// Deep link from the Calendar: open that period's details.
				const key = page.url.searchParams.get('period');
				if (key) {
					const b = s.bands.find((x) => x.band === prefs.band) ?? s.bands[1];
					selected = b.periods.find((x) => x.key === key) ?? null;
				}
			})
			.catch(
				(e: Error) =>
					(error =
						e instanceof ApiError && e.status === 404
							? 'No forecast yet for this location.'
							: e.message)
			);
		getTrend(current)
			.then((t) => (trend = t))
			.catch(() => (trend = null));
		scores = null;
		getVerification(current)
			.then((v) => (scores = v))
			.catch(() => (scores = null));
		avy = null;
		getAvalanche()
			.then((all) => (avy = all[current] ?? null))
			.catch(() => (avy = null));
	});

	const tabs = $derived<Tab[]>(
		snap?.location.kind === 'backcountry'
			? ['forecast', 'backcountry', 'models', 'observed']
			: ['forecast', 'models', 'backcountry', 'observed']
	);
	const names: Record<Tab, string> = {
		forecast: 'Forecast',
		models: 'Models',
		backcountry: 'Backcountry',
		observed: 'Observed'
	};
	const band = $derived(
		snap ? (snap.bands.find((b) => b.band === prefs.band) ?? snap.bands[1]) : null
	);
	const units = $derived<UnitSystem>(prefs.units);
	const mid = $derived(snap?.bands[1] ?? null);
	const membersFor = (name: string): number[] => {
		if (!snap || !band || !mid) return [];
		const m = mid.windows[name]?.members_cm ?? [];
		const scale = band.band === 'mid' ? 1 : (band.windows[name]?.scale ?? null);
		return scale === null ? [] : m.map((v) => v * scale);
	};
	const backcountry = $derived(snap?.location.kind === 'backcountry');
	const powder = $derived(
		(snap?.days ?? []).filter((d) => d.rating === 'Powder').map((d) => d.date)
	);
	const best = $derived.by(() => {
		const rated = (snap?.days ?? []).filter((d) => d.score !== null && d.score !== undefined);
		const top = Math.max(0, ...rated.map((d) => d.score ?? 0));
		return top >= 3 ? (rated.find((d) => d.score === top) ?? null) : null;
	});
	// Flags for "Heads up", plus avalanche danger 4+ while the center's rating is current.
	const headsUp = $derived.by(() => {
		const out: Flag[] = (snap?.flags ?? []).filter((f) => f.type !== 'best_day');
		if (avy?.status === 'current' && (avy.today_max ?? 0) >= 4)
			out.unshift({ type: 'avalanche_danger', severity: 'warning', value: avy.today_max });
		return out;
	});
	const selectedDay = $derived(
		selected && selected.kind === 'day'
			? ((snap?.days ?? []).find((d) => d.date === selected!.date) ?? null)
			: null
	);
	// Ridge wind on the wind chart for tours, and for any location's summit band.
	const ridge = $derived(backcountry || band?.band === 'summit' ? (snap?.ridge ?? null) : null);
	const updated = $derived(
		snap
			? new Date(snap.generated_at).toLocaleString('en-US', {
					weekday: 'short',
					hour: 'numeric',
					minute: '2-digit'
				})
			: ''
	);
</script>

<svelte:head
	><title>{snap ? `${snap.location.name} · Snow Watch` : 'Snow Watch'}</title></svelte:head
>

{#if error}
	<p class="card">{error} <a href={resolve('/')}>All locations</a></p>
{:else if !snap || !band}
	<p class="muted">Loading…</p>
{:else}
	<div class="loc-head">
		<div class="title">
			<a class="back faint" href={resolve('/')}>← All locations</a>
			<h1>{snap.location.name}</h1>
			<div class="muted sub">
				{snap.location.region} · {band.label}
				{elevation(band.elev_m, units)} · updated {updated}
			</div>
		</div>
		<div class="seg" role="group" aria-label="Elevation">
			{#each snap.bands as b (b.band)}
				<button
					aria-pressed={band.band === b.band}
					onclick={() => prefs.setBand(b.band as BandName)}>{b.label}</button
				>
			{/each}
		</div>
	</div>

	{#each snap.alerts as a, i (i)}
		<div class="alert"><strong>{a.event}</strong> {a.headline ?? ''}</div>
	{/each}

	<nav class="tabs" aria-label="Sections">
		{#each tabs as t (t)}
			<button aria-current={tab === t ? 'page' : undefined} onclick={() => (tab = t)}
				>{names[t]}</button
			>
		{/each}
	</nav>

	{#if tab === 'forecast'}
		<div class="stackcol">
			{#if backcountry}
				<section class="card thin">
					<DangerPyramid view={avy} tz={snap.location.tz} today={dateOf(snap.now)} compact />
				</section>
			{/if}
			<Tiles {band} {units} />
			{#if headsUp.length}
				<section class="card thin heads">
					<h2>Heads up</h2>
					<ul>
						{#each headsUp as f, i (i)}
							<li class={f.severity}>
								<strong>{flagTitle(f)}</strong>{#if isNew(f, snap.run_id)}<span class="new"
										>New</span
									>{/if}
								<span class="muted">{flagText(f, units)}</span>
							</li>
						{/each}
					</ul>
				</section>
			{/if}
			{#if best}
				<section class="card thin best">
					<span class="lead">Best ski day</span>
					<strong>{best.label === 'Today' ? 'Today' : weekday(best.date)}</strong>
					<RatingChip rating={best.rating} score={best.score} />
					<span class="muted"
						>{(best.reasons ?? []).map((r) => reasonText(r, units)).join(' · ')}</span
					>
				</section>
			{/if}
			<section class="card">
				<DayNightBars
					periods={band.periods}
					{units}
					selected={selected?.key ?? null}
					onselect={(p) => (selected = p)}
					{powder}
				/>
			</section>
			<div class="split">
				<section class="card">
					<h2>Hourly</h2>
					<HourlyStack {band} bands={snap.bands} {units} {ridge} />
				</section>
				<aside class="side">
					<section class="card">
						<h2>About this forecast</h2>
						<p class="muted small">
							Snow is the median of {snap.models.length} weather models, switching to the ensemble mean
							{#if snap.basis_switch}from {weekday(dateOf(snap.basis_switch))}{/if}
							when fewer than three models still run. Ranges come from
							{Object.entries(snap.ensembles)
								.map(([s, n]) => `${ENSEMBLE_NAMES[s] ?? s} (${n})`)
								.join(', ') || 'no ensembles'}.
						</p>
						{#if band.windows['next5'].snow_cm_slr !== null && band.windows['next5'].snow_cm_slr !== band.windows['next5'].snow_cm}
							<p class="muted small">
								With a temperature-based snow-to-liquid ratio the next 5 days would be
								<strong>{snow(band.windows['next5'].snow_cm_slr, units)}</strong>.
							</p>
						{/if}
					</section>
					{#if Object.keys(snap.location.links).length}
						<section class="card">
							<h2>Links</h2>
							<ul class="links">
								{#each Object.entries(snap.location.links) as [name, url] (name)}
									<!-- External site: resolve() is only for routes in this app. -->
									<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
									<li><a href={url} rel="noopener" target="_blank">{name}</a></li>
								{/each}
							</ul>
						</section>
					{/if}
					<Webcams cams={snap.location.webcams ?? []} />
				</aside>
			</div>
			<section class="card">
				<h2>Day by day</h2>
				<PeriodTable periods={band.periods} {units} />
			</section>
		</div>
	{:else if tab === 'models'}
		<div class="stackcol">
			<section class="card">
				<ModelAgreement daily={snap.daily} models={snap.models} {units} />
			</section>
			<h2 class="section">Chance of at least each amount</h2>
			<div class="two">
				<section class="card">
					<Exceedance
						title="Next 5 days"
						members={membersFor('next5')}
						{units}
						estimated={band.band !== 'mid'}
					/>
				</section>
				<section class="card">
					<Exceedance
						title="Days 6–10"
						members={membersFor('d6_10')}
						{units}
						estimated={band.band !== 'mid'}
					/>
				</section>
			</div>
			<section class="card">
				<TrendChart runs={trend?.runs ?? []} {units} />
				<TrendDays runs={trend?.runs ?? []} {units} />
			</section>
			<section class="card">
				<h2>Base, mid and summit</h2>
				<BandTable bands={snap.bands} {units} />
			</section>
		</div>
	{:else if tab === 'backcountry'}
		<BackcountryTab {snap} {avy} {units} />
	{:else}
		<div class="stackcol">
			<StationPanel
				station={snap.snotel ?? null}
				bandLabel={snap.bands[1].label}
				bandElev={snap.bands[1].elev_m}
				{units}
			/>
			<Scorecard data={scores} {units} />
		</div>
	{/if}

	{#if selected}
		<PeriodSheet
			period={selected}
			bandLabel={band.label}
			{units}
			day={selectedDay}
			onclose={() => (selected = null)}
		/>
	{/if}
{/if}

<style>
	.loc-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 12px;
		flex-wrap: wrap;
		position: sticky;
		top: 0;
		z-index: 5;
		background: var(--bg);
		padding: 6px 0 10px;
	}
	.title {
		min-width: 0;
	}
	h1 {
		margin: 2px 0 0;
		font-size: 1.5rem;
		line-height: 1.15;
	}
	.back {
		font-size: 0.8rem;
		text-decoration: none;
	}
	.sub {
		font-size: 0.82rem;
	}
	.alert {
		background: var(--surface);
		border: 1px solid var(--temp);
		border-left-width: 4px;
		border-radius: 8px;
		padding: 8px 12px;
		margin: 0 0 10px;
		font-size: 0.88rem;
	}
	.tabs {
		display: flex;
		gap: 4px;
		border-bottom: 1px solid var(--border);
		margin: 0 0 12px;
		overflow-x: auto;
	}
	.tabs button {
		border: 0;
		background: none;
		padding: 8px 12px;
		cursor: pointer;
		color: var(--text-2);
		border-bottom: 2px solid transparent;
		white-space: nowrap;
	}
	.tabs button[aria-current='page'] {
		color: var(--text);
		border-bottom-color: var(--snow);
		font-weight: 600;
	}
	.stackcol {
		display: grid;
		gap: 12px;
	}
	.split {
		display: grid;
		gap: 12px;
		min-width: 0;
	}
	.side {
		display: grid;
		gap: 12px;
		align-content: start;
	}
	@media (min-width: 1100px) {
		.split {
			grid-template-columns: minmax(0, 1fr) 300px;
		}
	}
	.two {
		display: grid;
		gap: 12px;
	}
	@media (min-width: 768px) {
		.two {
			grid-template-columns: 1fr 1fr;
		}
	}
	.small {
		font-size: 0.85rem;
	}
	.heads h2 {
		margin: 0 0 4px;
		font-size: 0.95rem;
	}
	.heads ul {
		margin: 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 6px;
		font-size: 0.88rem;
	}
	.heads li {
		display: grid;
		gap: 1px;
		padding-left: 10px;
		border-left: 3px solid var(--border);
	}
	.heads li.notice {
		border-left-color: var(--snow);
	}
	.heads li.warning {
		border-left-color: var(--temp);
	}
	.heads .new {
		margin-left: 6px;
		font-size: 0.65rem;
		font-weight: 700;
		text-transform: uppercase;
		color: var(--snow);
	}
	.thin {
		padding-top: 8px;
		padding-bottom: 8px;
	}
	.best {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 8px;
		font-size: 0.88rem;
	}
	.best .lead {
		font-weight: 600;
		color: var(--text-2);
	}
	.section {
		font-size: 0.95rem;
		margin: 4px 0 -4px;
	}
	.links {
		margin: 0;
		padding-left: 18px;
		font-size: 0.88rem;
	}
	.links a {
		color: var(--text);
	}
</style>
