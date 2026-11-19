<!--
  Snow by elevation: the snow stations around the location drawn as a profile (how deep
  the snow is at each height, with this location's elevations across it), and every
  station in a table underneath, highest first. Read from the same hourly file as the
  map's stations layer.
-->
<script lang="ts">
	import { hscroll } from '../hscroll';
	import { safeHref } from '../links';
	import type { LoadState } from '../load';
	import type { BandOut, NearbyOut } from '../types.gen';
	import { ago } from '../time';
	import { elevation, snow, type UnitSystem } from '../units';
	import ElevationProfile from './ElevationProfile.svelte';

	interface Props {
		data: NearbyOut | null;
		load?: LoadState;
		bands: BandOut[];
		/** The location's own station (its id), marked in the list. */
		own?: string | null;
		units: UnitSystem;
		/** Fixed chart width (tests); otherwise the chart measures its container. */
		width?: number;
	}

	let { data, load = 'ready', bands, own = null, units, width }: Props = $props();

	const stations = $derived(data?.stations ?? []);
	// Highest first; a station with no elevation on record goes last.
	const rows = $derived(
		[...stations].sort((a, b) => (b.station.elev_m ?? -Infinity) - (a.station.elev_m ?? -Infinity))
	);
	const charted = $derived(
		stations.filter((s) => s.station.elev_m !== null && s.station.depth_cm !== null).length
	);
	const deepest = $derived(Math.max(1, ...stations.map((s) => s.station.depth_cm ?? 0)));
	const away = (km: number) =>
		units === 'imperial' ? `${(km * 0.621371).toFixed(0)} mi` : `${km.toFixed(0)} km`;
	const radius = $derived(data ? away(data.radius_km) : '');
	const signed = (cm: number | null | undefined) =>
		cm === null || cm === undefined ? '–' : `${cm > 0 ? '+' : ''}${snow(cm, units)}`;
</script>

<section class="card" aria-labelledby="near-h">
	<h2 id="near-h">Snow by elevation</h2>
	{#if load === 'loading'}
		<p class="muted small" aria-live="polite">Loading nearby stations…</p>
	{:else if load === 'error'}
		<p class="muted small" role="alert">Couldn’t load nearby stations. Try again in a moment.</p>
	{:else if !data || !data.stations_at}
		<p class="muted small">Stations arrive with the worker’s next hourly check.</p>
	{:else if !stations.length}
		<p class="muted small">No snow station is reporting within {radius}.</p>
	{:else}
		<p class="muted small sub">
			Snow stations within {radius}, checked {ago(data.stations_at)}.
		</p>
		{#if charted}
			<ElevationProfile {stations} {bands} {own} {units} {width} />
		{/if}
		<details class="how list" open={!charted}>
			<summary>All {stations.length} station{stations.length === 1 ? '' : 's'}</summary>
			<div class="table-wrap" use:hscroll>
				<table class="data near">
					<thead>
						<tr>
							<th>Station</th>
							<th>Elevation</th>
							<th class="away">Away</th>
							<th class="depth">Snow depth</th>
							<th>24 h</th>
						</tr>
					</thead>
					<tbody>
						{#each rows as r (r.station.id)}
							{@const st = r.station}
							<tr>
								<th scope="row">
									{#if safeHref(st.url)}
										<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
										<a href={safeHref(st.url)} target="_blank" rel="noopener noreferrer"
											>{st.name}</a
										>
									{:else}{st.name}{/if}
									{#if st.id === own}<span class="own">this location’s</span>{/if}
								</th>
								<td class="num">{elevation(st.elev_m, units)}</td>
								<td class="num away">{away(r.distance_km)}</td>
								<td class="depth">
									<span class="bar" aria-hidden="true"
										><i style:width="{(100 * (st.depth_cm ?? 0)) / deepest}%"></i></span
									>
									<span class="num">{snow(st.depth_cm, units)}</span>
								</td>
								<td class="num">{signed(st.change24_cm)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</details>
		<p class="faint small">
			SNOTEL and BC snow pillows, as they report. A 24-hour change includes settling, so it can be
			negative.
		</p>
	{/if}
</section>

<style>
	h2 {
		margin: 0 0 4px;
	}
	.small {
		font-size: 0.85rem;
	}
	.near th:first-child {
		font-weight: 500;
	}
	.near a {
		color: inherit;
	}
	.own {
		margin-left: 6px;
		padding: 1px 7px;
		border-radius: 999px;
		background: var(--accent-soft);
		color: var(--accent-ink);
		font-size: 0.7rem;
		font-weight: 600;
		white-space: nowrap;
	}
	.sub {
		margin: 0 0 10px;
	}
	.list {
		margin-top: 10px;
	}
	.depth {
		min-width: 150px;
	}
	.bar {
		display: inline-block;
		width: 70px;
		height: 8px;
		margin-right: 6px;
		border-radius: 4px;
		background: var(--surface-2);
		overflow: hidden;
		vertical-align: middle;
	}
	.bar i {
		display: block;
		height: 100%;
		border-radius: 4px;
		background: var(--snow);
	}
	/* Phones: the depth must be on screen without scrolling, so the distance and the
	   bars go, and a long station name wraps. */
	@media (max-width: 640px) {
		.away,
		.bar {
			display: none;
		}
		.depth {
			min-width: 0;
		}
		.near th:first-child {
			white-space: normal;
		}
		.own {
			display: inline-block;
			margin-left: 0;
		}
	}
</style>
