<!--
  One control at the foot of the map (weather, terrain, avalanche, satellite, measure).
  On phones and tablets at most one is open, above a single row of tabs naming them all
  (DockTabs.svelte), so the controls never stack up over the map; a closed one isn't
  drawn at all. On desktop they all stay open, stacked.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		/** Phones and tablets: only the open one shows. */
		compact: boolean;
		open: boolean;
		/** Touched while open (so it stays the one open). */
		ontouch: () => void;
		children: Snippet;
	}

	let { compact, open, ontouch, children }: Props = $props();
</script>

{#if !compact || open}
	<div class="item" onpointerdown={ontouch} role="presentation">
		{@render children()}
	</div>
{/if}

<style>
	.item {
		display: grid;
	}
</style>
