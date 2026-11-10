<script lang="ts">
	import { safeHref } from '../../../lib/links';
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
	import {
		converters,
		elevation,
		snow,
		snowNum,
		speed,
		temperature,
		type UnitSystem
	} from '../../../lib/units';
	import { ENSEMBLE_NAMES } from '../../../lib/models';
	import { dateOf, weekday } from '../../../lib/time';
	import ForecastChart from '../../../lib/charts/ForecastChart.svelte';
	import { availableRanges, type Range } from '../../../lib/charts/forecast';
	import { pageBar } from '../../../lib/pagebar.svelte';
	import PeriodGrid from '../../../lib/components/PeriodGrid.svelte';
	import ModelAgreement from '../../../lib/charts/ModelAgreement.svelte';
	import Exceedance from '../../../lib/charts/Exceedance.svelte';
	import TrendChart from '../../../lib/charts/TrendChart.svelte';
	import PeriodSheet from '../../../lib/charts/PeriodSheet.svelte';
	import BandTable from '../../../lib/components/BandTable.svelte';
	import BackcountryTab from '../../../lib/backcountry/BackcountryTab.svelte';
	import StationPanel from '../../../lib/observed/StationPanel.svelte';
	import Scorecard from '../../../lib/observed/Scorecard.svelte';
	import TrendDays from '../../../lib/components/TrendDays.svelte';
	import Webcams from '../../../lib/components/Webcams.svelte';
	import { flagText, flagTitle, isNew } from '../../../lib/flags';
	import DangerPyramid from '../../../lib/backcountry/DangerPyramid.svelte';
	import { compass, skyWord } from '../../../lib/conditions';
	import { nextStorm, periodName, startsIn, STORM_CM } from '../../../lib/storm';
	import ShareButton from '../../../lib/share/ShareButton.svelte';
	import { paint, slug } from '../../../lib/share/canvas';
	import { drawDaysCard } from '../../../lib/share/daysCard';
	import { viewport } from '../../../lib/viewport.svelte';
	import DayList from '../../../lib/components/DayList.svelte';
	import DaySheet from '../../../lib/charts/DaySheet.svelte';
	import ErrorNote from '../../../lib/components/ErrorNote.svelte';
	import { friendlyError } from '../../../lib/errors';
	import type { LoadState } from '../../../lib/load';

	type Tab = 'forecast' | 'models' | 'backcountry' | 'observed';

	const id = $derived(page.params.id ?? '');
	let snap = $state<Snapshot | null>(null);
	let trend = $state<TrendOut | null>(null);
	let error = $state<string | null>(null);
	let notFound = $state(false);
	let retry = $state(0);
	let tab = $state<Tab>('forecast');
	let selected = $state<PeriodOut | null>(null);
	let range = $state<Range>(5);
	let tabsEl = $state<HTMLElement>();
	const phone = $derived(viewport.phone);
	// Phones: a day's hours open as a chart in a popup over the day list.
	let hourlyDay = $state<{ date: string; start: string } | null>(null);

	// Desktop: once the section tabs scroll away, the page's controls dock into the header.
	$effect(() => {
		pageBar.snippet = dock;
		return () => {
			pageBar.snippet = null;
			pageBar.show = false;
		};
	});
	$effect(() => {
		if (!tabsEl) return;
		const io = new IntersectionObserver(
			([e]) => (pageBar.show = !e.isIntersecting && e.boundingClientRect.top < 80),
			{ rootMargin: '-72px 0px 0px 0px' }
		);
		io.observe(tabsEl);
		return () => io.disconnect();
	});
	let avy = $state<AvalancheView | null>(null);
	let scores = $state<VerificationOut | null>(null);

	let avyLoad = $state<LoadState>('loading');
	let scoresLoad = $state<LoadState>('loading');

	$effect(() => {
		const current = id;
		void retry; // the Retry button runs this again
		// Answers for a location we've already left must not land on this one.
		let live = true;
		snap = null;
		error = null;
		notFound = false;
		trend = null;
		selected = null;
		hourlyDay = null;
		shareDaysPick = null;
		scores = null;
		avy = null;
		avyLoad = 'loading';
		scoresLoad = 'loading';
		crosshair.reset();
		getSnapshot(current)
			.then((s) => {
				if (!live) return;
				snap = s;
				// Deep link from the Calendar: open that period's details.
				const key = page.url.searchParams.get('period');
				if (key) {
					const b = s.bands.find((x) => x.band === prefs.band) ?? s.bands[1];
					selected = b.periods.find((x) => x.key === key) ?? null;
				}
			})
			.catch((e: Error) => {
				if (!live) return;
				notFound = e instanceof ApiError && e.status === 404;
				error = notFound ? null : friendlyError(e);
			});
		getTrend(current)
			.then((t) => live && (trend = t))
			.catch(() => live && (trend = null));
		getVerification(current)
			.then((v) => {
				if (!live) return;
				scores = v;
				scoresLoad = 'ready';
			})
			.catch(() => live && (scoresLoad = 'error'));
		getAvalanche()
			.then((all) => {
				if (!live) return;
				avy = all[current] ?? null;
				avyLoad = 'ready';
			})
			.catch(() => live && (avyLoad = 'error'));
		return () => (live = false);
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
	const c = $derived(converters(units));
	const storm = $derived(band ? nextStorm(band.periods) : null);
	// Open the period details for a time picked on the chart.
	const pickTime = (t: string) => {
		if (!band) return;
		const at = Date.parse(t);
		selected =
			band.periods.find(
				(p) => Date.parse(p.start) <= at && at < Date.parse(p.start) + p.hours * 3600e3
			) ?? null;
	};
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
	// Day by day as an image: as many days as the chart shows (at least 3), up to the data.
	const SHARE_DAYS = [3, 5, 7, 10] as const;
	const daysAvailable = $derived(new Set((band?.periods ?? []).map((p) => p.date)).size);
	const shareDayChoices = $derived(SHARE_DAYS.filter((n) => n <= Math.max(3, daysAvailable)));
	let shareDaysPick = $state<number | null>(null);
	const shareDays = $derived(
		shareDaysPick ??
			shareDayChoices.find((n) => n >= range) ??
			shareDayChoices[shareDayChoices.length - 1] ??
			5
	);
	// Elevation buttons on a phone: just the number, so long band names never crowd them.
	const elevNum = (m: number) => elevation(m, units).replace(/\s*(ft|m)$/, '');
	const place = $derived(
		snap
			? { name: snap.location.name, region: snap.location.region, generatedAt: snap.generated_at }
			: null
	);
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

{#snippet dock()}
	{#if snap && band}
		<div class="dock">
			<span class="dock-name">{snap.location.name}</span>
			<div class="seg mini" role="group" aria-label="Elevation">
				{#each snap.bands as b (b.band)}
					<button
						aria-pressed={band.band === b.band}
						onclick={() => prefs.setBand(b.band as BandName)}>{b.label}</button
					>
				{/each}
			</div>
			<div class="seg mini" role="group" aria-label="Sections">
				{#each tabs as t (t)}
					<button aria-pressed={tab === t} onclick={() => (tab = t)}>{names[t]}</button>
				{/each}
			</div>
			{#if tab === 'forecast'}
				<div class="seg mini" role="group" aria-label="Time range">
					{#each availableRanges(band.hourly.t.length) as r (r)}
						<button aria-pressed={range === r} onclick={() => (range = r)}>{r}d</button>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
{/snippet}

{#snippet shareDaysBtn()}
	{#if place && band}
		<ShareButton
			label="Share day by day"
			filename={slug(`${place.name} day by day ${shareDays} days`)}
			render={(shape) =>
				paint(shape, (ctx, p) =>
					drawDaysCard(ctx, shape, { ...place, band, units, days: shareDays }, p)
				)}
		>
			{#snippet options()}
				<div class="seg" role="group" aria-label="Days to share">
					{#each shareDayChoices as n (n)}
						<button aria-pressed={shareDays === n} onclick={() => (shareDaysPick = n)}
							>{n} days</button
						>
					{/each}
				</div>
			{/snippet}
		</ShareButton>
	{/if}
{/snippet}

{#if notFound}
	<div class="card">
		<h1 class="nf">No forecast here</h1>
		<p class="muted">
			This location doesn’t exist, or its first forecast hasn’t finished yet (that takes a few
			minutes after it’s added).
		</p>
		<a class="btn" href={resolve('/')}>All locations</a>
	</div>
{:else if error}
	<ErrorNote message={error} onretry={() => retry++}>
		<a href={resolve('/')}>All locations</a>
	</ErrorNote>
{:else if !snap || !band}
	<p class="muted" aria-live="polite">Loading…</p>
{:else}
	{#if phone}
		<div class="mhead">
			<a class="mback" href={resolve('/')} aria-label="All locations">
				<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"
					><path d="M15 5l-7 7 7 7" /></svg
				>
			</a>
			<h1>{snap.location.name}</h1>
		</div>
		<div class="mband">
			<span class="mbname faint"><strong>{band.label}</strong> · {updated}</span>
			<div class="seg elevs" role="group" aria-label="Elevation, {c.heightUnit}">
				{#each snap.bands as b (b.band)}
					<button
						aria-pressed={band.band === b.band}
						aria-label="{b.label}, {elevation(b.elev_m, units)}"
						onclick={() => prefs.setBand(b.band as BandName)}>{elevNum(b.elev_m)}</button
					>
				{/each}
				<span class="unit" aria-hidden="true">{c.heightUnit}</span>
			</div>
		</div>
	{:else}
		<div class="loc-head">
			<div class="title">
				<a class="back faint" href={resolve('/')}>← All locations</a>
				<h1>{snap.location.name}</h1>
				<div class="muted sub">
					{snap.location.region} ·
					<span class="nw"
						>{band.label}
						{elevation(band.elev_m, units)}</span
					>
					· <span class="nw">updated {updated}</span>
				</div>
			</div>
			<div class="seg elev" role="group" aria-label="Elevation">
				{#each snap.bands as b (b.band)}
					<button
						aria-pressed={band.band === b.band}
						onclick={() => prefs.setBand(b.band as BandName)}>{b.label}</button
					>
				{/each}
			</div>
		</div>

		<div class="now" aria-label="Right now">
			<span class="now-lbl">Now</span>
			<span
				><strong class="num">{temperature(band.hourly.temp_c[0], units)}</strong>
				{skyWord(band.hourly.wcode[0])}</span
			>
			<span><span class="faint">Freezing level</span> {elevation(band.hourly.fl_m[0], units)}</span>
			<span
				><span class="faint">Wind</span>
				{compass(band.hourly.wdir[0])}
				{speed(band.hourly.wind_kmh[0], units)}, gusts {speed(band.hourly.gust_kmh[0], units)}</span
			>
		</div>
	{/if}

	{#each snap.alerts as a, i (i)}
		<div class="alert"><strong>{a.event}</strong> {a.headline ?? ''}</div>
	{/each}

	<nav class="tabs" aria-label="Sections" bind:this={tabsEl}>
		{#each tabs as t (t)}
			<button aria-current={tab === t ? 'page' : undefined} onclick={() => (tab = t)}
				>{names[t]}</button
			>
		{/each}
	</nav>

	{#if tab === 'forecast'}
		<div class="stackcol">
			{#if backcountry && !phone}
				<section class="card thin">
					<DangerPyramid
						view={avy}
						tz={snap.location.tz}
						today={dateOf(snap.now)}
						load={avyLoad}
						compact
					/>
				</section>
			{/if}
			{#if phone}
				<section class="card chartcard">
					<ForecastChart {band} bands={snap.bands} {units} bind:range place={place ?? undefined} />
				</section>
				{#if backcountry}
					<section class="card thin">
						<DangerPyramid
							view={avy}
							tz={snap.location.tz}
							today={dateOf(snap.now)}
							load={avyLoad}
							compact
						/>
					</section>
				{/if}
				<section class="card mout">
					<div>
						<span class="eyebrow">Next 5 days</span>
						<span class="mnum num"
							>{snowNum(band.windows['next5'].snow_cm, units)}<small>{c.snowUnit}</small></span
						>
						{#if band.windows['next5'].ens}
							{@const e = band.windows['next5'].ens}
							<span class="faint msub"
								>{snowNum(e.p10, units)}–{snowNum(e.p90, units)} likely{e.estimated
									? ' (est.)'
									: ''}</span
							>
						{/if}
					</div>
					<div class="mstorm">
						<span class="eyebrow">Next storm</span>
						{#if storm}
							<span class="mnum num"
								>{snowNum(storm.total_cm, units)}<small>{c.snowUnit}</small></span
							>
							<span class="msub">{startsIn(dateOf(snap.now), storm.first)}</span>
						{:else}
							<span class="mnum">Quiet</span>
							<span class="faint msub">none in sight</span>
						{/if}
					</div>
					<div>
						<span class="eyebrow">Now</span>
						<span class="mnum num">{temperature(band.hourly.temp_c[0], units)}</span>
						<span class="faint msub"
							>{compass(band.hourly.wdir[0])}
							{speed(band.hourly.wind_kmh[0], units)}</span
						>
					</div>
				</section>
				<section class="card">
					<div class="cardhead">
						<h2>Day by day</h2>
						{@render shareDaysBtn()}
					</div>
					<DayList
						periods={band.periods}
						hourly={band.hourly}
						{units}
						onperiod={(p) => (selected = p)}
						onhourly={(date, start) => (hourlyDay = { date, start })}
					/>
				</section>
			{:else}
				<section class="card outlook">
					<div class="half">
						<span class="eyebrow">Next 5 days</span>
						<span class="big num"
							>{snowNum(band.windows['next5'].snow_cm, units)}<small>{c.snowUnit}</small></span
						>
						{#if band.windows['next5'].ens}
							{@const e = band.windows['next5'].ens}
							<span class="faint small"
								>{snowNum(e.p10, units)}–{snowNum(e.p90, units)}
								{c.snowUnit} likely{e.estimated ? ' (est.)' : ''}</span
							>
						{/if}
						<span class="faint small"
							><span class="nw">Days 6–10: {snow(band.windows['d6_10'].snow_cm, units)}</span> ·
							<span class="nw">Last 24 h: {snow(band.stats.last24_cm, units)}</span></span
						>
					</div>
					<div class="half storm">
						<span class="eyebrow">Next storm</span>
						{#if storm}
							<span class="big num"
								>{snowNum(storm.total_cm, units)}<small>{c.snowUnit}</small></span
							>
							<span class="small">
								<strong
									><span class="nw">{periodName(storm.first)}</span
									>{#if storm.periods > 1}&#32;→&#32;<span class="nw">{periodName(storm.last)}</span
										>{/if}</strong
								>
								· <span class="nw">{startsIn(dateOf(snap.now), storm.first)}</span>
							</span>
							<span class="small muted">
								<span class="nw"
									>Heaviest {periodName(storm.peak)}: {snow(storm.peak.snow_cm, units)}</span
								>{#if storm.snow_level_min_m !== null}&nbsp;·&#32;<span class="nw"
										>snow level {elevation(storm.snow_level_min_m, units)}</span
									>{/if}
							</span>
						{:else}
							<span class="big">Quiet</span>
							<span class="small">No storm of {snow(STORM_CM, units)}+ in sight</span>
						{/if}
					</div>
				</section>
				<section class="card">
					<ForecastChart
						{band}
						bands={snap.bands}
						{units}
						onpick={pickTime}
						bind:range
						place={place ?? undefined}
					/>
				</section>
				<section class="card">
					<div class="cardhead">
						<h2>Day by day</h2>
						{@render shareDaysBtn()}
					</div>
					<PeriodGrid
						periods={band.periods}
						hourly={band.hourly}
						{units}
						onselect={(p) => (selected = p)}
					/>
				</section>
			{/if}
			{#if headsUp.length}
				<section class="card heads">
					<h2>Heads up</h2>
					<ul>
						{#each headsUp as f, i (i)}
							<li class={f.severity}>
								<span
									><strong>{flagTitle(f)}</strong>{#if isNew(f, snap.run_id)}<span class="new"
											>New</span
										>{/if}</span
								>
								<span class="muted">{flagText(f, units)}</span>
							</li>
						{/each}
					</ul>
				</section>
			{/if}
			<div class="extras">
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
								<li>
									<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
									<a href={safeHref(url)} rel="noopener noreferrer" target="_blank">{name}</a>
								</li>
							{/each}
						</ul>
					</section>
				{/if}
				<Webcams cams={snap.location.webcams ?? []} />
			</div>
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
		<BackcountryTab {snap} {avy} {units} {avyLoad} />
	{:else}
		<div class="stackcol">
			<StationPanel
				station={snap.snotel ?? null}
				bandLabel={snap.bands[1].label}
				bandElev={snap.bands[1].elev_m}
				{units}
			/>
			<Scorecard data={scores} {units} load={scoresLoad} />
		</div>
	{/if}

	{#if hourlyDay}
		<DaySheet
			{band}
			bands={snap.bands}
			{units}
			date={hourlyDay.date}
			start={hourlyDay.start}
			onclose={() => (hourlyDay = null)}
		/>
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
	.nf {
		font-size: 1.2rem;
		margin: 0 0 6px;
	}
	.loc-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 12px;
		flex-wrap: wrap;
		padding: 4px 0 14px;
	}
	.title {
		min-width: 0;
	}
	h1 {
		margin: 4px 0 2px;
		font-family: var(--font-num);
		font-size: 2rem;
		font-weight: 600;
		letter-spacing: -0.02em;
		line-height: 1.1;
	}
	.back {
		font-size: 0.82rem;
		text-decoration: none;
	}
	.sub {
		font-size: 0.85rem;
	}
	.nw {
		white-space: nowrap;
	}
	.alert {
		background: var(--warn-bg);
		border: 1px solid var(--warn-border);
		border-radius: 14px;
		padding: 10px 14px;
		margin: 0 0 12px;
		font-size: 0.88rem;
	}
	.tabs {
		display: inline-flex;
		gap: 2px;
		padding: 3px;
		margin: 0 0 16px;
		border-radius: 999px;
		background: var(--surface-2);
		border: 1px solid var(--border);
		max-width: 100%;
		overflow-x: auto;
	}
	.tabs button {
		border: 0;
		background: none;
		padding: 8px 16px;
		cursor: pointer;
		color: var(--text-2);
		border-radius: 999px;
		white-space: nowrap;
		font-size: 0.88rem;
	}
	/* Phones: the section tabs and elevation picker span the width so every option shows. */
	@media (max-width: 640px) {
		.tabs,
		.seg.elev {
			display: flex;
			width: 100%;
		}
		.tabs button,
		.seg.elev button {
			flex: 1 1 auto;
			min-width: 0;
			padding-left: 8px;
			padding-right: 8px;
			overflow: hidden;
			text-overflow: ellipsis;
		}
		.tabs button {
			padding-top: 7px;
			padding-bottom: 7px;
			font-size: 0.85rem;
		}
		.seg.elev button {
			padding-top: 5px;
			padding-bottom: 5px;
		}
		.loc-head {
			padding-bottom: 12px;
		}
	}
	.tabs button[aria-current='page'] {
		color: var(--text);
		background: var(--surface);
		box-shadow: 0 2px 8px rgb(31 27 46 / 0.08);
		font-weight: 600;
	}
	.dock {
		display: flex;
		align-items: center;
		gap: 8px;
		white-space: nowrap;
	}
	.dock-name {
		font-family: var(--font-num);
		font-weight: 600;
		font-size: 0.9rem;
		padding: 0 6px 0 8px;
		max-width: 180px;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.seg.mini {
		background: transparent;
		border-color: var(--border);
	}
	.seg.mini button {
		padding: 4px 9px;
		font-size: 0.78rem;
	}
	@media (max-width: 1279px) {
		.dock-name {
			display: none;
		}
	}
	.now {
		display: flex;
		gap: 8px 18px;
		align-items: center;
		flex-wrap: nowrap;
		overflow-x: auto;
		white-space: nowrap;
		margin: -4px 0 14px;
		padding: 8px 14px;
		border-radius: 999px;
		background: var(--surface);
		border: 1px solid var(--border);
		font-size: 0.85rem;
		scrollbar-width: none;
	}
	/* Phones: let the "Now" items wrap rather than hide off the right edge. */
	@media (max-width: 640px) {
		.now {
			flex-wrap: wrap;
			gap: 4px 14px;
			border-radius: 14px;
			padding: 8px 12px;
		}
	}
	.now strong {
		font-size: 1rem;
		font-weight: 600;
	}
	.now-lbl {
		font-size: 0.7rem;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--accent);
	}
	.outlook {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		padding: 0;
		overflow: hidden;
	}
	.half {
		display: grid;
		align-content: start;
		gap: 4px;
		padding: 14px 16px;
		min-width: 0;
	}
	.half.storm {
		background: var(--accent-soft);
	}
	.eyebrow {
		font-size: 0.7rem;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--text-3);
	}
	.storm .eyebrow {
		color: var(--accent);
	}
	.big {
		font-family: var(--font-num);
		font-size: 1.9rem;
		font-weight: 600;
		line-height: 1.05;
		letter-spacing: -0.02em;
	}
	.big small {
		font-family: var(--font-ui);
		font-size: 0.8rem;
		font-weight: 500;
		letter-spacing: 0;
		margin-left: 3px;
		color: var(--text-2);
	}
	.stackcol {
		display: grid;
		gap: 12px;
	}
	/* --- Phones --- */
	.mhead {
		display: flex;
		align-items: center;
		gap: 2px;
		margin: -6px 0 0 -12px;
	}
	.mhead h1 {
		margin: 0;
		min-width: 0;
		font-size: 1.45rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.mback {
		flex: 0 0 44px;
		height: 44px;
		display: grid;
		place-items: center;
		color: var(--text-2);
	}
	.mback svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.mband {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		margin: 0 0 6px;
	}
	.mbname {
		min-width: 0;
		font-size: 0.78rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.mbname strong {
		font-weight: 600;
		color: var(--text-2);
	}
	.seg.elevs {
		flex: 0 0 auto;
		align-items: center;
		border-radius: 12px;
	}
	.seg.elevs button {
		min-width: 50px;
		padding: 8px 8px;
		border-radius: 10px;
		font-family: var(--font-num);
		font-variant-numeric: tabular-nums;
	}
	.seg.elevs .unit {
		padding: 0 8px 0 4px;
		font-size: 0.72rem;
		color: var(--text-3);
	}
	.mout {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		padding: 0;
	}
	.mout > div {
		display: grid;
		align-content: start;
		gap: 2px;
		padding: 10px 12px;
		min-width: 0;
	}
	.mout > div + div {
		border-left: 1px solid var(--border);
	}
	.mout .eyebrow {
		font-size: 0.66rem;
	}
	.mstorm .eyebrow {
		color: var(--accent);
	}
	.mnum {
		font-family: var(--font-num);
		font-size: 1.35rem;
		font-weight: 600;
		line-height: 1.1;
		letter-spacing: -0.02em;
	}
	.mnum small {
		font-family: var(--font-ui);
		font-size: 0.75rem;
		font-weight: 400;
		letter-spacing: 0;
		margin-left: 3px;
		color: var(--text-2);
	}
	.msub {
		font-size: 0.72rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	@media (max-width: 640px) {
		.chartcard {
			padding: 12px 10px;
		}
		.tabs {
			border: 0;
			border-radius: 0;
			background: none;
			padding: 0;
			margin: 0 -16px 12px;
			width: auto;
			max-width: none;
			border-bottom: 1px solid var(--border);
		}
		.tabs button {
			border-radius: 0;
			padding-top: 11px;
			padding-bottom: 11px;
		}
		.tabs button[aria-current='page'] {
			background: none;
			box-shadow: inset 0 -2px 0 var(--accent);
		}
	}
	.extras {
		display: grid;
		gap: 12px;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
		align-items: start;
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
	.cardhead {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		margin-bottom: 10px;
	}
	.cardhead h2 {
		margin: 0;
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
		border-left-color: var(--warn);
	}
	.heads .new {
		margin-left: 6px;
		font-size: 0.65rem;
		font-weight: 700;
		text-transform: uppercase;
		color: var(--accent);
	}
	.thin {
		padding-top: 8px;
		padding-bottom: 8px;
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
