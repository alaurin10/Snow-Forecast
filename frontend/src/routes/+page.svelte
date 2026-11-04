<script lang="ts">
	// Placeholder until milestone M2 builds the real pages.
	type Health = { status: string; age_s: number | null };

	let health = $state<Health | null>(null);
	let failed = $state(false);

	$effect(() => {
		fetch('/api/health')
			.then((r) => r.json() as Promise<Health>)
			.then((h) => (health = h))
			.catch(() => (failed = true));
	});
</script>

<svelte:head><title>Snow Watch</title></svelte:head>

<main>
	<h1>Snow Watch</h1>
	{#if failed}
		<p>The API isn't reachable.</p>
	{:else if health}
		<p>
			Data: {health.status}{#if health.age_s !== null}, updated {Math.round(health.age_s / 60)} min ago{/if}
		</p>
	{:else}
		<p>Loading…</p>
	{/if}
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 40rem;
		margin: 2rem auto;
		padding: 0 1rem;
	}
</style>
