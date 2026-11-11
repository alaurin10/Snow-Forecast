<!--
  What the map shows: a base map, one weather layer, one terrain overlay, and the
  features drawn on top. One weather layer and one overlay at a time keeps the map
  readable and its memory bounded.
-->
<script lang="ts">
	import { prefs, type MapFeature, type MapOverlay, type MapWeather } from '../prefs.svelte';

	interface Props {
		/** Slope and aspect need the terrain worker (missing on old browsers). */
		analysis: boolean;
		/** Contours come from maplibre-contour, which may have failed to load. */
		contours: boolean;
		offline: boolean;
		onclose: () => void;
	}

	let { analysis, contours, offline, onclose }: Props = $props();

	const WEATHER: { id: MapWeather; label: string }[] = [
		{ id: 'radar', label: 'Radar & forecast' },
		{ id: 'totals', label: 'Snow total' },
		{ id: 'off', label: 'None' }
	];
	const OVERLAYS: { id: MapOverlay; label: string; worker?: boolean }[] = [
		{ id: 'none', label: 'None' },
		{ id: 'slope', label: 'Slope', worker: true },
		{ id: 'aspect', label: 'Aspect', worker: true },
		{ id: 'bands', label: 'Elevation' }
	];
	const FEATURES = $derived<{ id: MapFeature; label: string; hint?: string; off?: boolean }[]>([
		{ id: 'runs', label: 'Ski runs', hint: 'From zoom 11' },
		{ id: 'peaks', label: 'Peaks' },
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
			<button aria-pressed={prefs.mapBase === 'topo'} onclick={() => prefs.setMapBase('topo')}
				>Topo</button
			>
			<button
				aria-pressed={prefs.mapBase === 'satellite'}
				onclick={() => prefs.setMapBase('satellite')}
				disabled={offline}
				title={offline ? 'Satellite needs a connection' : undefined}>Satellite</button
			>
		</div>
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
			Slope and aspect from about 10 m terrain, from zoom 8. Tap the map for numbers.
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
		left: 60px;
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
</style>
