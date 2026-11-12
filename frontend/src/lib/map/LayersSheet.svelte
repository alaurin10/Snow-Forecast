<!--
  What the map shows: a base map, one weather layer, one terrain overlay, and the
  features drawn on top. One weather layer and one overlay at a time keeps the map
  readable and its memory bounded.
-->
<script lang="ts">
	import {
		prefs,
		type MapBase,
		type MapFeature,
		type MapOverlay,
		type MapWeather
	} from '../prefs.svelte';
	import { WEATHER_CHOICES } from './weather';

	interface Props {
		/** Slope and aspect need the terrain worker (missing on old browsers). */
		analysis: boolean;
		/** Contours come from maplibre-contour, which may have failed to load. */
		contours: boolean;
		offline: boolean;
		/** The server offers the experimental concern index (HAZARD_INDEX isn't off). */
		concern?: boolean;
		/** The owner has supplied ATES ratings. */
		ates?: boolean;
		onclose: () => void;
	}

	let { analysis, contours, offline, concern = false, ates = false, onclose }: Props = $props();

	const BASES: { id: MapBase; label: string; title: string }[] = [
		{ id: 'topo', label: 'Topo', title: 'Topographic map' },
		{
			id: 'satellite',
			label: 'Satellite',
			title: 'Detailed imagery, of no particular date (Esri)'
		},
		{
			id: 'recent',
			label: 'Recent satellite',
			title: 'This week’s imagery: Sentinel-2 near saved locations, daily VIIRS elsewhere'
		}
	];
	const WEATHER: { id: MapWeather; label: string }[] = [
		...WEATHER_CHOICES,
		{ id: 'off', label: 'None' }
	];
	const OVERLAYS = $derived<{ id: MapOverlay; label: string; worker?: boolean }[]>([
		{ id: 'none', label: 'None' },
		{ id: 'slope', label: 'Slope', worker: true },
		{ id: 'aspect', label: 'Aspect', worker: true },
		{ id: 'bands', label: 'Elevation' },
		{ id: 'sun', label: 'Sun & shade', worker: true },
		{ id: 'wind', label: 'Wind effect', worker: true },
		{ id: 'problems', label: 'Avalanche problems', worker: true },
		...(concern
			? [{ id: 'concern' as const, label: 'Concern index (experimental)', worker: true }]
			: [])
	]);
	const FEATURES = $derived<{ id: MapFeature; label: string; hint?: string; off?: boolean }[]>([
		{ id: 'runs', label: 'Ski runs and routes', hint: 'From zoom 11' },
		{ id: 'peaks', label: 'Peaks' },
		{ id: 'places', label: 'Huts, trailheads, passes', hint: 'From zoom 10' },
		{ id: 'glaciers', label: 'Glaciers and cliffs' },
		{ id: 'stations', label: 'Snow stations', hint: 'Depth and new snow, hourly' },
		{ id: 'zones', label: 'Avalanche danger zones', hint: 'Today, as published' },
		{ id: 'obs', label: 'Field reports', hint: 'Canada (MIN), last 2 weeks' },
		...(ates
			? [{ id: 'ates' as const, label: 'ATES terrain ratings', hint: 'From Avalanche Canada' }]
			: []),
		{
			id: 'contours',
			label: 'Contours',
			hint: 'On satellite; the topo map has its own',
			off: !contours
		}
	]);
</script>

<div class="sheet" role="dialog" aria-label="Map layers" id="map-layers">
	<section>
		<h4>Base map</h4>
		<div class="seg" role="group" aria-label="Base map">
			{#each BASES as b (b.id)}
				<button
					aria-pressed={prefs.mapBase === b.id}
					onclick={() => prefs.setMapBase(b.id)}
					disabled={b.id !== 'topo' && offline}
					title={b.id !== 'topo' && offline ? 'Satellite needs a connection' : b.title}
					>{b.label}</button
				>
			{/each}
		</div>
		{#if prefs.mapBase === 'recent'}
			<p class="faint">
				Daily 375 m views everywhere; near saved locations, the newest 10 m Sentinel-2 view that
				sees the ground, a few days old at most in clear weather.
			</p>
		{/if}
	</section>

	<section>
		<h4>Weather</h4>
		<div class="seg" role="group" aria-label="Weather">
			{#each WEATHER as w (w.id)}
				<button aria-pressed={prefs.mapWeather === w.id} onclick={() => prefs.setMapWeather(w.id)}
					>{w.label}</button
				>
			{/each}
		</div>
		<p class="faint">
			One at a time. Snow level and wind are forecasts to about 3½ days; snow depth and observed
			snow are the latest analyses (observed snow: the US only); clouds are the last three hours
			from GOES-West.
		</p>
	</section>

	<section>
		<h4>Terrain</h4>
		<div class="seg" role="group" aria-label="Terrain overlay">
			{#each OVERLAYS as o (o.id)}
				<button
					aria-pressed={prefs.mapOverlay === o.id}
					disabled={o.worker && !analysis}
					title={o.worker && !analysis ? 'Needs a newer browser' : undefined}
					onclick={() => prefs.setMapOverlay(o.id)}>{o.label}</button
				>
			{/each}
		</div>
		<p class="faint">
			Worked out on this device from about 10 m terrain, once zoomed in. Sun & shade and Wind effect
			are estimates from the shape of the ground. Avalanche problems shows the terrain today's
			bulletin describes{concern
				? '; the concern index is the app’s own experimental estimate, not a forecast'
				: ''}. Tap the map for numbers.
		</p>
	</section>

	<section>
		<h4>Show</h4>
		<div class="checks">
			{#each FEATURES as f (f.id)}
				<label class:off={f.off}>
					<input
						type="checkbox"
						checked={prefs.mapFeatures.has(f.id)}
						disabled={f.off}
						onchange={(e) => prefs.setMapFeature(f.id, e.currentTarget.checked)}
					/>
					<span>{f.label}</span>
					{#if f.hint}<small class="faint">{f.hint}</small>{/if}
				</label>
			{/each}
		</div>
		<div class="shade">
			<span>Hill shading</span>
			<div class="seg" role="group" aria-label="Hill shading">
				{#each ['off', 'light', 'strong'] as const as s (s)}
					<button aria-pressed={prefs.mapShade === s} onclick={() => prefs.setMapShade(s)}
						>{s[0].toUpperCase() + s.slice(1)}</button
					>
				{/each}
			</div>
		</div>
	</section>

	<button class="close" onclick={onclose}>Done</button>
</div>

<style>
	.sheet {
		position: absolute;
		top: 136px;
		left: calc(var(--map-inset, 0px) + 60px);
		right: 10px;
		max-width: 380px;
		max-height: calc(100% - 150px);
		overflow-y: auto;
		z-index: 1002;
		padding: 12px 14px;
		border-radius: 14px;
		background: var(--surface);
		border: 1px solid var(--border);
		box-shadow: var(--glass-shadow);
		font-size: 0.85rem;
		color: var(--text);
		display: grid;
		gap: 12px;
	}
	section {
		display: grid;
		gap: 6px;
	}
	h4 {
		margin: 0;
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--text-2);
	}
	.seg {
		justify-self: start;
		display: flex;
		flex-wrap: wrap;
	}
	.seg button {
		font-size: 0.8rem;
		padding: 5px 11px;
		min-height: 32px;
	}
	.seg button:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	p {
		margin: 0;
		font-size: 0.75rem;
	}
	.checks {
		display: grid;
		gap: 2px;
	}
	label {
		display: flex;
		align-items: center;
		gap: 8px;
		min-height: 32px;
		cursor: pointer;
	}
	label.off {
		opacity: 0.5;
	}
	input[type='checkbox'] {
		width: 18px;
		height: 18px;
		accent-color: var(--accent);
	}
	small {
		font-size: 0.72rem;
		margin-left: auto;
		text-align: right;
	}
	.shade {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		flex-wrap: wrap;
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
			max-height: calc(100% - 136px - 94px - env(safe-area-inset-bottom));
		}
	}
</style>
