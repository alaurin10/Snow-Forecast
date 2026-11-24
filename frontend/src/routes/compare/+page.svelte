<!-- Compare: the locations you choose, on one chart and day by day (docs/COMPARE-PLAN.md).
     Nothing is picked for you. The open comparison lives in the URL (so a link opens it
     and Back undoes adding or removing a location); a group is a comparison saved under a
     name in this browser, kept up to date as you change it. One band for every location,
     with each one's real elevation shown; up to 8 locations, up to 4 of them as lines. -->
<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import { getOverview, getSnapshot } from '../../lib/api';
	import { prefs } from '../../lib/prefs.svelte';
	import { viewport } from '../../lib/viewport.svelte';
	import { friendlyError } from '../../lib/errors';
	import { ago, weekday } from '../../lib/time';
	import { snow } from '../../lib/units';
	import type { OverviewRow, Snapshot } from '../../lib/types.gen';
	import {
		addGroup,
		addLocation,
		BANDS,
		buildTimeline,
		clean,
		cleanName,
		COMPARE_RANGES,
		dayCells,
		dayStart,
		emptyComparison,
		findGroup,
		fromQuery,
		hoursAhead,
		lineSlot,
		MAX_GROUPS,
		MAX_LOCS,
		METRIC_NAMES,
		moveGroup,
		moveLocation,
		pickBand,
		removeGroup,
		removeLocation,
		renameGroup,
		restoreGroup,
		summarizeSteps,
		toggleLine,
		toQuery,
		updateGroup,
		windowDays,
		windowSpan,
		dayStarts,
		windowFor,
		type BandName,
		type Comparison,
		type Group
	} from '../../lib/compare';
	import ErrorNote from '../../lib/components/ErrorNote.svelte';
	import Sheet from '../../lib/components/Sheet.svelte';
	import CompareChart from '../../lib/charts/CompareChart.svelte';
	import CompareRows, { type RowView } from '../../lib/components/CompareRows.svelte';
	import CompareTimeline, { type TimelineDay } from '../../lib/components/CompareTimeline.svelte';
	import CompareAdd, { type AddItem } from '../../lib/components/CompareAdd.svelte';
	import CompareGroups from '../../lib/components/CompareGroups.svelte';
	import ShareButton from '../../lib/share/ShareButton.svelte';
	import { paint, slug } from '../../lib/share/canvas';
	import { compareColors, drawCompareCard } from '../../lib/share/compareCard';

	const BAND_NAMES: Record<BandName, string> = { base: 'Base', mid: 'Mid', summit: 'Summit' };
	/** A forecast older than this gets a note on its row (runs are every 3 hours). */
	const STALE_H = 9;

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
	const nameOf = (id: string) => rows?.find((r) => r.id === id)?.name ?? id;

	// --- The open comparison: in the URL; with none there, the one open last -------------
	const parsed = $derived(fromQuery(page.url.searchParams));
	const cmp = $derived(parsed?.cmp ?? emptyComparison());
	const urlName = $derived(parsed?.name ?? null);
	const group = $derived(findGroup(prefs.compareGroups, urlName));

	function go(query: string, replace: boolean) {
		// A real navigation (so Back steps through it), keeping the scroll and the focus.
		void goto(resolve(`/compare?${query}`), { replace, reset: false });
	}
	$effect(() => {
		const saved = prefs.compareOpen;
		if (!page.url.searchParams.has('loc') && saved) untrack(() => go(saved, true));
	});
	$effect(() => {
		if (page.url.searchParams.has('loc')) prefs.setCompareOpen(page.url.searchParams.toString());
	});

	/** A change to the comparison: into the URL, and into the open group. Adding or removing
	 *  a location makes a new history entry (so Back undoes it); the rest replace it. */
	function commit(next: Comparison, push = false) {
		if (group) prefs.setCompareGroups(updateGroup(prefs.compareGroups, group.name, next));
		go(toQuery(next, group?.name ?? urlName), !push);
	}

	// Locations the owner has since removed drop out, with a note.
	$effect(() => {
		if (!rows || !parsed) return;
		const known = new Set(rows.map((r) => r.id));
		const gone = cmp.locs.filter((id) => !known.has(id));
		if (!gone.length) return;
		untrack(() => {
			commit(clean(cmp, known));
			toast(
				gone.length === 1
					? 'A location in this comparison is no longer on this site, so it was taken out.'
					: `${gone.length} locations in this comparison are no longer on this site, so they were taken out.`
			);
		});
	});

	// --- Each location's forecast ----------------------------------------------------------
	let snaps = $state<Record<string, Snapshot | 'error'>>({});
	// Asked for once each. Not reactive on purpose: the answers land in `snaps`.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- bookkeeping, never rendered
	const asked = new Set<string>();
	$effect(() => {
		for (const id of cmp.locs) {
			if (asked.has(id)) continue;
			asked.add(id);
			getSnapshot(id)
				.then((s) => (snaps[id] = s))
				.catch(() => (snaps[id] = 'error'));
		}
	});
	const loaded = $derived(
		cmp.locs.flatMap((id) => {
			const s = snaps[id];
			return s && s !== 'error' ? [{ id, name: nameOf(id), snap: s }] : [];
		})
	);
	const timeline = $derived(buildTimeline(loaded, cmp.band, cmp.range));

	// --- The window the chart shows, moved with the timeline under it ------------------
	let startMs = $state<number | null>(null);
	let hoverT = $state<string | null>(null);
	// Picking out one location's line: pointing at it (a mouse, for as long as it's there)
	// or selecting it (a tap or click on its card; again to clear, another to switch).
	// What's pointed at wins; when the pointer leaves, the selection shows again.
	let hover = $state<string | null>(null);
	let selected = $state<string | null>(null);
	const drawn = (id: string | null) => id !== null && cmp.on.includes(id);
	const hl = $derived(drawn(hover) ? hover : drawn(selected) ? selected : null);
	const select = (id: string) => (selected = selected === id ? null : id);
	// A selection whose line goes away is cleared.
	$effect(() => {
		if (selected && !cmp.on.includes(selected)) untrack(() => (selected = null));
	});
	const win = $derived(windowFor(timeline.slots, cmp.range, startMs));
	const inView = $derived(windowDays(timeline.slots, win, timeline.dates));
	function showDay(k: number) {
		const last = Math.max(0, timeline.dates.length - 1);
		startMs = dayStart(timeline.slots, timeline.dates, Math.max(0, Math.min(last, k)));
		hoverT = null;
	}
	$effect(() => {
		if (prefs.showTimeline !== 'on') untrack(() => (startMs = null));
	});
	const centreOn = (k: number) => showDay(k - Math.floor((cmp.range - 1) / 2));
	const stepDay = (by: -1 | 1) => showDay(inView.from + by);
	const span = $derived(
		windowSpan(timeline.slots, win, dayStarts(timeline.ref?.band.hourly.t ?? [], timeline.dates))
	);

	// --- The rows ----------------------------------------------------------------------------
	let editing = $state(false);
	const rowViews = $derived<RowView[]>(
		cmp.locs.map((id) => {
			const s = snaps[id];
			const base = {
				id,
				name: nameOf(id),
				slot: lineSlot(cmp, id),
				elev_m: null,
				bandLabel: '',
				cells: [],
				summary: null,
				stale: null
			};
			if (!s) return { ...base, state: 'loading' };
			if (s === 'error') {
				const ov = rows?.find((r) => r.id === id);
				return { ...base, state: ov && ov.run_id == null ? 'nodata' : 'error' };
			}
			const band = pickBand(s, cmp.band);
			const cells = dayCells(band, timeline.dates);
			const track = timeline.tracks.find((t) => t.id === id);
			const hours = (Date.now() - Date.parse(s.generated_at)) / 3600e3;
			return {
				...base,
				state: 'ok',
				elev_m: band.elev_m,
				bandLabel: band.label,
				cells,
				summary: track ? summarizeSteps(track.steps.slice(win.off, win.off + win.n)) : null,
				stale: hours > STALE_H ? `updated ${ago(s.generated_at)}` : null
			};
		})
	);
	const timelineDays = $derived<TimelineDay[]>(
		timeline.dates.map((date, k) => {
			const wd = weekday(date);
			return {
				date,
				label: k === 0 ? 'Today' : wd,
				short: k === 0 ? 'Tod' : wd.slice(0, 2),
				bars: rowViews
					.filter((r) => r.slot >= 0 && r.state === 'ok')
					.sort((a, b) => a.slot - b.slot)
					.map((r) => ({ id: r.id, name: r.name, slot: r.slot, cm: r.cells[k]?.snow ?? 0 }))
			};
		})
	);
	const shownRows = $derived(
		prefs.compareSort === 'snow'
			? [...rowViews].sort((a, b) => (b.summary?.snow ?? -1) - (a.summary?.snow ?? -1))
			: rowViews
	);
	$effect(() => {
		if (!cmp.locs.length) untrack(() => (editing = false));
	});

	function toggle(id: string) {
		const r = toggleLine(cmp, id);
		if (r.full) toast('Up to 4 lines at once: turn one off first.');
		else commit(r.cmp);
	}
	function pick(id: string) {
		commit(cmp.locs.includes(id) ? removeLocation(cmp, id) : addLocation(cmp, id), true);
	}

	// --- Adding locations ------------------------------------------------------------------
	let adding = $state(false);
	// A location page's Compare button: its location, with the Add list open to pick the rest.
	$effect(() => {
		if (!page.url.searchParams.has('add')) return;
		untrack(() => {
			adding = true;
			go(toQuery(cmp, urlName), true);
		});
	});
	// First visit (nothing in the comparison): tick several, then Compare.
	let draft = $state<string[]>([]);
	function pickDraft(id: string) {
		if (draft.includes(id)) draft = draft.filter((x) => x !== id);
		else if (draft.length < MAX_LOCS) draft = [...draft, id];
	}
	function startCompare() {
		let next = cmp;
		for (const id of draft) next = addLocation(next, id);
		draft = [];
		commit(next, true);
	}
	const addItems = $derived<AddItem[]>(
		(rows ?? []).map((r) => ({
			id: r.id,
			name: r.name,
			region: r.region,
			kind: r.kind,
			next5: snow(r.next5_cm, prefs.units),
			ready: r.run_id != null
		}))
	);

	// --- Groups ------------------------------------------------------------------------------
	let groupsOpen = $state(false);
	const same = (a: string, b: string) => a.toLocaleLowerCase() === b.toLocaleLowerCase();
	function openGroup(g: Group) {
		groupsOpen = false;
		startMs = null;
		hoverT = null;
		go(toQuery(g, g.name), false);
	}
	function newComparison() {
		groupsOpen = false;
		startMs = null;
		hoverT = null;
		go(toQuery(emptyComparison()), false);
	}
	function renameOne(from: string, to: string): string | null {
		const r = renameGroup(prefs.compareGroups, from, to);
		if (r.error)
			return r.error === 'exists' ? 'You already have a group with that name.' : 'Give it a name.';
		prefs.setCompareGroups(r.groups);
		if (group && same(group.name, from)) go(toQuery(cmp, r.name), true);
		return null;
	}
	function deleteOne(name: string) {
		const r = removeGroup(prefs.compareGroups, name);
		const removed = r.removed;
		if (!removed) return;
		const wasOpen = !!group && same(group.name, name);
		prefs.setCompareGroups(r.groups);
		if (wasOpen) go(toQuery(cmp, null), true);
		toast(`Deleted “${removed.group.name}”.`, {
			label: 'Undo',
			run: () => {
				prefs.setCompareGroups(restoreGroup(prefs.compareGroups, removed));
				if (wasOpen) go(toQuery(removed.group, removed.group.name), true);
			}
		});
	}

	let saving = $state(false);
	let saveName = $state('');
	let saveErr = $state<string | null>(null);
	function startSave() {
		saveName = urlName ?? '';
		saveErr = null;
		saving = true;
	}
	function doSave(e: SubmitEvent) {
		e.preventDefault();
		const r = addGroup(prefs.compareGroups, saveName, cmp);
		if (r.error) {
			saveErr = {
				name: 'Give the group a name.',
				exists: 'You already have a group with that name.',
				full: `This browser keeps ${MAX_GROUPS} groups at most. Delete one first.`
			}[r.error];
			return;
		}
		const n = cleanName(saveName);
		prefs.setCompareGroups(r.groups);
		saving = false;
		go(toQuery(cmp, n), true);
		toast(`Saved “${n}”.`);
	}

	// --- Share and Copy link ------------------------------------------------------------
	const shareTitle = $derived(group?.name ?? urlName ?? 'Compare');

	async function copyLink() {
		const url = `${location.origin}${resolve(`/compare?${toQuery(cmp, group?.name ?? urlName)}`)}`;
		try {
			if (viewport.phone && navigator.share) {
				await navigator.share({ title: `${group?.name ?? 'Compare'} · Snow Watch`, url });
				return;
			}
			await navigator.clipboard.writeText(url);
			toast('Link copied. Open it on another device to see this comparison there.');
		} catch (e) {
			if ((e as DOMException)?.name !== 'AbortError') toast('Couldn’t copy the link.');
		}
	}

	// --- A short note at the foot of the screen ------------------------------------------
	let note = $state<{ text: string; action?: { label: string; run: () => void } } | null>(null);
	let noteTimer: ReturnType<typeof setTimeout> | undefined;
	function toast(text: string, action?: { label: string; run: () => void }) {
		clearTimeout(noteTimer);
		note = { text, action };
		noteTimer = setTimeout(() => (note = null), action ? 7000 : 4000);
	}
	$effect(() => () => clearTimeout(noteTimer));

	// Places whose clocks differ from the chart's.
	const zoneNote = $derived.by(() => {
		const ref = timeline.ref;
		if (!ref) return '';
		const parts = timeline.tracks
			.filter((t) => t.offset !== ref.offset)
			.map((t) => {
				const h = hoursAhead(t.offset, ref.offset);
				return `${t.name} is ${Math.abs(h)} h ${h > 0 ? 'ahead' : 'behind'}`;
			});
		return parts.length ? `Times are ${ref.name}’s; ${parts.join(', ')}.` : '';
	});
</script>

<svelte:head><title>Compare · Snow Watch</title></svelte:head>

<header class="head">
	<h1>Compare</h1>
	{#if cmp.locs.length}
		<div class="acts">
			<button class="linkbtn glass" onclick={copyLink} aria-label="Copy a link to this comparison">
				<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
					><path
						d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"
					/></svg
				>
				<span>Copy link</span>
			</button>
			<ShareButton
				label="Share this comparison"
				filename={slug(`${shareTitle} ${METRIC_NAMES[cmp.metric].long} ${cmp.range} day`)}
				render={(shape) =>
					paint(shape, (ctx, p) =>
						drawCompareCard(
							ctx,
							shape,
							{
								title: shareTitle,
								timeline,
								cmp,
								win,
								units: prefs.units,
								selected: drawn(selected) ? selected : null,
								colors: compareColors(),
								total: prefs.snowTotal
							},
							p
						)
					)}
			/>
		</div>
	{/if}
</header>

<div class="bar">
	<button class="gpill glass" onclick={() => (groupsOpen = true)} aria-haspopup="dialog">
		<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
			><path d="M4 7h16M4 12h16M4 17h10" /></svg
		>
		<span class="gname">{group?.name ?? urlName ?? 'New comparison'}</span>
		<svg class="chev" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"
			><path d="M6 9l6 6 6-6" /></svg
		>
	</button>
	{#if !group && cmp.locs.length}
		<button class="save glass" onclick={startSave}
			>{urlName ? 'Save group' : 'Save as group'}</button
		>
	{/if}
	<div class="seg glass bands" role="group" aria-label="Elevation">
		{#each BANDS as b (b)}
			<button aria-pressed={cmp.band === b} onclick={() => commit({ ...cmp, band: b })}
				>{BAND_NAMES[b]}</button
			>
		{/each}
	</div>
</div>

{#if error}
	<ErrorNote message={error} onretry={() => retry++} />
{:else if !rows}
	<p class="loading glass" aria-live="polite">Loading…</p>
{:else if !cmp.locs.length}
	<section class="card pick">
		<h2>Choose locations to compare</h2>
		<p class="muted">
			Pick up to {MAX_LOCS}. Up to four are drawn as lines on one chart; every one gets a row of
			days. Save the set as a group to open it again later.
		</p>
		<CompareAdd items={addItems} picked={draft} ontoggle={pickDraft} />
		<div class="go">
			<button class="btn" disabled={!draft.length} onclick={startCompare}
				>{draft.length
					? `Compare ${draft.length} ${draft.length === 1 ? 'location' : 'locations'}`
					: 'Compare'}</button
			>
		</div>
	</section>
{:else}
	<section class="card chartcard" aria-label="Comparison">
		<CompareChart
			{timeline}
			{cmp}
			units={prefs.units}
			{win}
			bind:hoverT
			{hl}
			{selected}
			total={prefs.snowTotal}
			onhover={(id) => (hover = id)}
			onselect={select}
			onmetric={(m) => commit({ ...cmp, metric: m })}
			empty={loaded.length ? undefined : 'Loading…'}
		/>
		{#if prefs.showTimeline === 'on'}
			<CompareTimeline
				days={timelineDays}
				{span}
				{inView}
				whole={win.maxOff === 0}
				canPrev={win.off > 0}
				canNext={win.off < win.maxOff}
				range={cmp.range}
				units={prefs.units}
				onday={centreOn}
				onstep={stepDay}
				onhome={() => showDay(0)}
			/>
		{/if}
		<div class="rangebar">
			<div class="seg" role="group" aria-label="Time range">
				{#each COMPARE_RANGES as r (r)}
					<button aria-pressed={cmp.range === r} onclick={() => commit({ ...cmp, range: r })}
						>{r} {r === 1 ? 'day' : 'days'}</button
					>
				{/each}
			</div>
			<button
				class="tltoggle"
				aria-pressed={prefs.showTimeline === 'on'}
				aria-label={prefs.showTimeline === 'on' ? 'Hide the timeline' : 'Show the timeline'}
				title={prefs.showTimeline === 'on' ? 'Hide the timeline' : 'Show the timeline'}
				onclick={() => prefs.setShowTimeline(prefs.showTimeline !== 'on')}
			>
				<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"
					><path d="M3 18h18M6 18v-4M10 18V9M14 18v-6M18 18V7" /></svg
				>
				<span>Timeline</span>
			</button>
		</div>
		{#if zoneNote}<p class="zone faint">{zoneNote}</p>{/if}
		<div class="rowsblock">
			<CompareRows
				rows={shownRows}
				metric={cmp.metric}
				units={prefs.units}
				sort={prefs.compareSort}
				full={cmp.locs.length >= MAX_LOCS}
				bind:editing
				onsort={() => prefs.setCompareSort(prefs.compareSort === 'mine' ? 'snow' : 'mine')}
				ontoggle={toggle}
				onremove={(id) => commit(removeLocation(cmp, id), true)}
				onmove={(id, by) => commit(moveLocation(cmp, id, by))}
				onadd={() => (adding = true)}
				{hl}
				onhighlight={(id) => (hover = id)}
			/>
		</div>
	</section>
	<p class="callink">
		<a href={resolve('/calendar')}>Every location, snow only: Calendar</a>
	</p>
{/if}

{#if adding}
	<Sheet
		title="Add locations"
		sub="Up to {MAX_LOCS} in one comparison"
		onclose={() => (adding = false)}
	>
		<CompareAdd items={addItems} picked={cmp.locs} ontoggle={pick} />
		<button class="btn done" onclick={() => (adding = false)}>Done</button>
	</Sheet>
{/if}

{#if groupsOpen}
	<Sheet title="Groups" width={480} onclose={() => (groupsOpen = false)}>
		<CompareGroups
			groups={prefs.compareGroups}
			current={group?.name ?? null}
			{nameOf}
			onopen={openGroup}
			onnew={newComparison}
			onrename={renameOne}
			onmove={(name, by) => prefs.setCompareGroups(moveGroup(prefs.compareGroups, name, by))}
			ondelete={deleteOne}
		/>
	</Sheet>
{/if}

{#if saving}
	<Sheet title="Save as group" width={420} onclose={() => (saving = false)}>
		<form class="saveform" onsubmit={doSave}>
			<label for="group-name">Name</label>
			<!-- svelte-ignore a11y_autofocus -->
			<input
				id="group-name"
				bind:value={saveName}
				maxlength="40"
				placeholder="e.g. Washington touring"
				aria-invalid={saveErr ? 'true' : undefined}
				autofocus
			/>
			{#if saveErr}<p class="err" role="alert">{saveErr}</p>{/if}
			<p class="faint">
				Kept in this browser. It opens the way you leave it: its locations, lines, elevation, metric
				and days.
			</p>
			<button class="btn" type="submit">Save</button>
		</form>
	</Sheet>
{/if}

{#if note}
	<div class="toast glass" role="status">
		<span>{note.text}</span>
		{#if note.action}
			<button
				class="btn small"
				onclick={() => {
					note?.action?.run();
					note = null;
				}}>{note.action.label}</button
			>
		{/if}
	</div>
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 12px;
		padding: 44px 4px 12px;
	}
	h1 {
		font-family: var(--font-num);
		font-size: 2.9rem;
		font-weight: 700;
		letter-spacing: -0.03em;
		line-height: 1.05;
		margin: 0;
	}
	.acts {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.bar {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		margin-bottom: 12px;
	}
	.gpill,
	.save,
	.linkbtn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		min-height: 40px;
		padding: 0 14px;
		border-radius: 999px;
		font-size: 0.88rem;
		font-weight: 600;
		color: var(--text);
		cursor: pointer;
	}
	.gpill {
		max-width: min(320px, 100%);
		min-width: 0;
	}
	.gname {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.gpill svg,
	.linkbtn svg {
		flex: 0 0 auto;
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.bands {
		margin-left: auto;
	}
	.bands button {
		min-height: 34px;
	}
	.loading {
		display: inline-block;
		padding: 8px 16px;
		border-radius: 999px;
		color: var(--text-2);
	}
	.pick {
		display: grid;
		gap: 4px;
	}
	.pick h2 {
		margin: 0;
	}
	.pick p {
		margin: 0 0 6px;
		font-size: 0.88rem;
	}
	/* The Compare button stays in reach while the list scrolls. */
	.go {
		position: sticky;
		bottom: calc(84px + env(safe-area-inset-bottom));
		display: flex;
		justify-content: flex-end;
		padding-top: 8px;
	}
	@media (min-width: 1100px) {
		.go {
			bottom: 16px;
		}
	}
	.go .btn {
		min-height: 44px;
		padding: 0 22px;
	}
	.chartcard {
		display: grid;
		gap: 18px;
	}
	/* The range sits with the timeline, right under the chart. */
	.rangebar {
		margin-top: -8px;
		gap: 8px;
		align-items: center;
		display: flex;
		justify-content: center;
	}
	.tltoggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 42px;
		padding: 0 14px;
		border: 0;
		border-radius: 999px;
		background: var(--surface-2);
		color: var(--text-2);
		font-size: 0.84rem;
		font-weight: 600;
		cursor: pointer;
	}
	.tltoggle[aria-pressed='true'] {
		background: var(--sel);
		box-shadow: var(--sel-shadow);
		color: var(--text);
	}
	.tltoggle svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2.1;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	@media (max-width: 640px) {
		.tltoggle {
			width: 42px;
			padding: 0;
			justify-content: center;
		}
		.tltoggle span {
			display: none;
		}
	}
	.rangebar .seg button {
		min-height: 36px;
		padding: 0 16px;
	}
	.rowsblock {
		padding-top: 16px;
		border-top: 1px solid var(--grid);
	}
	.zone {
		margin: -8px 0 0;
		text-align: center;
		font-size: 0.76rem;
	}
	.callink {
		margin: 12px 4px 0;
		font-size: 0.84rem;
	}
	.callink a {
		color: var(--accent-ink);
	}
	.done {
		justify-self: end;
	}
	.saveform {
		display: grid;
		gap: 8px;
	}
	.saveform label {
		font-size: 0.84rem;
		font-weight: 600;
	}
	.saveform input {
		min-height: 44px;
		padding: 0 14px;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
		color: var(--text);
		font: inherit;
	}
	.saveform p {
		margin: 0;
		font-size: 0.8rem;
	}
	.saveform .btn {
		justify-self: end;
	}
	.err {
		color: var(--warn-ink);
	}
	.toast {
		position: fixed;
		left: 50%;
		bottom: calc(92px + env(safe-area-inset-bottom));
		transform: translateX(-50%);
		z-index: 45;
		width: max-content;
		max-width: calc(100vw - 32px);
		box-sizing: border-box;
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px 12px 10px 16px;
		border-radius: 18px;
		font-size: 0.86rem;
	}
	@media (min-width: 1100px) {
		.toast {
			bottom: 24px;
		}
	}
	/* Phones: a smaller heading, and the band switch on its own line under the group. */
	@media (max-width: 640px) {
		.head {
			padding-top: 6px;
		}
		h1 {
			font-size: 1.9rem;
		}
		.linkbtn span {
			display: none;
		}
		.linkbtn {
			width: 40px;
			padding: 0;
			justify-content: center;
		}
		.bands {
			margin-left: 0;
			width: 100%;
		}
		.bands button {
			flex: 1 1 0;
		}
		.chartcard {
			padding: 14px 12px;
			gap: 14px;
		}
	}
</style>
