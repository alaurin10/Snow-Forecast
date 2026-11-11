<!--
  The key for the terrain overlay on the map: slope classes, aspect colours or elevation
  bands. (Sun & shade and Wind effect carry their keys in their controls.)
-->
<script lang="ts">
	import type { UnitSystem } from '../units';
	import type { MapOverlay } from '../prefs.svelte';
	import { ASPECT_COLORS, SECTORS, SLOPE_CLASSES } from './terrain/analysis';
	import { elevationBands } from './style';

	interface Props {
		overlay: MapOverlay;
		units: UnitSystem;
		zoom: number;
	}

	let { overlay, units, zoom }: Props = $props();
	const bands = $derived(elevationBands(units).bands.slice().reverse());
</script>

{#if overlay === 'slope' || overlay === 'aspect' || overlay === 'bands'}
	<div class="legend glass" role="note" aria-label="Terrain key">
		{#if overlay === 'slope'}
			<strong>Slope</strong>
			{#each SLOPE_CLASSES.slice().reverse() as c (c.from)}
				<span class="row"><i style:background={c.color}></i>{c.label}</span>
			{/each}
		{:else if overlay === 'aspect'}
			<strong>Faces</strong>
			<span class="rose" aria-hidden="true">
				{#each SECTORS as s, i (s)}
					<span class="petal" style:--a="{i * 45}deg" style:background={ASPECT_COLORS[s]}></span>
				{/each}
			</span>
			<span class="sectors">
				{#each SECTORS as s (s)}<span class="row"
						><i style:background={ASPECT_COLORS[s]}></i>{s}</span
					>{/each}
			</span>
		{:else}
			<strong>Elevation</strong>
			{#each bands as b (b.from)}
				<span class="row"><i style:background={b.color}></i>{b.label}</span>
			{/each}
		{/if}
		{#if overlay !== 'bands' && zoom < 8.5}
			<span class="hint faint">Zoom in to see it</span>
		{/if}
	</div>
{/if}

<style>
	.legend {
		position: absolute;
		top: 44px;
		right: 10px;
		z-index: 1000;
		display: grid;
		gap: 2px;
		padding: 8px 10px;
		border-radius: 12px;
		font-size: 0.72rem;
		color: var(--text);
		max-width: 132px;
	}
	strong {
		font-size: 0.72rem;
		margin-bottom: 2px;
	}
	.row {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		white-space: nowrap;
		font-variant-numeric: tabular-nums;
	}
	i {
		width: 12px;
		height: 10px;
		border-radius: 3px;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.12);
		flex-shrink: 0;
	}
	.sectors {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 2px 8px;
	}
	.rose {
		position: relative;
		width: 54px;
		height: 54px;
		margin: 2px auto 4px;
	}
	.petal {
		position: absolute;
		left: 50%;
		top: 0;
		width: 16px;
		height: 27px;
		margin-left: -8px;
		transform-origin: 50% 100%;
		transform: rotate(var(--a));
		clip-path: polygon(50% 100%, 0 0, 100% 0);
	}
	.hint {
		margin-top: 2px;
		white-space: normal;
	}
</style>
