<!--
  One control at the foot of the map (weather, terrain, avalanche, satellite, measure).
  On phones and tablets only one is open at a time, the last one touched; the others
  fold to a single line (what it is, what it shows now, a chevron) that opens it. Each
  form has a fixed height, so the map's padding doesn't nudge as their words change.
  On desktop they all stay open, stacked.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		/** What the control is: "Weather", "Satellite"… */
		title: string;
		/** What it shows now, in a few words, for the folded line. */
		status: string;
		/** Phones and tablets fold controls; desktop doesn't. */
		compact: boolean;
		open: boolean;
		/** Opened, or touched while open (so it stays the one open). */
		ontouch: () => void;
		children: Snippet;
	}

	let { title, status, compact, open, ontouch, children }: Props = $props();
</script>

{#if compact && !open}
	<button
		class="fold glass"
		aria-expanded="false"
		aria-label="{title}: {status}. Show the controls"
		onclick={ontouch}
		title="{title}: {status}"
	>
		<span class="eyebrow">{title}</span>
		<span class="st">{status}</span>
		<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
			><path d="M6 15l6-6 6 6" /></svg
		>
	</button>
{:else}
	<div class="item" onpointerdown={ontouch} role="presentation">
		{@render children()}
	</div>
{/if}

<style>
	.fold {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		height: 44px;
		padding: 0 12px 0 14px;
		border-radius: 16px;
		background: color-mix(in srgb, var(--surface) 90%, transparent);
		color: var(--text);
		font: inherit;
		font-size: 0.84rem;
		text-align: left;
		cursor: pointer;
	}
	.fold .eyebrow {
		flex: none;
	}
	.st {
		flex: 1;
		min-width: 0;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.fold svg {
		flex: none;
		fill: none;
		stroke: var(--text-2);
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.item {
		display: grid;
	}
</style>
