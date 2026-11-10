<!-- One location. Desktop: the name on the sky with the elevation control beside it, the
     outlook card, then the section (Forecast, Models, Backcountry, Observed; the rail
     switches them). Phones: the name, a "now" pill and the elevation numbers, tabs, and the
     chart first. The sky behind shows this location's weather now. -->
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
	import type { Range } from '../../../lib/charts/forecast';
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
	import { compass, DANGER_WORDS } from '../../../lib/conditions';
	import { nextStorm, periodName, startsIn, STORM_CM } from '../../../lib/storm';
	import ShareButton from '../../../lib/share/ShareButton.svelte';
	import { paint, slug } from '../../../lib/share/canvas';
	import { drawDaysCard } from '../../../lib/share/daysCard';
	import { viewport } from '../../../lib/viewport.svelte';
	import { sections, SECTION_NAMES, type Section } from '../../../lib/sections.svelte';
	import { skyState } from '../../../lib/skystate.svelte';
	import { skyOf, hourIndex } from '../../../lib/sky';
	import DayList from '../../../lib/components/DayList.svelte';
	import DaySheet from '../../../lib/charts/DaySheet.svelte';
	import ErrorNote from '../../../lib/components/ErrorNote.svelte';
	import { friendlyError } from '../../../lib/errors';
	import type { LoadState } from '../../../lib/load';

	const id = $derived(page.params.id ?? '');
	let snap = $state<Snapshot | null>(null);
	let trend = $state<TrendOut | null>(null);
	let error = $state<string | null>(null);
	let notFound = $state(false);
	let retry = $state(0);
	let selected = $state<PeriodOut | null>(null);
	let range = $state<Range>(5);
	const phone = $derived(viewport.phone);
	// Phones: a day's hours open as a chart in a popup over the day list.
	let hourlyDay = $state<{ date: string; start: string } | null>(null);
	// Desktop: the day under the pointer in the table (shaded on the chart) and on the
	// chart (lit in the table).
	let tableDate = $state<string | null>(null);
	let chartDate = $state<string | null>(null);
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
		tableDate = null;
		chartDate = null;
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

	const tabs = $derived<Section[]>(
		snap?.location.kind === 'backcountry'
			? ['forecast', 'backcountry', 'models', 'observed']
			: ['forecast', 'models', 'backcountry', 'observed']
	);
	// The rail shows this location's sections; the sky shows its weather now.
	$effect(() => {
		sections.id = snap ? id : null;
		sections.list = snap ? tabs : [];
		skyState.page = snap ? skyOf(snap) : null;
	});
	$effect(() => () => {
		sections.id = null;
		sections.list = [];
		skyState.page = null;
	});
	const tab = $derived(sections.tab);
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
	// The hour holding "now", for the current conditions.
	const nowAt = $derived(band && snap ? hourIndex(band.hourly, snap.now) : 0);
	const sky = $derived(skyState.current);
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
	const avyRated = $derived(avy?.status === 'current' && !!avy.today_max);
	const avyCenter = $derived(avy?.doc?.center ?? null);
	const next5 = $derived(band?.windows['next5'] ?? null);

	// Phones: the conditions and elevation row sticks to the top; once it has, it gets a
	// frosted band so the page doesn't show through around it.
	let stuck = $state(false);
	function watchStuck(node: HTMLElement) {
		if (typeof IntersectionObserver === 'undefined') return;
		const io = new IntersectionObserver(([e]) => (stuck = !e.isIntersecting));
		io.observe(node);
		return { destroy: () => io.disconnect() };
	}
</script>

<svelte:head
	><title>{snap ? `${snap.location.name} · Snow Watch` : 'Snow Watch'}</title></svelte:head
>

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

{#snippet headsUpCard()}
	{#if snap && headsUp.length}
		<section class="card heads">
			<h2>Heads up</h2>
			<ul>
				{#each headsUp as f, i (i)}
					<li class={f.severity}>
						<span
							><strong>{flagTitle(f)}</strong>{#if isNew(f, snap.run_id)}<span class="new">New</span
								>{/if}</span
						>
						<span class="muted">{flagText(f, units)}</span>
					</li>
				{/each}
			</ul>
		</section>
	{/if}
{/snippet}

{#snippet aboutCard()}
	{#if snap && band}
		<section class="card about">
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
			{#if Object.keys(snap.location.links).length}
				<h3>Links</h3>
				<ul class="links">
					{#each Object.entries(snap.location.links) as [name, url] (name)}
						<!-- External site: resolve() is only for routes in this app. -->
						<li>
							<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
							<a href={safeHref(url)} rel="noopener noreferrer" target="_blank">{name}</a>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
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
	<p class="loading glass" aria-live="polite">Loading…</p>
{:else}
	{#if phone}
		<header class="mhead">
			<a class="mback glass" href={resolve('/')} aria-label="All locations">
				<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"
					><path d="M15 5l-7 7 7 7" /></svg
				>
			</a>
			<h1>{snap.location.name}</h1>
		</header>
		<div class="stuckmark" use:watchStuck aria-hidden="true"></div>
		<div class="mrow" class:stuck>
			<span class="pill glass" title="{band.label} · updated {updated}">
				<span class="skydot" data-scene={sky.scene} aria-hidden="true"></span>
				{sky.label} · <span class="num">{temperature(band.hourly.temp_c[nowAt], units)}</span>
			</span>
			<div class="seg glass elevs" role="group" aria-label="Elevation, {c.heightUnit}">
				{#each snap.bands as b (b.band)}
					<button
						aria-pressed={band.band === b.band}
						aria-label="{b.label}, {elevation(b.elev_m, units)}"
						onclick={() => prefs.setBand(b.band as BandName)}
						><span class="bn">{b.label}</span><span class="be num">{elevNum(b.elev_m)}</span
						></button
					>
				{/each}
			</div>
		</div>
	{:else}
		<header class="lhead">
			<div class="title">
				<h1>{snap.location.name}</h1>
				<span class="pill glass">
					<span class="skydot" data-scene={sky.scene} aria-hidden="true"></span>
					{snap.location.region} · {sky.label} now · updated {updated}
				</span>
			</div>
			<div class="seg glass elev" role="group" aria-label="Elevation">
				{#each snap.bands as b (b.band)}
					<button
						aria-pressed={band.band === b.band}
						onclick={() => prefs.setBand(b.band as BandName)}
						><span class="bn">{b.label}</span><span class="be num"
							>{elevation(b.elev_m, units)}</span
						></button
					>
				{/each}
			</div>
		</header>

		<section class="card outlook" aria-label="Outlook">
			<div>
				<span class="eyebrow">Next 5 days</span>
				<span class="big num">{snowNum(next5?.snow_cm, units)}<small>{c.snowUnit}</small></span>
				{#if next5?.ens}
					<span class="small muted"
						>{snowNum(next5.ens.p10, units)}–{snowNum(next5.ens.p90, units)}
						{c.snowUnit} likely{next5.ens.estimated ? ' (est.)' : ''}</span
					>
				{/if}
				<span class="small muted"
					><span class="nw">Days 6–10: {snow(band.windows['d6_10'].snow_cm, units)}</span> ·
					<span class="nw">last 24 h: {snow(band.stats.last24_cm, units)}</span></span
				>
			</div>
			<div class="stormcell">
				<span class="eyebrow">Next storm</span>
				{#if storm}
					<span class="big num">{snowNum(storm.total_cm, units)}<small>{c.snowUnit}</small></span>
					<span class="small"
						><strong
							><span class="nw">{periodName(storm.first)}</span
							>{#if storm.periods > 1}&#32;→&#32;<span class="nw">{periodName(storm.last)}</span
								>{/if}</strong
						>
						· <span class="nw">{startsIn(dateOf(snap.now), storm.first)}</span></span
					>
					<span class="small muted"
						><span class="nw"
							>Heaviest {periodName(storm.peak)}: {snow(storm.peak.snow_cm, units)}</span
						>{#if storm.snow_level_min_m !== null}&nbsp;·&#32;<span class="nw"
								>snow level {elevation(storm.snow_level_min_m, units)}</span
							>{/if}</span
					>
				{:else}
					<span class="big">Quiet</span>
					<span class="small muted">No storm of {snow(STORM_CM, units)}+ in sight</span>
				{/if}
			</div>
			<div>
				<span class="eyebrow">Now</span>
				<span class="big num">{temperature(band.hourly.temp_c[nowAt], units)}</span>
				<span class="small muted"
					>{compass(band.hourly.wdir[nowAt])}
					{speed(band.hourly.wind_kmh[nowAt], units)}, gusts {speed(
						band.hourly.gust_kmh[nowAt],
						units
					)}</span
				>
				<span class="small muted">Freezing level {elevation(band.hourly.fl_m[nowAt], units)}</span>
			</div>
			<div>
				<span class="eyebrow">Avalanche</span>
				{#if avyLoad === 'loading'}
					<span class="big faint">…</span>
				{:else if avyRated && avy?.today_max}
					<span class="avyval"
						><span class="danger d{avy.today_max}"
							>{avy.today_max} · {DANGER_WORDS[avy.today_max] ?? ''}</span
						></span
					>
					<span class="small muted">{avyCenter ?? 'Avalanche center'} · today’s highest</span>
				{:else}
					<span class="big">No rating</span>
					<span class="small muted"
						>{avyCenter
							? `${avyCenter}${avy?.doc?.off_season ? ' · off season' : ''}`
							: 'None published right now'}</span
					>
				{/if}
			</div>
		</section>
	{/if}

	{#each snap.alerts as a, i (i)}
		<div class="alert"><strong>{a.event}</strong> {a.headline ?? ''}</div>
	{/each}

	{#if !viewport.desktop}
		<div class="tabs" class:under={phone} role="tablist" aria-label="Sections">
			{#each tabs as t (t)}
				<button role="tab" aria-selected={tab === t} onclick={() => (sections.tab = t)}
					>{SECTION_NAMES[t]}</button
				>
			{/each}
		</div>
	{/if}

	{#if tab === 'forecast'}
		<div class="stackcol">
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
				<section class="card mout" aria-label="Outlook">
					<div>
						<span class="eyebrow">Next 5 days</span>
						<span class="mnum num">{snowNum(next5?.snow_cm, units)}<small>{c.snowUnit}</small></span
						>
						{#if next5?.ens}
							<span class="faint msub"
								>{snowNum(next5.ens.p10, units)}–{snowNum(next5.ens.p90, units)} likely{next5.ens
									.estimated
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
						<span class="mnum num">{temperature(band.hourly.temp_c[nowAt], units)}</span>
						<span class="faint msub"
							>{compass(band.hourly.wdir[nowAt])}
							{speed(band.hourly.wind_kmh[nowAt], units)}</span
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
				{@render headsUpCard()}
				{@render aboutCard()}
				<Webcams cams={snap.location.webcams ?? []} />
			{:else}
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
				<section class="card chartcard">
					<ForecastChart
						{band}
						bands={snap.bands}
						{units}
						onpick={pickTime}
						bind:range
						place={place ?? undefined}
						shadeDate={tableDate}
						onhoverdate={(d) => (chartDate = d)}
					/>
				</section>
				<section class="card">
					<div class="cardhead">
						<div>
							<h2>Day by day</h2>
							<p class="faint small hint">
								Each cell shows the day, then the night. Point at a day to find it on the chart;
								pick a snow cell for its details.
							</p>
						</div>
						{@render shareDaysBtn()}
					</div>
					<PeriodGrid
						periods={band.periods}
						hourly={band.hourly}
						days={snap.days ?? []}
						{units}
						onselect={(p) => (selected = p)}
						focusDate={chartDate}
						onhoverdate={(d) => (tableDate = d)}
					/>
				</section>
				<div class="extras">
					{@render headsUpCard()}
					{@render aboutCard()}
				</div>
				<Webcams cams={snap.location.webcams ?? []} />
			{/if}
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
	.loading {
		display: inline-block;
		margin: 8px 0;
		padding: 8px 16px;
		border-radius: 999px;
		color: var(--text-2);
	}
	h1 {
		margin: 0;
		font-family: var(--font-num);
		font-weight: 700;
		letter-spacing: -0.03em;
		line-height: 1.05;
	}
	.pill {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 6px 14px 6px 7px;
		border-radius: 999px;
		font-size: 0.88rem;
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
	}
	/* A swatch of the scene's sky (the same colours as the backdrop's top). */
	.skydot {
		flex: 0 0 20px;
		height: 20px;
		border-radius: 50%;
		background: linear-gradient(180deg, #62a8ea, #e6f1fa);
		box-shadow: inset 0 0 0 1px var(--glass-border);
	}
	.skydot[data-scene='clear'] {
		background: linear-gradient(180deg, #4f9fec, #dff0fc);
	}
	.skydot[data-scene='night'] {
		background: linear-gradient(180deg, #1d2a4f, #7f88d8);
	}
	.skydot[data-scene='glow'] {
		background: linear-gradient(180deg, #8aa4e6, #ffe3c4);
	}
	.skydot[data-scene='overcast'],
	.skydot[data-scene='fog'] {
		background: linear-gradient(180deg, #9fb0c4, #e6ebf1);
	}
	.skydot[data-scene='snow'],
	.skydot[data-scene='heavy'],
	.skydot[data-scene='mixed'] {
		background: linear-gradient(180deg, #a9bcd6, #f4f7fb);
	}
	.skydot[data-scene='rain'] {
		background: linear-gradient(180deg, #8fa6b8, #dbe4ea);
	}

	/* --- Desktop and tablet --- */
	.lhead {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 12px 24px;
		flex-wrap: wrap;
		padding: 18px 4px 14px;
	}
	.lhead h1 {
		font-size: 2.9rem;
		margin-bottom: 10px;
	}
	.title {
		min-width: 0;
	}
	.seg.elev {
		padding: 4px;
		border-radius: 20px;
	}
	.seg.elev button {
		display: grid;
		justify-items: center;
		gap: 0;
		padding: 5px 16px;
		border-radius: 16px;
		min-width: 110px;
	}
	.bn {
		font-size: 0.86rem;
	}
	.be {
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--text-2);
	}
	.outlook {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		padding: 0;
		overflow: hidden;
		margin-bottom: 16px;
	}
	.outlook > div {
		display: grid;
		align-content: start;
		gap: 3px;
		padding: 16px 20px;
		min-width: 0;
	}
	.outlook > div + div {
		border-left: 1px solid var(--grid);
	}
	.stormcell {
		background: var(--accent-soft);
	}
	.stormcell .eyebrow {
		color: var(--accent-ink);
	}
	.big {
		font-family: var(--font-num);
		font-size: 1.9rem;
		font-weight: 600;
		line-height: 1.1;
		letter-spacing: -0.03em;
	}
	.big small,
	.mnum small {
		font-family: var(--font-ui);
		font-size: 0.82rem;
		font-weight: 500;
		letter-spacing: 0;
		margin-left: 3px;
		color: var(--text-2);
	}
	.avyval {
		display: flex;
		align-items: center;
		min-height: 2.1rem;
	}
	.avyval .danger {
		font-size: 0.95rem;
		padding: 3px 12px;
	}
	@media (max-width: 1099px) {
		.outlook {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
		.outlook > div:nth-child(3) {
			border-left: 0;
		}
		.outlook > div:nth-child(n + 3) {
			border-top: 1px solid var(--grid);
		}
	}
	.nw {
		white-space: nowrap;
	}
	.small {
		font-size: 0.85rem;
	}
	.alert {
		background: var(--warn-bg);
		border: 1px solid var(--warn-border);
		color: var(--warn-ink);
		border-radius: 18px;
		padding: 10px 16px;
		margin: 0 0 12px;
		font-size: 0.9rem;
	}
	.tabs {
		display: inline-flex;
		gap: 2px;
		padding: 4px;
		margin: 0 0 16px;
		border-radius: 999px;
		background: var(--glass);
		border: 1px solid var(--glass-border);
		box-shadow: var(--glass-shadow);
		backdrop-filter: var(--blur-glass);
		-webkit-backdrop-filter: var(--blur-glass);
		max-width: 100%;
		overflow-x: auto;
	}
	.tabs button {
		border: 0;
		background: none;
		padding: 8px 18px;
		cursor: pointer;
		color: var(--text-2);
		border-radius: 999px;
		white-space: nowrap;
		font-size: 0.9rem;
		transition:
			background-color var(--ease),
			box-shadow var(--ease);
	}
	.tabs button[aria-selected='true'] {
		color: var(--text);
		background: var(--sel);
		box-shadow: var(--sel-shadow);
		font-weight: 600;
	}
	.stackcol {
		display: grid;
		gap: 16px;
	}
	.chartcard {
		padding: 18px 20px 16px;
	}
	.cardhead {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 10px;
		margin-bottom: 10px;
	}
	.cardhead h2 {
		margin: 0;
	}
	.hint {
		margin: 2px 0 0;
	}
	.extras {
		display: grid;
		gap: 16px;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
		align-items: start;
	}
	.two {
		display: grid;
		gap: 16px;
	}
	@media (min-width: 768px) {
		.two {
			grid-template-columns: 1fr 1fr;
		}
	}
	.heads h2 {
		margin: 0 0 8px;
	}
	.heads ul {
		margin: 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 10px;
		font-size: 0.9rem;
	}
	.heads li {
		display: grid;
		gap: 1px;
		padding-left: 18px;
		position: relative;
	}
	.heads li::before {
		content: '';
		position: absolute;
		left: 0;
		top: 7px;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--text-3);
	}
	.heads li.notice::before {
		background: var(--snow);
	}
	.heads li.warning::before {
		background: var(--warn);
	}
	.heads .new {
		margin-left: 6px;
		font-size: 0.66rem;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--accent-ink);
	}
	.about h3 {
		margin: 14px 0 6px;
		font-size: 0.88rem;
	}
	.links {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		font-size: 0.86rem;
	}
	.links a {
		display: inline-flex;
		align-items: center;
		min-height: 32px;
		padding: 0 12px;
		border-radius: 999px;
		background: var(--surface-2);
		color: var(--text);
		text-decoration: none;
	}
	.links a:hover {
		text-decoration: underline;
	}
	.thin {
		padding-top: 8px;
		padding-bottom: 8px;
	}
	.section {
		font-size: 1rem;
		margin: 4px 4px -6px;
	}

	/* --- Phones --- */
	.mhead {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 0 0 10px;
	}
	.mhead h1 {
		min-width: 0;
		font-size: 1.6rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.mback {
		flex: 0 0 44px;
		height: 44px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		color: var(--text);
	}
	.mback svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	/* Conditions and elevation: stays at the top of the screen while you scroll, so the
	   elevation can be changed from anywhere on the page. */
	.stuckmark {
		height: 1px;
		margin-bottom: -1px;
	}
	.mrow {
		position: sticky;
		top: env(safe-area-inset-top);
		z-index: 30;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin: -6px -16px 0;
		padding: 6px 16px;
		border-bottom: 1px solid transparent;
		transition:
			background-color var(--ease),
			border-color var(--ease);
	}
	.mrow.stuck {
		background: var(--header-glass);
		backdrop-filter: var(--blur-glass);
		-webkit-backdrop-filter: var(--blur-glass);
		border-bottom-color: var(--border);
	}
	/* Fill the strip behind the status bar too. */
	.mrow.stuck::before {
		content: '';
		position: absolute;
		left: 0;
		right: 0;
		bottom: 100%;
		height: env(safe-area-inset-top);
		background: var(--header-glass);
	}
	/* The conditions never shrink; the elevations wrap below them if both can't fit. */
	.mrow .pill {
		flex: 0 0 auto;
		overflow: visible;
		padding: 5px 12px 5px 5px;
		font-size: 0.8rem;
	}
	.seg.elevs {
		flex: 0 1 auto;
		min-width: 0;
		margin-left: auto;
		padding: 3px;
	}
	.seg.elevs button {
		display: grid;
		justify-items: center;
		min-width: 0;
		width: 64px;
		padding: 4px 4px 5px;
		line-height: 1.15;
	}
	.seg.elevs .bn {
		max-width: 100%;
		font-size: 0.62rem;
		font-weight: 500;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.seg.elevs button[aria-pressed='true'] .bn {
		color: var(--text);
	}
	.seg.elevs .be {
		font-size: 0.86rem;
	}
	.tabs.under {
		display: flex;
		width: auto;
		margin: 0 -16px 12px;
		padding: 0 6px;
		border: 0;
		border-bottom: 1px solid var(--grid);
		border-radius: 0;
		background: none;
		box-shadow: none;
		backdrop-filter: none;
		-webkit-backdrop-filter: none;
	}
	.tabs.under button {
		flex: 1 1 auto;
		min-width: 0;
		border-radius: 0;
		padding: 12px 6px;
		font-size: 0.88rem;
	}
	.tabs.under button[aria-selected='true'] {
		background: none;
		box-shadow: inset 0 -2px 0 var(--accent);
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
		padding: 11px 12px;
		min-width: 0;
	}
	.mout > div + div {
		border-left: 1px solid var(--grid);
	}
	.mout .eyebrow {
		font-size: 0.66rem;
	}
	.mstorm .eyebrow {
		color: var(--accent-ink);
	}
	.mnum {
		font-family: var(--font-num);
		font-size: 1.35rem;
		font-weight: 600;
		line-height: 1.15;
		letter-spacing: -0.02em;
	}
	.msub {
		font-size: 0.74rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	@media (max-width: 640px) {
		.chartcard {
			padding: 12px 10px;
		}
		.stackcol {
			gap: 12px;
		}
	}
</style>
