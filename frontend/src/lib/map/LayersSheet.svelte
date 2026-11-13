<!--
  What the map shows: a base map (and its hill shading), one weather layer, one terrain
  overlay, and the features drawn on top. One weather layer and one overlay at a time
  keeps the map readable and its memory bounded.

  Every choice is a tile of the same size in a well, the chosen one raised (colour only,
  so nothing moves); "None" comes first. Each section's (i) says, in one line, what the
  chosen option is; the long version is in the map's About panel. On desktop the sheet
  can be pinned open beside the map's buttons.
-->
<script lang="ts">
	import {
		prefs,
		type MapBase,
		type MapFeature,
		type MapOverlay,
		type MapWeather
	} from '../prefs.svelte';

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
		/** Desktop: the sheet can be pinned open. */
		pinnable?: boolean;
		pinned?: boolean;
		onpin?: () => void;
		onclose: () => void;
	}

	let {
		analysis,
		contours,
		offline,
		concern = false,
		ates = false,
		pinnable = false,
		pinned = false,
		onpin,
		onclose
	}: Props = $props();

	interface Choice<T> {
		id: T;
		label: string;
		/** The full name, for screen readers, when the label is short. */
		name?: string;
		/** One line on what it is, for the section's (i). */
		about: string;
		disabled?: boolean;
		why?: string;
		beta?: boolean;
	}

	const BASES = $derived<Choice<MapBase>[]>([
		{ id: 'topo', label: 'Topo', about: 'Topographic map: OpenTopoMap up close.' },
		{
			id: 'satellite',
			label: 'Satellite',
			about: 'Detailed imagery, of no particular date (Esri).',
			disabled: offline,
			why: 'Needs a connection'
		},
		{
			id: 'recent',
			label: 'Recent',
			name: 'Recent satellite',
			about:
				'This week’s imagery: the newest clear 10 m Sentinel-2 view near saved locations, daily 375 m VIIRS elsewhere.',
			disabled: offline,
			why: 'Needs a connection'
		}
	]);
	const WEATHER: Choice<MapWeather>[] = [
		{ id: 'off', label: 'None', about: 'No weather layer.' },
		{
			id: 'radar',
			label: 'Radar',
			name: 'Radar & forecast',
			about: 'Radar for the last three hours, then the forecast hour by hour.'
		},
		{
			id: 'totals',
			label: 'Snow total',
			about: 'Forecast snow, with the ratio from the forecast temperature.'
		},
		{ id: 'snowlevel', label: 'Snow level', about: 'Forecast snow level, to about 3½ days.' },
		{ id: 'wind', label: 'Wind', about: 'Forecast wind, to about 3½ days.' },
		{
			id: 'depth',
			label: 'Depth',
			name: 'Snow depth',
			about: 'Snow on the ground: the latest daily analysis.'
		},
		{
			id: 'snowfall',
			label: 'Observed',
			name: 'Observed snow',
			about: 'Snow that fell, analysed from reports and radar (the US only).'
		},
		{ id: 'clouds', label: 'Clouds', about: 'Satellite clouds, the last three hours (GOES-West).' }
	];
	const OVERLAYS = $derived<Choice<MapOverlay>[]>(
		(
			[
				{ id: 'none', label: 'None', about: 'No terrain overlay.' },
				{
					id: 'slope',
					label: 'Slope',
					about: 'Slope angle from about 10 m terrain, once zoomed in.',
					worker: true
				},
				{ id: 'aspect', label: 'Aspect', about: 'The way each slope faces.', worker: true },
				{ id: 'bands', label: 'Elevation', name: 'Elevation bands', about: 'Elevation in bands.' },
				{
					id: 'sun',
					label: 'Sun',
					name: 'Sun & shade',
					about: 'Direct sun and terrain shade through the day: an estimate.',
					worker: true
				},
				{
					id: 'wind',
					label: 'Wind',
					name: 'Wind effect',
					about: 'Slopes the forecast wind loads or strips, from the shape of the ground.',
					worker: true
				},
				{
					id: 'problems',
					label: 'Avalanche',
					name: 'Avalanche problems',
					about: 'The terrain today’s avalanche problems describe.',
					worker: true
				},
				...(concern
					? [
							{
								id: 'concern' as const,
								label: 'Concern',
								name: 'Concern index (experimental)',
								about: 'This app’s experimental concern index: not a forecast.',
								worker: true,
								beta: true
							}
						]
					: [])
			] as (Choice<MapOverlay> & { worker?: boolean })[]
		).map(({ worker, ...c }) => ({
			...c,
			disabled: worker && !analysis,
			why: worker && !analysis ? 'Needs a newer browser' : undefined
		}))
	);
	const FEATURES = $derived<Choice<MapFeature>[]>([
		{
			id: 'runs',
			label: 'Runs',
			name: 'Ski runs and routes',
			about: 'Ski runs and routes, from zoom 11.'
		},
		{ id: 'peaks', label: 'Peaks', about: 'Named peaks.' },
		{
			id: 'places',
			label: 'Huts & passes',
			name: 'Huts, trailheads, passes',
			about: 'Huts, trailheads and passes, from zoom 10.'
		},
		{
			id: 'glaciers',
			label: 'Glaciers',
			name: 'Glaciers and cliffs',
			about: 'Glaciers and cliffs.'
		},
		{
			id: 'stations',
			label: 'Stations',
			name: 'Snow stations',
			about: 'Snow stations: depth and new snow, hourly.'
		},
		{
			id: 'zones',
			label: 'Avy zones',
			name: 'Avalanche danger zones',
			about: 'Colour when zoomed out; outline up close.'
		},
		{
			id: 'obs',
			label: 'Reports',
			name: 'Field reports',
			about: 'Field reports: Canada (MIN), the last 2 weeks.'
		},
		...(ates
			? [
					{
						id: 'ates' as const,
						label: 'ATES',
						name: 'ATES terrain ratings',
						about: 'ATES terrain ratings (Avalanche Canada).'
					}
				]
			: []),
		{
			id: 'contours',
			label: 'Contours',
			about: 'Contours over imagery; the topo map draws its own.',
			disabled: !contours,
			why: 'Contours couldn’t load'
		}
	]);
	const SHADES = ['off', 'light', 'strong'] as const;

	/** Which sections' (i) lines are open. */
	let info = $state<Record<string, boolean>>({});
	const flip = (k: string) => (info = { ...info, [k]: !info[k] });
	const aboutOf = <T,>(list: Choice<T>[], id: T) => list.find((c) => c.id === id)?.about ?? '';
	const shownFeatures = $derived(
		FEATURES.filter((f) => prefs.mapFeatures.has(f.id))
			.map((f) => f.about)
			.join(' ')
	);
</script>

{#snippet infoButton(key: string, name: string)}
	<button
		class="i"
		aria-expanded={!!info[key]}
		aria-label="About {name}"
		title="About {name}"
		onclick={() => flip(key)}
	>
		<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
			><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></svg
		>
	</button>
{/snippet}

{#snippet tileButton(
	label: string,
	pressed: boolean,
	on: () => void,
	c: Choice<unknown>,
	tick = false
)}
	<button
		aria-pressed={pressed}
		aria-label={c.name ?? label}
		disabled={c.disabled}
		title={c.disabled ? c.why : c.about}
		onclick={on}
	>
		{#if tick}<i class="tick" aria-hidden="true"></i>{/if}<span>{label}</span>{#if c.beta}<b
				class="beta"
				aria-hidden="true">beta</b
			>{/if}
	</button>
{/snippet}

<div class="sheet" class:pinned role="dialog" aria-label="Map layers" id="map-layers">
	<header>
		<div class="names">
			<span class="eyebrow">Map</span>
			<strong class="title">Layers</strong>
		</div>
		{#if pinnable}
			<button
				class="hbtn"
				aria-pressed={pinned}
				aria-label={pinned ? 'Unpin layers' : 'Pin layers open'}
				title={pinned ? 'Unpin: close with a tap on the map' : 'Keep open beside the map'}
				onclick={() => onpin?.()}
			>
				<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
					><path d="M9 4h6l-1 6 3 3H7l3-3-1-6zM12 13v7" /></svg
				>
			</button>
		{/if}
		<button class="hbtn" onclick={onclose} aria-label="Close">✕</button>
	</header>

	<div class="body">
		<section aria-label="Base map">
			<div class="shead">
				<h4 class="eyebrow">Base map</h4>
				{@render infoButton('base', 'base maps')}
				<div class="seg shade" role="group" aria-label="Hill shading">
					{#each SHADES as s (s)}
						<button
							aria-pressed={prefs.mapShade === s}
							title="Hill shading: {s}"
							onclick={() => prefs.setMapShade(s)}
							>{s === 'off' ? 'Flat' : s[0].toUpperCase() + s.slice(1)}</button
						>
					{/each}
				</div>
			</div>
			<div class="mp-tiles" style:--cols="3" role="group" aria-label="Base map">
				{#each BASES as b (b.id)}
					{@render tileButton(b.label, prefs.mapBase === b.id, () => prefs.setMapBase(b.id), b)}
				{/each}
			</div>
			{#if info.base}
				<p class="about">
					{aboutOf(BASES, prefs.mapBase)} Hill shading (Flat, Light, Strong) draws the terrain's relief.
				</p>
			{/if}
		</section>

		<section aria-label="Weather">
			<div class="shead">
				<h4 class="eyebrow">Weather</h4>
				{@render infoButton('weather', 'the weather layers')}
			</div>
			<div class="mp-tiles" role="group" aria-label="Weather">
				{#each WEATHER as w (w.id)}
					{@render tileButton(
						w.label,
						prefs.mapWeather === w.id,
						() => prefs.setMapWeather(w.id),
						w
					)}
				{/each}
			</div>
			{#if info.weather}
				<p class="about">{aboutOf(WEATHER, prefs.mapWeather)} One at a time.</p>
			{/if}
		</section>

		<section aria-label="Terrain">
			<div class="shead">
				<h4 class="eyebrow">Terrain</h4>
				{@render infoButton('terrain', 'the terrain overlays')}
			</div>
			<div class="mp-tiles" role="group" aria-label="Terrain overlay">
				{#each OVERLAYS as o (o.id)}
					{@render tileButton(
						o.label,
						prefs.mapOverlay === o.id,
						() => prefs.setMapOverlay(o.id),
						o
					)}
				{/each}
			</div>
			{#if info.terrain}
				<p class="about">
					{aboutOf(OVERLAYS, prefs.mapOverlay)} Worked out on this device; tap the map for the numbers.
				</p>
			{/if}
		</section>

		<section aria-label="Show">
			<div class="shead">
				<h4 class="eyebrow">Show</h4>
				{@render infoButton('show', 'what’s shown')}
			</div>
			<div class="mp-tiles" style:--cols="3" role="group" aria-label="Show on the map">
				{#each FEATURES as f (f.id)}
					{@render tileButton(
						f.label,
						prefs.mapFeatures.has(f.id),
						() => prefs.setMapFeature(f.id, !prefs.mapFeatures.has(f.id)),
						f,
						true
					)}
				{/each}
			</div>
			{#if info.show}
				<p class="about">{shownFeatures || 'Nothing extra is shown.'}</p>
			{/if}
		</section>
	</div>
</div>

<style>
	/* Desktop: beside the map's buttons, the same panel as the tap panel's. */
	.sheet {
		position: absolute;
		top: 10px;
		left: calc(var(--map-inset, 0px) + 60px);
		transition: left 320ms cubic-bezier(0.2, 0.8, 0.2, 1);
		width: 368px;
		max-height: calc(100% - 20px);
		z-index: 1002;
		display: flex;
		flex-direction: column;
		border-radius: 16px;
		border: 1px solid var(--glass-border);
		background: color-mix(in srgb, var(--surface) 94%, transparent);
		box-shadow: var(--glass-shadow);
		backdrop-filter: var(--blur-glass);
		-webkit-backdrop-filter: var(--blur-glass);
		color: var(--text);
		font-size: 0.85rem;
		overflow: hidden;
	}
	header {
		flex: none;
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 10px 8px 8px 14px;
		border-bottom: 1px solid var(--border);
	}
	.names {
		flex: 1;
		min-width: 0;
		display: grid;
		gap: 1px;
	}
	.names .eyebrow {
		font-size: 0.66rem;
	}
	.title {
		font-family: var(--font-num);
		font-size: 1.08rem;
		font-weight: 700;
		letter-spacing: -0.01em;
	}
	.hbtn {
		flex: none;
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		border: 0;
		border-radius: 10px;
		background: transparent;
		color: var(--text-2);
		font-size: 0.9rem;
		cursor: pointer;
	}
	.hbtn:hover {
		background: var(--hover);
	}
	.hbtn[aria-pressed='true'] {
		background: var(--accent-soft);
		color: var(--accent-ink);
	}
	.hbtn svg,
	.i svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.body {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		overscroll-behavior: contain;
		padding: 10px 12px 12px;
		display: grid;
		align-content: start;
		gap: 12px;
	}
	section {
		display: grid;
		gap: 6px;
	}
	.shead {
		display: flex;
		align-items: center;
		gap: 2px;
		min-height: 24px;
	}
	h4 {
		margin: 0 0 0 2px;
	}
	.i {
		display: grid;
		place-items: center;
		width: 24px;
		height: 24px;
		border: 0;
		border-radius: 999px;
		background: transparent;
		color: var(--text-3);
		cursor: pointer;
	}
	.i:hover,
	.i[aria-expanded='true'] {
		color: var(--accent-ink);
		background: var(--accent-soft);
	}
	.shade {
		margin-left: auto;
		padding: 2px;
	}
	.shade button {
		font-size: 0.72rem;
		padding: 2px 8px;
	}
	.about {
		margin: 0 2px;
		font-size: 0.75rem;
		line-height: 1.35;
		color: var(--text-2);
	}
	/* In the tile's corner, so the label keeps its room. */
	.body :global(.mp-tiles button:has(.beta)) {
		position: relative;
	}
	.beta {
		position: absolute;
		top: 2px;
		right: 3px;
		font-size: 0.5rem;
		line-height: 1.2;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		padding: 0 3px;
		border-radius: 4px;
		background: var(--accent-soft);
		color: var(--accent-ink);
	}

	/* Phones and tablets: a sheet over the foot of the map, above the tab bar, sized to
	   fit everything without scrolling on a small phone. */
	@media (max-width: 1099px) {
		.sheet {
			top: auto;
			left: 8px;
			right: 8px;
			bottom: calc(84px + env(safe-area-inset-bottom));
			width: auto;
			max-width: 560px;
			margin: 0 auto;
			max-height: calc(100% - 84px - env(safe-area-inset-bottom) - 10px);
			border-radius: 18px;
		}
		header {
			padding-top: 8px;
			padding-bottom: 6px;
		}
		.body {
			gap: 10px;
			padding-top: 8px;
		}
		.body :global(.mp-tiles button) {
			height: 34px;
			font-size: 0.78rem;
		}
		.body :global(.mp-tiles button > span) {
			font-size: 0.76rem;
		}
	}
	/* The narrowest phones: three across, so every word fits its tile. */
	@media (max-width: 359px) {
		.body :global(.mp-tiles) {
			--cols: 3 !important;
		}
	}
</style>
