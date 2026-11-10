<!-- A failed load: what happened, and a way to try again. -->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		message: string;
		onretry?: () => void;
		children?: Snippet;
	}

	let { message, onretry, children }: Props = $props();
</script>

<div class="card note" role="alert">
	<p>{message}</p>
	<div class="actions">
		{#if onretry}<button class="btn small" onclick={onretry}>Try again</button>{/if}
		{@render children?.()}
	</div>
</div>

<style>
	.note {
		border-color: var(--warn-border);
		background: var(--warn-bg);
	}
	p {
		margin: 0 0 8px;
	}
	.actions {
		display: flex;
		gap: 10px;
		align-items: center;
		flex-wrap: wrap;
	}
</style>
