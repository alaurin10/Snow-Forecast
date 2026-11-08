<script lang="ts">
	import { resolve } from '$app/paths';
	import { getOverview } from '../../lib/api';
	import { prefs } from '../../lib/prefs.svelte';
	import { savedAreas } from '../../lib/offlineMaps';
	import MapView from '../../lib/components/MapView.svelte';
	import type { OverviewRow } from '../../lib/types.gen';

	let rows = $state<OverviewRow[] | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		getOverview()
			.then((r) => (rows = r))
			.catch((e: Error) => {
				// No connection and no recent copy: still open the map on the areas saved for
				// offline use, with no forecast numbers.
				const saved = Object.values(savedAreas());
				if (saved.length) {
					rows = saved.map(
						(a) =>
							({
								id: a.id,
								name: a.name,
								lat: a.lat,
								lon: a.lon,
								next5_cm: null
							}) as unknown as OverviewRow
					);
				} else error = e.message;
			});
	});

	const href = (id: string) => resolve('/location/[id]', { id });
</script>

<svelte:head><title>Map · Snow Watch</title></svelte:head>

<h1>Map</h1>

{#if error}
	<p class="card">Can't load the map: {error}</p>
{:else if !rows}
	<p class="muted">Loading…</p>
{:else}
	<MapView {rows} units={prefs.units} {href} radar />
{/if}

<style>
	/* The map fills the window; the title is for screen readers. */
	h1 {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		margin: 0;
	}
</style>
