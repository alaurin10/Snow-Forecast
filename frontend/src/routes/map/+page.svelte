<script lang="ts">
	import { resolve } from '$app/paths';
	import { getOverview } from '../../lib/api';
	import { prefs } from '../../lib/prefs.svelte';
	import MapView from '../../lib/components/MapView.svelte';
	import type { OverviewRow } from '../../lib/types.gen';

	let rows = $state<OverviewRow[] | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		getOverview()
			.then((r) => (rows = r))
			.catch((e: Error) => (error = e.message));
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
	h1 {
		font-family: var(--font-num);
		font-size: 1.9rem;
		font-weight: 600;
		letter-spacing: -0.02em;
		margin: 4px 0 16px;
	}
	/* Phones and tablets: the map fills the screen; the title is for screen readers. */
	@media (max-width: 1099px) {
		h1 {
			position: absolute;
			width: 1px;
			height: 1px;
			overflow: hidden;
			clip-path: inset(50%);
			margin: 0;
		}
	}
</style>
