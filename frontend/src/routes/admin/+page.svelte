<script lang="ts">
	import { resolve } from '$app/paths';
	import {
		adminLocations,
		adminLookups,
		archiveLocation,
		createLocation,
		ApiError,
		getBudget,
		getMe,
		logout,
		refreshLocation,
		refreshLookups,
		reorderLocations,
		resolveLocation,
		searchCatalog,
		updateLocation,
		waitForJob
	} from '../../lib/api';
	import { prefs } from '../../lib/prefs.svelte';
	import { friendlyError } from '../../lib/errors';
	import { elevation } from '../../lib/units';
	import MapPicker, { type PinBand, type Pins } from '../../lib/manage/MapPicker.svelte';
	import LocationForm from '../../lib/manage/LocationForm.svelte';
	import OwnerLogin from '../../lib/manage/OwnerLogin.svelte';
	import type {
		BudgetOut,
		CatalogItem,
		Location,
		LookupStatus,
		Me,
		ResolveIn,
		ResolveOut
	} from '../../lib/types.gen';

	type Mode = 'list' | 'resort' | 'zone' | 'review';

	let me = $state<Me | null>(null);
	let locs = $state<Location[]>([]);
	let budget = $state<BudgetOut | null>(null);
	let lookups = $state<LookupStatus | null>(null);
	let mode = $state<Mode>('list');
	let message = $state<string | null>(null);
	let error = $state<string | null>(null);

	// Review form state
	let draft = $state<Location | null>(null);
	let draftIsNew = $state(true);
	let detected = $state<ResolveOut | null>(null);
	let saving = $state(false);
	let busy = $state(false);

	// Add a resort
	let query = $state('');
	let results = $state<CatalogItem[]>([]);
	let searchTimer: ReturnType<typeof setTimeout> | undefined;
	let searchSeq = 0;

	// Add a backcountry zone
	let zoneName = $state('');
	let pins = $state<Pins>({});
	let activePin = $state<PinBand>('base');

	async function load() {
		error = null;
		try {
			me = await getMe();
			if (!me.is_owner) return;
			[locs, budget, lookups] = await Promise.all([adminLocations(), getBudget(), adminLookups()]);
		} catch (e) {
			if (!signedOut(e)) error = friendlyError(e);
		}
	}

	/** The session ended (expired, or signed out elsewhere): show the password form again. */
	function signedOut(e: unknown): boolean {
		if (e instanceof ApiError && e.status === 401 && me) {
			me = { ...me, is_owner: false };
			return true;
		}
		return false;
	}

	const signOut = () =>
		act(async () => {
			me = await logout();
		});

	// Job polling stops when the page is left.
	const leaving = new AbortController();
	$effect(() => {
		load();
		return () => leaving.abort();
	});

	/** Run an owner action; any failure becomes the page's error message. */
	async function act(work: () => Promise<void>) {
		error = null;
		try {
			await work();
		} catch (e) {
			if (!signedOut(e)) error = friendlyError(e);
		}
	}

	function onSearch(q: string) {
		query = q;
		clearTimeout(searchTimer);
		if (q.trim().length < 2) {
			results = [];
			return;
		}
		searchTimer = setTimeout(async () => {
			const asked = ++searchSeq;
			try {
				const found = await searchCatalog(q);
				if (asked === searchSeq) results = found; // ignore answers that arrive late
			} catch (e) {
				if (asked === searchSeq && !signedOut(e)) error = friendlyError(e);
			}
		}, 250);
	}

	function toLocation(r: ResolveOut): Location {
		return {
			id: r.id,
			name: r.name,
			kind: r.kind as Location['kind'],
			region: r.region,
			country: r.country,
			tz: r.tz,
			bands: r.bands,
			snotel: r.snotel,
			nws_office: r.nws_office,
			radar_station: r.radar_station,
			avy: r.avy,
			links: r.links,
			active: true
		} as Location;
	}

	async function detect(body: Parameters<typeof resolveLocation>[0]) {
		busy = true;
		error = null;
		try {
			detected = await resolveLocation(body);
			draft = toLocation(detected);
			draftIsNew = true;
			mode = 'review';
		} catch (e) {
			if (!signedOut(e)) error = friendlyError(e);
		} finally {
			busy = false;
		}
	}

	const pickResort = (c: CatalogItem) =>
		detect({
			kind: 'resort',
			catalog_id: c.id,
			name: c.name,
			pins: [{ band: 'mid', lat: c.lat, lon: c.lon }]
		});

	const detectZone = () =>
		detect({
			kind: 'backcountry',
			name: zoneName,
			pins: (Object.entries(pins) as [PinBand, { lat: number; lon: number }][]).map(
				([band, p]) => ({
					band,
					lat: p.lat,
					lon: p.lon
				})
			) as ResolveIn['pins']
		});

	async function follow(jobId: number | null | undefined, name: string, id: string) {
		if (!jobId) return;
		message = `Getting the forecast for ${name}… (this usually takes a minute or two)`;
		try {
			const job = await waitForJob(
				jobId,
				(j) => {
					if (j.status === 'running') message = `Fetching and analysing ${name}…`;
				},
				leaving.signal
			);
			if (leaving.signal.aborted) return;
			if (job.status === 'done') message = `${name} is ready.`;
			else if (job.status === 'failed')
				message = `The forecast for ${name} failed: ${job.error ?? 'unknown error'}. It will retry at the next scheduled run.`;
			else
				message = `${name} is still being fetched. It will appear on the overview when it’s ready.`;
			lastReady = job.status === 'done' ? id : null;
			await load();
		} catch (e) {
			if (!leaving.signal.aborted && !signedOut(e)) message = null;
		}
	}
	let lastReady = $state<string | null>(null);

	async function save(loc: Location) {
		saving = true;
		error = null;
		try {
			const res = draftIsNew ? await createLocation(loc) : await updateLocation(loc);
			mode = 'list';
			draft = null;
			detected = null;
			pins = {};
			zoneName = '';
			query = '';
			results = [];
			await load();
			void follow(res.job_id, loc.name, loc.id);
		} catch (e) {
			if (!signedOut(e)) error = friendlyError(e);
		} finally {
			saving = false;
		}
	}

	const move = (i: number, d: -1 | 1) =>
		act(async () => {
			const ids = locs.map((l) => l.id);
			const j = i + d;
			if (j < 0 || j >= ids.length) return;
			[ids[i], ids[j]] = [ids[j], ids[i]];
			await reorderLocations(ids);
			await load();
		});

	const toggle = (loc: Location) =>
		act(async () => {
			const res = await updateLocation({
				...$state.snapshot(loc),
				active: !loc.active
			} as Location);
			await load();
			void follow(res.job_id, loc.name, loc.id);
		});

	const refreshNow = (loc: Location) =>
		act(async () => {
			const job = await refreshLocation(loc.id);
			void follow(job.id, loc.name, loc.id);
		});

	const archive = (loc: Location) =>
		act(async () => {
			if (!confirm(`Remove ${loc.name}? Its history is kept and it can be added again.`)) return;
			await archiveLocation(loc.id);
			await load();
		});

	function edit(loc: Location) {
		draft = $state.snapshot(loc) as Location;
		draftIsNew = false;
		detected = null;
		mode = 'review';
	}

	const loadLookups = () =>
		act(async () => {
			const job = await refreshLookups();
			message = 'Loading the ski-area catalog, snow stations and avalanche zones…';
			const done = await waitForJob(job.id, undefined, leaving.signal);
			if (leaving.signal.aborted) return;
			message =
				done.status === 'done'
					? 'Lookups loaded.'
					: done.status === 'failed'
						? `Lookups failed: ${done.error}`
						: 'Still loading the lookups; check back in a few minutes.';
			await load();
		});

	const lookupsMissing = $derived(
		lookups !== null &&
			(lookups.ski_areas === 0 || lookups.snotel_stations === 0 || lookups.avy_zones === 0)
	);
	const atCap = $derived(budget !== null && budget.active >= budget.max_locations);
	const perLoc = $derived(budget && budget.active ? Math.round(budget.total / budget.active) : 150);
</script>

<svelte:head><title>Manage locations · Snow Watch</title></svelte:head>

<div class="head">
	<div class="title">
		<h1>Manage locations</h1>
		{#if me?.is_owner}<button class="btn" onclick={signOut}>Sign out</button>{/if}
	</div>
	{#if budget}
		<p class="muted small">
			{budget.active} of {budget.max_locations} locations · about {Math.round(
				budget.total
			).toLocaleString('en-US')}
			of {budget.budget.toLocaleString('en-US')} free Open-Meteo calls a day. Each new location adds about
			{perLoc}.
		</p>
	{/if}
</div>

{#if error}<p class="card bad" role="alert">{error}</p>{/if}
{#if message}<p class="card note" role="status">
		{message}
		{#if lastReady}<a href={resolve('/location/[id]', { id: lastReady })}>Open it</a>{/if}
	</p>{/if}

{#if me && !me.is_owner}
	{#if me.owner_login_enabled}
		<OwnerLogin
			onSignedIn={(m) => {
				me = m;
				load();
			}}
		/>
	{:else}
		<p class="card">
			Managing locations in the app is turned off on this server: set <code>OWNER_PASSWORD</code>
			to turn it on. <a href={resolve('/')}>Back to the overview</a>
		</p>
	{/if}
{:else if !me}
	<p class="muted">Loading…</p>
{:else if mode === 'review' && draft}
	<section class="card">
		<h2>{draftIsNew ? 'Check the details, then add it' : `Edit ${draft.name}`}</h2>
		<LocationForm
			initial={draft}
			isNew={draftIsNew}
			candidates={detected?.snotel_candidates ?? []}
			warnings={detected?.warnings ?? []}
			avyName={detected?.avy_name ?? null}
			{saving}
			onsave={save}
			oncancel={() => (mode = 'list')}
		/>
	</section>
{:else if mode === 'resort'}
	<section class="card">
		<h2>Add a resort</h2>
		<input
			class="search"
			type="search"
			aria-label="Search ski areas"
			placeholder="Search ski areas, e.g. Stevens Pass"
			value={query}
			oninput={(e) => onSearch(e.currentTarget.value)}
		/>
		{#if results.length}
			<ul class="results">
				{#each results as c (c.id)}
					<li>
						<button class="result" disabled={busy} onclick={() => pickResort(c)}>
							<strong>{c.name}</strong>
							<span class="faint">
								{c.region ?? ''}{c.country ? `, ${c.country}` : ''}
								{#if c.min_elev_m !== null && c.max_elev_m !== null}
									· {elevation(c.min_elev_m, prefs.units)}–{elevation(
										c.max_elev_m,
										prefs.units
									)}{/if}
							</span>
						</button>
					</li>
				{/each}
			</ul>
		{:else if query.trim().length >= 2}
			<p class="faint small">
				No ski areas match. Try fewer words, or add it as a zone with map pins.
			</p>
		{/if}
		{#if busy}<p class="muted small">
				Detecting elevations, timezone, weather office, snow station and avalanche zone…
			</p>{/if}
		<div class="actions"><button class="btn" onclick={() => (mode = 'list')}>Cancel</button></div>
	</section>
{:else if mode === 'zone'}
	<section class="card">
		<h2>Add a backcountry zone</h2>
		<label class="name"
			>Name <input bind:value={zoneName} placeholder="e.g. Maple Pass loop" /></label
		>
		<div class="seg pinseg" role="group" aria-label="Pin to place">
			<button aria-pressed={activePin === 'base'} onclick={() => (activePin = 'base')}
				>Trailhead{pins.base ? ' ✓' : ''}</button
			>
			<button aria-pressed={activePin === 'summit'} onclick={() => (activePin = 'summit')}
				>High point{pins.summit ? ' ✓' : ''}</button
			>
			<button aria-pressed={activePin === 'mid'} onclick={() => (activePin = 'mid')}
				>Mid (optional){pins.mid ? ' ✓' : ''}</button
			>
		</div>
		<p class="faint small">Tap the map to place the selected pin; drag a pin to move it.</p>
		<MapPicker
			{pins}
			active={activePin}
			onpick={(band, lat, lon) => {
				pins = { ...pins, [band]: { lat, lon } };
				if (band === 'base' && !pins.summit) activePin = 'summit';
			}}
		/>
		<div class="actions">
			<button class="btn" onclick={() => (mode = 'list')}>Cancel</button>
			<button
				class="btn primary"
				disabled={!pins.base || !pins.summit || !zoneName.trim() || busy}
				onclick={detectZone}
			>
				{busy ? 'Detecting…' : 'Detect details'}
			</button>
		</div>
	</section>
{:else}
	{#if lookupsMissing}
		<section class="card note">
			The ski-area catalog, SNOTEL stations or avalanche zones aren't loaded yet.
			<button class="btn small" onclick={loadLookups}>Load them</button>
		</section>
	{/if}
	<div class="addbar">
		<button class="btn primary" disabled={atCap} onclick={() => (mode = 'resort')}
			>+ Add a resort</button
		>
		<button class="btn primary" disabled={atCap} onclick={() => (mode = 'zone')}
			>+ Add a backcountry zone</button
		>
		{#if atCap}<span class="faint small"
				>At the limit of {budget?.max_locations} active locations; pause one first.</span
			>{/if}
	</div>
	<ul class="list">
		{#each locs as l, i (l.id)}
			<li class="card row" class:paused={!l.active}>
				<div class="order">
					<button
						class="btn small"
						aria-label={`Move ${l.name} up`}
						disabled={i === 0}
						onclick={() => move(i, -1)}>↑</button
					>
					<button
						class="btn small"
						aria-label={`Move ${l.name} down`}
						disabled={i === locs.length - 1}
						onclick={() => move(i, 1)}>↓</button
					>
				</div>
				<div class="info">
					<strong>{l.name}</strong>
					<span class="faint small">
						{l.kind === 'backcountry' ? 'Backcountry' : 'Resort'} · {l.region || l.country} ·
						{l.bands.map((b) => elevation(b.elev_m, prefs.units)).join(' / ')}
						{#if !l.active}
							· <em>paused</em>{/if}
					</span>
				</div>
				<div class="btns">
					<button class="btn small" onclick={() => edit(l)}>Edit</button>
					<button class="btn small" onclick={() => toggle(l)}
						>{l.active ? 'Pause' : 'Resume'}</button
					>
					{#if l.active}<button class="btn small" onclick={() => refreshNow(l)}>Refresh now</button
						>{/if}
					<button class="btn small" onclick={() => archive(l)}>Remove</button>
				</div>
			</li>
		{/each}
	</ul>
{/if}

<style>
	h1 {
		font-size: 1.3rem;
		margin: 4px 0 2px;
	}
	.small {
		font-size: 0.85rem;
	}
	.head p {
		margin: 0 0 12px;
	}
	.title {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
	}
	.bad {
		border-color: var(--temp);
	}
	.note {
		border-color: var(--snow);
		margin: 0 0 12px;
	}
	.note a {
		margin-left: 6px;
		color: var(--text);
	}
	.addbar {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		align-items: center;
		margin: 0 0 12px;
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 8px;
	}
	.row {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 6px 12px;
		align-items: center;
		padding: 10px 12px;
	}
	.row.paused {
		opacity: 0.65;
	}
	.order {
		display: grid;
		gap: 4px;
	}
	.info {
		display: grid;
		min-width: 0;
	}
	.btns {
		grid-column: 1 / -1;
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	@media (min-width: 800px) {
		.row {
			grid-template-columns: auto minmax(0, 1fr) auto;
		}
		.btns {
			grid-column: auto;
		}
	}
	.search {
		width: 100%;
		font: inherit;
		font-size: 1rem;
		padding: 9px 12px;
		border: 1px solid var(--border);
		border-radius: 10px;
		background: var(--surface);
		color: var(--text);
	}
	.results {
		list-style: none;
		padding: 0;
		margin: 8px 0 0;
		display: grid;
		gap: 4px;
	}
	.result {
		width: 100%;
		text-align: left;
		display: grid;
		gap: 1px;
		background: var(--surface-2);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 8px 10px;
		cursor: pointer;
	}
	.result span {
		font-size: 0.8rem;
	}
	.name {
		display: grid;
		gap: 3px;
		font-size: 0.82rem;
		color: var(--text-2);
		margin-bottom: 8px;
	}
	.name input {
		font: inherit;
		color: var(--text);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 7px 9px;
	}
	.pinseg {
		margin-bottom: 4px;
		flex-wrap: wrap;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 10px;
	}
</style>
