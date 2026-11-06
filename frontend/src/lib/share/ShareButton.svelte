<!-- A small share icon that opens the share preview for whatever the page shows now. -->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import ShareSheet from './ShareSheet.svelte';
	import type { Shape } from './canvas';

	interface Props {
		/** What is shared, e.g. "Share the forecast chart"; also the button's label. */
		label: string;
		filename: string;
		render: (shape: Shape) => HTMLCanvasElement;
		options?: Snippet;
	}

	let { label, filename, render, options }: Props = $props();
	let open = $state(false);
</script>

<button class="share" onclick={() => (open = true)} aria-label={label} title={label}>
	<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"
		><path d="M12 3v12M7 8l5-5 5 5M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7" /></svg
	>
	<span>Share</span>
</button>

{#if open}
	<ShareSheet title={label} {filename} {render} {options} onclose={() => (open = false)} />
{/if}

<style>
	.share {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
		height: 32px;
		padding: 0 12px 0 10px;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: var(--surface-2);
		color: var(--text-2);
		font-size: 0.82rem;
		font-weight: 600;
		cursor: pointer;
	}
	.share:hover {
		color: var(--text);
	}
	.share svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2.2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	/* Phones: the icon alone keeps crowded headers tidy. */
	@media (max-width: 480px) {
		.share {
			width: 34px;
			height: 34px;
			padding: 0;
			justify-content: center;
		}
		.share span {
			display: none;
		}
	}
</style>
