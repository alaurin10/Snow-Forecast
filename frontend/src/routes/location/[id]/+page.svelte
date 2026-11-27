<!-- One saved location: its forecast loads here, then LocationView shows it (one view per
     location, so nothing from the last one lingers), with its trend, scorecard, what's
     nearby and its avalanche forecast loaded alongside. -->
<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import {
		ApiError,
		getAvalanche,
		getNearby,
		getSnapshot,
		getTrend,
		getVerification
	} from '../../../lib/api';
	import type { Snapshot } from '../../../lib/types.gen';
	import LocationView from '../../../lib/components/LocationView.svelte';
	import ErrorNote from '../../../lib/components/ErrorNote.svelte';
	import { friendlyError } from '../../../lib/errors';

	const id = $derived(page.params.id ?? '');
	let snap = $state<Snapshot | null>(null);
	let shownId = $state('');
	let error = $state<string | null>(null);
	let notFound = $state(false);
	let retry = $state(0);

	$effect(() => {
		const current = id;
		void retry; // the Retry button runs this again
		// Answers for a location we've already left must not land on this one.
		let live = true;
		snap = null;
		error = null;
		notFound = false;
		getSnapshot(current)
			.then((s) => {
				if (!live) return;
				snap = s;
				shownId = current;
			})
			.catch((e: Error) => {
				if (!live) return;
				notFound = e instanceof ApiError && e.status === 404;
				error = notFound ? null : friendlyError(e);
			});
		return () => (live = false);
	});
</script>

<svelte:head
	><title>{snap ? `${snap.location.name} · Snow Watch` : 'Snow Watch'}</title></svelte:head
>

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
{:else if !snap || shownId !== id}
	<p class="loading glass" aria-live="polite">Loading…</p>
{:else}
	{#key shownId}
		<LocationView
			bind:snap
			id={shownId}
			refresh={() => getSnapshot(shownId, { fresh: true })}
			loadTrend={() => getTrend(shownId)}
			loadVerification={() => getVerification(shownId)}
			loadNearby={() => getNearby(shownId)}
			loadAvalanche={() => getAvalanche().then((all) => all[shownId] ?? null)}
			openPeriod={page.url.searchParams.get('period')}
			mapHref="{resolve('/map')}?loc={encodeURIComponent(shownId)}"
			compareHref="{resolve('/compare')}?loc={encodeURIComponent(shownId)}&add=1"
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
		margin: 8px 0;
		padding: 8px 16px;
		border-radius: 999px;
		color: var(--text-2);
	}
</style>
