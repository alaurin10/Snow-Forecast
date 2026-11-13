<!--
  One control at the foot of the map (terrain, weather, satellite, measure). At most one
  is open, above a single row of tabs naming them all (DockTabs.svelte), so the controls
  never stack up over the map; a closed one isn't drawn at all.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		open: boolean;
		/** Touched while open (so it stays the one open). */
		ontouch: () => void;
		children: Snippet;
	}

	let { open, ontouch, children }: Props = $props();
</script>

{#if open}
	<div class="item" onpointerdown={ontouch} role="presentation">
		{@render children()}
	</div>
{/if}

<style>
	.item {
		display: grid;
		justify-items: center;
		gap: 6px;
	}
	.item > :global(*) {
		width: 100%;
	}
</style>
