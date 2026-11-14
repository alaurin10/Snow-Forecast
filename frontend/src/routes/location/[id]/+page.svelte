<!-- One location. Desktop and tablet: the name on the sky with its conditions, then the
     sections' tabs and the elevation, the outlook card, and the section (Forecast,
     Models, Backcountry, Observed; keys 1–4 switch them too). On every screen, once the
     elevation picker has scrolled away, a compact one (numbers only) stays at the top
     right, or stacked in the empty margin beside the page on wide windows. Phones: the name, a "now" pill and the elevation numbers, tabs, and the
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
	import { hourIndex, sceneIcon } from '../../../lib/sky';
	import { luminance, skyPaint } from '../../../lib/skypaint';
	import { colorMode } from '../../../lib/mode.svelte';
	import WxIcon from '../../../lib/components/WxIcon.svelte';
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
		// Once the clock runs past the forecast's hours, quietly fetch a newer one.
		const current = id;
		skyState.set('page', snap, () =>
			getSnapshot(current, { fresh: true })
				.then((s) => current === id && snap && (snap = s))
				.catch(() => {})
		);
	});
	$effect(() => () => {
		sections.id = null;
		sections.list = [];
		skyState.set('page', null);
	});
	const tab = $derived(sections.tab);
	// Switching section (keys 1–4) from further down: back up to the tabs, so the new
	// section starts at its top rather than somewhere in its middle.
	let toolsEl = $state<HTMLElement>();
	let lastTab: Section | null = null;
	$effect(() => {
		const t = tab;
		if (lastTab && lastTab !== t && toolsEl && toolsEl.getBoundingClientRect().top < 0)
			toolsEl.scrollIntoView({ block: 'start' });
		lastTab = t;
	});
	const MAP_ICON = 'M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14';
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
	// The hour holding "now", for the current conditions: it follows the clock, like the sky.
	const nowAt = $derived(band && snap ? hourIndex(band.hourly, skyState.timeOf(snap)) : 0);
	const sky = $derived(skyState.current);
	// The pill's swatch: the backdrop's colours for this sky, with light lines when dark.
	const dotPaint = $derived(skyPaint(sky, colorMode.dark));
	const dotBg = $derived(`linear-gradient(180deg, ${dotPaint.k1}, ${dotPaint.k3})`);
	const dotLight = $derived(luminance(dotPaint.k2) < 0.2);
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
	// Phones: the conditions pill is an icon and the temperature; a tap shows the words.
	const nowTemp = $derived(band ? temperature(band.hourly.temp_c[nowAt], units) : '');
	const wxLine = $derived(
		band ? `${sky.label} · ${nowTemp} · ${band.label} · updated ${updated}` : ''
	);
	let wxOpen = $state(false);
	let pillwrap = $state<HTMLElement>();
	$effect(() => {
		if (!wxOpen) return;
		const away = (e: PointerEvent) => {
			if (!pillwrap?.contains(e.target as Node)) wxOpen = false;
		};
		const esc = (e: KeyboardEvent) => e.key === 'Escape' && (wxOpen = false);
		window.addEventListener('pointerdown', away);
		window.addEventListener('keydown', esc);
		return () => {
			window.removeEventListener('pointerdown', away);
			window.removeEventListener('keydown', esc);
		};
	});
	const avyRated = $derived(avy?.status === 'current' && !!avy.today_max);
	const avyCenter = $derived(avy?.doc?.center ?? null);
	const next5 = $derived(band?.windows['next5'] ?? null);

	// Once the page's elevation picker has scrolled away, the compact one slides in.
	let stuck = $state(false);
	function watchStuck(node: HTMLElement, top = 0) {
		if (typeof IntersectionObserver === 'undefined') return;
		const io = new IntersectionObserver(([e]) => (stuck = !e.isIntersecting), {
			rootMargin: `-${top}px 0px 0px 0px`
		});
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
			{#if snap.depth_method === 'slr'}
				<p class="muted small">
					Snow totals turn the models' snow water into depth with a ratio from the temperature while
					it snows (8:1 near freezing, up to 17:1 in the cold), so a cold storm reads deeper than
					the models' own 7:1 snowfall{#if band.windows['next5'].snow_cm_raw !== null && band.windows['next5'].snow_cm_raw !== band.windows['next5'].snow_cm}
						(next 5 days at 7:1: {snow(band.windows['next5'].snow_cm_raw, units)}){/if}.
				</p>
			{:else}
				<p class="muted small">
					Snow totals are the models' own snowfall, at a fixed 7:1 snow-to-water ratio.
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
			<a
				class="mmap glass"
				href="{resolve('/map')}?loc={encodeURIComponent(id)}"
				aria-label="View {snap.location.name} on the map"
				title="View on the map"
			>
				<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"
					><path d={MAP_ICON} /></svg
				>
			</a>
		</header>
		<p class="elevname" aria-hidden="true">
			{band.label} <span class="faint">· {c.heightUnit}</span>
		</p>
		<div class="mrow">
			<span class="pillwrap" bind:this={pillwrap}>
				<button
					class="pill glass wxpill"
					aria-label={wxLine}
					aria-expanded={wxOpen}
					aria-controls="wxpop"
					title={wxLine}
					onclick={() => (wxOpen = !wxOpen)}
				>
					<span
						class="skydot"
						class:inklight={dotLight}
						style:background={dotBg}
						data-weather={sky.weather}
						><WxIcon icon={sceneIcon(sky)} size={15} label={sky.label} /></span
					>
					<span class="ptemp num">{nowTemp}</span>
				</button>
				{#if wxOpen}
					<span class="wxpop glass" id="wxpop" role="status">{wxLine}</span>
				{/if}
			</span>
			<div class="seg glass elevs" role="group" aria-label="Elevation, {c.heightUnit}">
				{#each snap.bands as b (b.band)}
					<button
						class="num"
						aria-pressed={band.band === b.band}
						aria-label="{b.label}, {elevation(b.elev_m, units)}"
						onclick={() => prefs.setBand(b.band as BandName)}>{elevNum(b.elev_m)}</button
					>
				{/each}
			</div>
		</div>
		{@render elevBand()}
	{:else}
		<header class="lhead">
			<div class="title">
				<h1>{snap.location.name}</h1>
				<div class="pills">
					<span class="pill glass" title="{snap.location.region} · {sky.label} now">
						<span
							class="skydot"
							class:inklight={dotLight}
							style:background={dotBg}
							data-weather={sky.weather}
							aria-hidden="true"><WxIcon icon={sceneIcon(sky)} size={14} label={sky.label} /></span
						>
						<span class="ptxt">{snap.location.region} · {sky.label} now</span>
					</span>
					<span class="pill glass faintpill" title="Updated {updated}">
						<span class="ptxt">Updated {updated}</span>
					</span>
					<a
						class="pill glass maplink"
						href="{resolve('/map')}?loc={encodeURIComponent(id)}"
						aria-label="View {snap.location.name} on the map"
						title="View on the map"
					>
						<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
							><path d={MAP_ICON} /></svg
						>
						Map
					</a>
				</div>
			</div>
		</header>
		<!-- Which section and which elevation: two pills that scroll with the page. -->
		<div class="ltools" bind:this={toolsEl}>
			{@render sectionTabs()}
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
		</div>
		{@render elevBand()}

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

	<!-- The compact elevation picker (numbers only), once the page's own has scrolled away:
	     at the top right of the page, or stacked in the empty margin on wide windows. It
	     takes no room in the page; only the pill itself takes clicks. -->
	{#snippet elevBand()}
		<div class="stuckmark" use:watchStuck aria-hidden="true"></div>
		<div class="bandwrap">
			<div class="band" class:shown={stuck} inert={!stuck}>
				<div class="seg glass elevs" role="group" aria-label="Elevation, {c.heightUnit}">
					{#each snap!.bands as b (b.band)}
						<button
							class="num"
							aria-pressed={band!.band === b.band}
							aria-label="{b.label}, {elevation(b.elev_m, units)}"
							title="{b.label}, {elevation(b.elev_m, units)}"
							onclick={() => prefs.setBand(b.band as BandName)}>{elevNum(b.elev_m)}</button
						>
					{/each}
				</div>
			</div>
		</div>
	{/snippet}
	{#snippet sectionTabs()}
		<div class="tabs" class:under={phone} role="tablist" aria-label="Sections">
			{#each tabs as t, i (t)}
				<button
					role="tab"
					aria-selected={tab === t}
					title={phone ? undefined : `${SECTION_NAMES[t]} (${i + 1})`}
					onclick={() => (sections.tab = t)}>{SECTION_NAMES[t]}</button
				>
			{/each}
		</div>
	{/snippet}
	<!-- Phones: the tabs sit above the section (desktops and tablets have them in the
	     toolbar under the name). -->
	{#if phone}{@render sectionTabs()}{/if}

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
			depthMethod={snap?.depth_method}
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
		max-width: 100%;
		min-width: 0;
	}
	/* Ellipsis works on a block, not on the flex pill itself: the words shrink and end in
	   "…", the temperature beside them never does. */
	.ptxt {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	/* A swatch of the sky (the backdrop's own colours, set inline), with the weather's
	   icon on it: dark lines on a light sky, light lines on a dark one. */
	.skydot {
		flex: 0 0 20px;
		height: 20px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		background: linear-gradient(180deg, #62a8ea, #e6f1fa);
		box-shadow: inset 0 0 0 1px var(--glass-border);
		transition: background 900ms ease;
		--text-2: #22324d;
		--snow: #2f5fae;
		--rain: #1f6f5a;
	}
	.skydot.inklight {
		--text-2: #f2f4ff;
		--snow: #a8c8ff;
		--rain: #8fd6c0;
	}

	/* --- Desktop and tablet --- */
	/* A taller band of sky above the name, so the weather shows before the panels start. */
	.lhead {
		padding: 44px 4px 12px;
	}
	.lhead h1 {
		font-size: 2.9rem;
		margin-bottom: 10px;
	}
	.title {
		min-width: 0;
		max-width: 100%;
	}
	.pills {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		min-width: 0;
	}
	.maplink {
		flex: 0 0 auto;
		padding-left: 12px;
		color: var(--text);
		text-decoration: none;
	}
	.maplink:hover {
		background-color: var(--hover);
	}
	.maplink svg,
	.mmap svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 1.9;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.faintpill {
		padding-left: 14px;
		color: var(--text-2);
		font-weight: 400;
	}
	/* Tabs on the left, elevation on the right: two separate pills, both 52 px tall. */
	.ltools {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 8px 16px;
		margin: 0 0 16px;
		scroll-margin-top: 14px;
	}
	/* A zero-height sticky holder, so the pill follows the column and takes no room; it
	   slides down into view once the page's picker is gone. */
	.bandwrap {
		position: sticky;
		top: 14px;
		z-index: 30;
		height: 0;
	}
	.band {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		display: flex;
		justify-content: flex-end;
		/* Only the pill takes clicks; the rest is the page. */
		pointer-events: none;
		opacity: 0;
		transform: translateY(-8px);
		visibility: hidden;
		transition:
			opacity var(--ease),
			transform var(--ease),
			visibility 0s 200ms;
	}
	.band.shown {
		opacity: 1;
		transform: none;
		visibility: visible;
		transition:
			opacity var(--ease),
			transform var(--ease),
			visibility 0s;
	}
	.band .seg.elevs {
		flex: 0 0 auto;
		height: 40px;
		box-sizing: border-box;
		padding: 3px;
		pointer-events: auto;
	}
	.band .seg.elevs button {
		min-width: 56px;
		padding: 6px 8px;
		font-size: 0.84rem;
	}
	/* Phones: just under the status bar, where the page's picker was. */
	@media (max-width: 640px) {
		.bandwrap {
			top: calc(env(safe-area-inset-top) + 8px);
		}
	}
	/* Wide windows have an empty margin right of the page: the pill stands there,
	   stacked, beside the page rather than over it. */
	@media (min-width: 1620px) {
		.band {
			left: calc(100% + 16px);
			right: auto;
		}
		.band .seg.elevs {
			flex-direction: column;
			height: auto;
			border-radius: 24px;
		}
		.band .seg.elevs button {
			min-width: 64px;
			padding: 9px 8px;
		}
	}
	.ltools .tabs {
		margin: 0;
		height: 52px;
		box-sizing: border-box;
		align-items: stretch;
	}
	.ltools .tabs button {
		display: grid;
		place-items: center;
		padding: 0 20px;
	}
	.seg.elev {
		height: 52px;
		box-sizing: border-box;
		padding: 4px;
		border-radius: 999px;
	}
	.seg.elev button {
		display: grid;
		align-content: center;
		justify-items: center;
		gap: 0;
		padding: 0 16px;
		border-radius: 999px;
		min-width: 104px;
		line-height: 1.2;
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
		font-weight: 500;
		transition:
			background-color var(--ease),
			box-shadow var(--ease);
	}
	/* Colour and background only: bold would widen the chosen tab and shift the others. */
	.tabs button[aria-selected='true'] {
		color: var(--text);
		background: var(--sel);
		box-shadow: var(--sel-shadow);
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
		margin: 0 0 4px;
	}
	.mhead h1 {
		flex: 1 1 auto;
		min-width: 0;
		font-size: 1.6rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.mback,
	.mmap {
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
	/* The conditions and the elevation (it scrolls with the page; the compact picker
	   takes over at the top once it's gone). */
	.mrow {
		position: relative;
		z-index: 30;
		display: flex;
		flex-wrap: nowrap;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin: -6px -16px 0;
		padding: 6px 16px;
	}
	/* One row, always. The conditions are an icon
	   and the temperature, with room for "−10°F", so the pill is the same width whatever
	   the weather; a tap shows the words under it. */
	.pillwrap {
		position: relative;
		flex: 0 0 auto;
	}
	.wxpill {
		border-color: var(--glass-border);
		color: var(--text);
		font: inherit;
		font-size: 0.86rem;
		font-weight: 500;
		padding: 5px 12px 5px 5px;
		cursor: pointer;
	}
	.wxpill .skydot {
		flex-basis: 26px;
		height: 26px;
	}
	.wxpill .ptemp {
		min-width: 4.6ch;
		font-variant-numeric: tabular-nums;
		text-align: left;
	}
	.wxpop {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 5;
		width: max-content;
		max-width: calc(100vw - 32px);
		padding: 8px 12px;
		border-radius: 14px;
		font-size: 0.8rem;
		font-weight: 500;
		white-space: normal;
		background-color: color-mix(in srgb, var(--surface) 94%, transparent);
	}
	.seg.elevs {
		flex: 0 0 auto;
		margin-left: auto;
		padding: 3px;
	}
	.seg.elevs button {
		min-width: 52px;
		padding: 8px 6px;
		font-size: 0.86rem;
	}
	/* The chosen elevation's name, above the selector (it scrolls away; the selector stays). */
	.elevname {
		margin: 0 6px 2px;
		text-align: right;
		font-size: 0.74rem;
		font-weight: 600;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
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
