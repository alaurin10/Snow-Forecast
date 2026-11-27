<!--
  The Observed tab: what was actually measured. At the top, the simple answers: what the
  location's snow station says (how much fell, how deep it is, the last seven days) and
  whether the forecast got it right. Then, in detail: the station's last 30 days, the
  forecast checked day by day, snow by elevation across the stations nearby, and (in
  Canada) recent field reports.
-->
<script lang="ts">
	import type { LoadState } from '../load';
	import type { NearbyOut, Snapshot, VerificationOut } from '../types.gen';
	import type { UnitSystem } from '../units';
	import { dateOf } from '../time';
	import { stationRead } from './read';
	import StationHero from './StationHero.svelte';
	import ForecastVerdict from './ForecastVerdict.svelte';
	import SnowpackDetail from './SnowpackDetail.svelte';
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
		/** A spot (a point tapped on the map): it never has a snow station of its own. */
		spot?: boolean;
		width?: number;
	}

	let {
		snap,
		scores,
		scoresLoad = 'ready',
		nearby,
		nearbyLoad = 'ready',
		units,
		spot = false,
		width
	}: Props = $props();
	const station = $derived(snap.snotel ?? null);
	const read = $derived(station ? stationRead(station, units) : null);
	// Avalanche Canada's reports cover Canada: elsewhere the card shows only when one is close.
	const showReports = $derived(
		!!nearby &&
			(nearby.reports.length > 0 || (snap.location.country === 'CA' && !!nearby.reports_at))
	);
</script>

{#snippet near()}
	<NearbyStations
		data={nearby}
		load={nearbyLoad}
		bands={snap.bands}
		own={station?.triplet ?? null}
		{units}
		{width}
	/>
{/snippet}

<div class="stackcol">
	{#if station && read}
		<div class="summary">
			<StationHero
				{station}
				{read}
				bandLabel={snap.bands[1].label}
				bandElev={snap.bands[1].elev_m}
				today={dateOf(snap.now)}
				{units}
			/>
			<ForecastVerdict data={scores} {units} load={scoresLoad} />
		</div>

		<h2 class="divider"><span>In detail</span></h2>
		<SnowpackDetail {read} {units} {width} />
		<MeasuredVsForecast data={scores} {units} load={scoresLoad} {width} />
		{@render near()}
	{:else}
		<section class="card">
			<h2>No snow station here</h2>
			{#if spot}
				<p class="muted small">
					A forecast made for a point on the map has no snow station of its own. The stations
					nearby:
				</p>
			{:else}
				<p class="muted small">
					No snow station is set for this location, so there’s nothing measured right here. The
					owner can pick one on the Manage page. Meanwhile, the stations nearby:
				</p>
			{/if}
		</section>
		{@render near()}
	{/if}
	{#if showReports && nearby}
		<FieldReports data={nearby} {units} />
	{/if}
</div>

<style>
	.stackcol {
		display: grid;
		gap: 16px;
	}
	.summary {
		display: grid;
		gap: 16px;
		align-items: start;
	}
	@media (min-width: 1080px) {
		.summary {
			grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
		}
	}
	.small {
		font-size: 0.85rem;
	}
	.divider {
		display: flex;
		align-items: center;
		gap: 12px;
		margin: 10px 4px 0;
		font-size: 0.75rem;
		font-weight: 650;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-2);
	}
	.divider::before,
	.divider::after {
		content: '';
		flex: 1;
		height: 1px;
		background: var(--border);
	}
	@media (max-width: 640px) {
		.stackcol,
		.summary {
			gap: 12px;
		}
	}
</style>
