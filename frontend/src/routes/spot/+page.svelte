<!-- A spot: the full forecast for any point in the US or Canada, made now on the server
     (docs/OPEN-METEO-PLAN.md, milestone 2), at /spot?lat=…&lon=… (shareable). The same
     page a saved location has (LocationView), without its history: no trend, scorecard
     or webcams. A cold area can take ~10 s, so the page's shape shows while it's made. -->
<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { ApiError, getMe, getSpot, getSpotNearby, spotQuery } from '../../lib/api';
	import type { NearbyOut, Snapshot } from '../../lib/types.gen';
	import LocationView from '../../lib/components/LocationView.svelte';
	import ErrorNote from '../../lib/components/ErrorNote.svelte';
	import { friendlyError } from '../../lib/errors';
	import { rememberSpot } from '../../lib/recentSpots';

	const num = (v: string | null) => (v === null || v.trim() === '' ? NaN : Number(v));
	const lat = $derived(num(page.url.searchParams.get('lat')));
	const lon = $derived(num(page.url.searchParams.get('lon')));
	const valid = $derived(
		Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
	);
	const key = $derived(valid ? spotQuery(lat, lon) : '');

	let snap = $state<Snapshot | null>(null);
	let shown = $state('');
	let error = $state<string | null>(null);
	let outside = $state(false);
	let retry = $state(0);
	let owner = $state(false);
	// Seconds spent making it, shown while it's made (a new area takes a while).
	let waited = $state(0);
	$effect(() => {
		if (snap && shown === key) return;
		if (error) return;
		waited = 0;
		const t0 = Date.now();
		const tick = setInterval(() => (waited = Math.floor((Date.now() - t0) / 1000)), 1000);
		return () => clearInterval(tick);
	});

	$effect(() => {
		getMe()
			.then((m) => (owner = m.is_owner))
			.catch(() => {});
	});

	$effect(() => {
		const k = key;
		void retry;
		let live = true;
		snap = null;
		error = null;
		outside = false;
		if (!k) {
			error = 'This link is missing the spot’s coordinates.';
			return;
		}
		const [a, b] = [lat, lon];
		getSpot(a, b)
			.then((s) => {
				if (!live) return;
				snap = s;
				shown = k;
				if (s.spot)
					rememberSpot({
						lat: s.spot.lat,
						lon: s.spot.lon,
						name: s.location.name,
						elev_m: s.spot.elev_m
					});
			})
			.catch((e: Error) => {
				if (!live) return;
				outside = e instanceof ApiError && e.status === 422;
				error = outside ? e.message : spotError(e);
			});
		return () => (live = false);
	});

	function spotError(e: Error): string {
		if (e instanceof ApiError && e.status === 503 && e.message !== 'offline')
			return 'A forecast for this spot can’t be made right now: the forecast server isn’t answering, or this site doesn’t offer forecasts anywhere. Try again in a minute.';
		if (e instanceof ApiError && e.status === 429)
			return 'Too many new spots just now. Wait a few seconds and try again.';
		return friendlyError(e);
	}

	// What's nearby is asked for once and feeds both the Observed and Backcountry tabs.
	let nearbyFor = '';
	let nearbyP: Promise<NearbyOut> | null = null;
	const nearby = () => {
		if (!nearbyP || nearbyFor !== shown) {
			nearbyFor = shown;
			nearbyP = getSpotNearby(lat, lon);
		}
		return nearbyP;
	};
	const mapHref = $derived(
		snap?.spot ? `${resolve('/map')}?lat=${snap.spot.lat}&lon=${snap.spot.lon}` : resolve('/map')
	);
	// The owner can keep a spot as a location: Manage, with its three bands filled in.
	const saveHref = $derived.by(() => {
		const s = snap;
		if (!s?.spot) return '';
		const q = new URLSearchParams({
			spot: `${s.spot.lat},${s.spot.lon}`,
			name: s.location.name,
			elev: s.bands.map((b) => Math.round(b.elev_m)).join(',')
		});
		return `${resolve('/admin')}?${q}`;
	});
</script>

<svelte:head
	><title>{snap ? `${snap.location.name} · Snow Watch` : 'A spot · Snow Watch'}</title></svelte:head
>

{#snippet saveAction()}
	{#if owner && saveHref}
		<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- resolved above -->
		<a class="pill glass savelink" href={saveHref} title="Keep this spot as a saved location">
			<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
				><path d="M6 3h12v18l-6-4-6 4z" /></svg
			>
			Save as location
		</a>
	{/if}
{/snippet}

{#if error}
	{#if outside}
		<div class="card">
			<h1 class="nf">No forecast here</h1>
			<p class="muted">{error}.</p>
			<a class="btn" href={resolve('/map')}>Back to the map</a>
		</div>
	{:else}
		<ErrorNote message={error} onretry={key ? () => retry++ : undefined}>
			<a href={resolve('/map')}>Back to the map</a>
		</ErrorNote>
	{/if}
{:else if !snap || shown !== key}
	<div class="skeleton" aria-busy="true" aria-live="polite">
		<p class="loading glass">
			Making a forecast for this spot…{#if waited >= 3}&nbsp;<span class="num">{waited} s</span
				>{/if}
		</p>
		{#if waited >= 12}
			<p class="muted small slow">
				The first forecast in an area takes longer: the server is reading this area's weather data
				for the first time. Spots nearby will be quicker.
			</p>
		{/if}
		<div class="card sk-head">
			<span class="mp-skel sk-title"></span>
			<span class="mp-skel"></span>
		</div>
		<div class="card sk-chart"><span class="mp-skel sk-block"></span></div>
		<div class="card sk-rows">
			{#each [1, 2, 3, 4] as i (i)}<span class="mp-skel sk-row"></span>{/each}
		</div>
	</div>
{:else}
	{#key shown}
		<LocationView
			bind:snap
			id={snap.location.id}
			refresh={() => getSpot(lat, lon, { fresh: true })}
			loadNearby={nearby}
			loadAvalanche={() => nearby().then((n) => n.avalanche ?? null)}
			{mapHref}
			actions={owner ? saveAction : undefined}
		/>
	{/key}
{/if}

<style>
	.nf {
		font-size: 1.2rem;
		margin: 0 0 6px;
	}
	.loading {
		display: inline-block;
		margin: 8px 0 12px;
		padding: 8px 16px;
		border-radius: 999px;
		color: var(--text-2);
	}
	.slow {
		margin: -6px 4px 4px;
		max-width: 40rem;
	}
	.skeleton {
		display: grid;
		gap: 16px;
	}
	.sk-head {
		display: grid;
		gap: 10px;
	}
	.sk-title {
		width: min(60%, 18rem);
		height: 1.8rem;
	}
	.sk-chart .sk-block {
		display: block;
		width: 100%;
		height: 220px;
	}
	.sk-rows {
		display: grid;
		gap: 12px;
	}
	.sk-row {
		width: 100%;
		height: 1.1rem;
	}
	.savelink {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 6px 14px 6px 12px;
		border-radius: 999px;
		font-size: 0.88rem;
		font-weight: 500;
		color: var(--text);
		text-decoration: none;
		white-space: nowrap;
	}
	.savelink:hover {
		background-color: var(--hover);
	}
	.savelink svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 1.9;
		stroke-linejoin: round;
	}
</style>
