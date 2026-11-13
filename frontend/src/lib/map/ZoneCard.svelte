<!--
  One avalanche forecast zone's bulletin, exactly as published (the same card as a
  location's Backcountry tab): the three-band pyramid, the problems, the bottom line and
  a link to the center. The map panel's content for a tapped zone.
-->
<script lang="ts">
	import type { ZoneFeature } from '../types.gen';
	import DangerPyramid from '../backcountry/DangerPyramid.svelte';

	interface Props {
		zone: ZoneFeature;
	}

	let { zone }: Props = $props();
</script>

<div class="content">
	<DangerPyramid
		view={zone.properties.view}
		tz={zone.properties.tz}
		today={zone.properties.today}
	/>
</div>

<style>
	.content {
		display: grid;
		gap: 8px;
	}
	.content :global(h2) {
		font-size: 1rem;
	}
</style>
