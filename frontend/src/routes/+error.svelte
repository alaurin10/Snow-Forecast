<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';

	const missing = $derived(page.status === 404);
</script>

<svelte:head
	><title>{missing ? 'Not found' : 'Something went wrong'} · Snow Watch</title></svelte:head
>

<section class="card err">
	<h1>{missing ? 'There’s nothing here' : 'Something went wrong'}</h1>
	<p class="muted">
		{missing
			? 'The link may be old, or the location may have been removed.'
			: 'The page couldn’t be shown. Reloading usually fixes it.'}
	</p>
	<div class="actions">
		<a class="btn primary" href={resolve('/')}>Back to the overview</a>
		{#if !missing}<button class="btn" onclick={() => location.reload()}>Reload</button>{/if}
	</div>
</section>

<style>
	.err {
		max-width: 520px;
		margin: 48px auto;
		padding: 24px 26px;
	}
	h1 {
		font-family: var(--font-num);
		font-size: 1.9rem;
		font-weight: 700;
		letter-spacing: -0.02em;
		line-height: 1.1;
		margin: 0 0 8px;
	}
	.actions {
		display: flex;
		gap: 10px;
		flex-wrap: wrap;
		margin-top: 12px;
	}
</style>
