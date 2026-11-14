<!--
  The Observed tab: what was actually measured. The location's own snow station, how
  the last month's snow compared with the forecast, the stations around it by
  elevation, and (in Canada) recent field reports.
-->
<script lang="ts">
	import type { LoadState } from '../load';
	import type { NearbyOut, Snapshot, VerificationOut } from '../types.gen';
	import type { UnitSystem } from '../units';
	import StationPanel from './StationPanel.svelte';
	import MeasuredVsForecast from './MeasuredVsForecast.svelte';
	import NearbyStations from './NearbyStations.svelte';
	import FieldReports from './FieldReports.svelte';

	interface Props {
		snap: Snapshot;
		scores: VerificationOut | null;
		scoresLoad?: LoadState;
		nearby: NearbyOut | null;
		nearbyLoad?: LoadState;
		units: UnitSystem;
		width?: number;
	}

	let {
		snap,
		scores,
		scoresLoad = 'ready',
		nearby,
		nearbyLoad = 'ready',
		units,
		width
	}: Props = $props();
	// Avalanche Canada's reports cover Canada: elsewhere the card shows only when one is close.
	const showReports = $derived(
		!!nearby &&
			(nearby.reports.length > 0 || (snap.location.country === 'CA' && !!nearby.reports_at))
	);
</script>

<div class="stackcol">
	<StationPanel
		station={snap.snotel ?? null}
		bandLabel={snap.bands[1].label}
		bandElev={snap.bands[1].elev_m}
		{units}
		{width}
	/>
	<MeasuredVsForecast data={scores} {units} load={scoresLoad} {width} />
	<NearbyStations
		data={nearby}
		load={nearbyLoad}
		bands={snap.bands}
		own={snap.snotel?.triplet ?? null}
		{units}
	/>
	{#if showReports && nearby}
		<FieldReports data={nearby} {units} />
	{/if}
</div>

<style>
	.stackcol {
		display: grid;
		gap: 16px;
	}
	@media (max-width: 640px) {
		.stackcol {
			gap: 12px;
		}
	}
</style>
