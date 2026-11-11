<!--
  One avalanche forecast zone's bulletin, exactly as published (the same card as a
  location's Backcountry tab): the three-band pyramid, the problems, the bottom line and
  a link to the center. Opened by tapping a zone.
-->
<script lang="ts">
	import type { ZoneFeature } from '../types.gen';
	import DangerPyramid from '../backcountry/DangerPyramid.svelte';

	interface Props {
		zone: ZoneFeature;
		onclose: () => void;
	}

	let { zone, onclose }: Props = $props();
</script>

<div class="sheet" role="dialog" aria-label="Avalanche forecast">
	<DangerPyramid
		view={zone.properties.view}
		tz={zone.properties.tz}
		today={zone.properties.today}
	/>
	<button class="close" onclick={onclose}>Close</button>
</div>

<style>
	.sheet {
		position: absolute;
		top: 56px;
		left: 60px;
		right: 10px;
		max-width: 420px;
		max-height: calc(100% - 180px);
		overflow-y: auto;
		z-index: 1003;
		padding: 12px 14px;
		border-radius: 14px;
		background: var(--surface);
		border: 1px solid var(--border);
		box-shadow: var(--glass-shadow);
		font-size: 0.85rem;
		color: var(--text);
		display: grid;
		gap: 8px;
	}
	.sheet :global(h2) {
		font-size: 1rem;
	}
	.close {
		justify-self: end;
		border: 0;
		background: transparent;
		color: var(--accent);
		font-weight: 600;
		cursor: pointer;
		padding: 4px 6px;
	}
	/* Clear the floating tab bar on phones, so the last button can be tapped. */
	@media (max-width: 1099px) {
		.sheet {
			max-height: calc(100% - 56px - 94px - env(safe-area-inset-bottom));
		}
	}
</style>
