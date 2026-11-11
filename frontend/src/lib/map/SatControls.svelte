<!--
  Controls for the Recent satellite base: which Sentinel-2 scene of the nearest location
  is shown (newest first, step to older ones), natural colour or snow vs cloud, and a
  line saying what's on screen and how old it is.
-->
<script lang="ts">
	import type { SatLocation, SatOut } from '../types.gen';
	import type { SatBands } from '../prefs.svelte';
	import { dayLabel, S2_MIN_ZOOM, sceneLabel } from './sat';

	interface Props {
		data: SatOut | null;
		loadState: 'idle' | 'loading' | 'ready' | 'failed';
		/** The location nearest the middle of the map, if one is close enough. */
		spot: SatLocation | null;
		/** Which of its scenes is shown (0: the newest). */
		index: number;
		bands: SatBands;
		zoom: number;
		now: number;
		onbands: (b: SatBands) => void;
	}

	let { data, loadState, spot, index = $bindable(), bands, zoom, now, onbands }: Props = $props();

	const scenes = $derived(spot?.scenes ?? []);
	const scene = $derived(scenes[Math.min(index, scenes.length - 1)] ?? null);
	const viirs = $derived(data?.viirs_date ? dayLabel(data.viirs_date) : null);
	const foot = $derived(
		[
			bands === 'snow' ? 'Snow shows cyan, cloud white.' : '',
			scene
				? `Sentinel-2 10 m${scene.hls && bands === 'natural' ? ' and HLS 30 m' : ''} from one pass;`
				: '',
			`NOAA-20 VIIRS daily${viirs ? `, ${viirs}` : ''}.`,
			spot
				? `Clear: at least ${data?.min_clear_pct ?? 70}% of an 8 km square round the location free of cloud.`
				: ''
		]
			.filter(Boolean)
			.join(' ')
	);
</script>

<section class="sat glass" aria-label="Recent satellite">
	<div class="row">
		<div class="seg" role="group" aria-label="Colours">
			<button aria-pressed={bands === 'natural'} onclick={() => onbands('natural')}>Natural</button>
			<button aria-pressed={bands === 'snow'} onclick={() => onbands('snow')}>Snow vs cloud</button>
		</div>
		{#if scenes.length > 1}
			<div class="step" role="group" aria-label="Scene">
				<button
					onclick={() => (index = Math.min(scenes.length - 1, index + 1))}
					disabled={index >= scenes.length - 1}
					aria-label="Older scene"
					title="Older scene">‹</button
				>
				<span class="num">{index + 1}/{scenes.length}</span>
				<button
					onclick={() => (index = Math.max(0, index - 1))}
					disabled={index <= 0}
					aria-label="Newer scene"
					title="Newer scene">›</button
				>
			</div>
		{/if}
	</div>
	<div class="main">
		{#if loadState === 'loading' && !data}
			<p class="note">Loading recent imagery…</p>
		{:else if !data}
			<p class="note">Recent imagery isn't available right now.</p>
		{:else if spot && scene}
			<p class="note" role="status">
				<strong>{sceneLabel(scene, now)}</strong>
				<span class="faint"
					>· {spot.name}{scene.snow_pct ? `, ${scene.snow_pct}% snow` : ''}{zoom < S2_MIN_ZOOM
						? '. Zoom in for 10 m detail'
						: ''}</span
				>
			</p>
		{:else if spot}
			<p class="note">
				No clear Sentinel-2 view of {spot.name} in the last {data.days ?? 30} days{viirs
					? `; showing the daily mosaic from ${viirs}`
					: ''}.
			</p>
		{:else}
			<p class="note">
				{viirs ? `Daily mosaic from ${viirs} (375 m). ` : ''}10 m Sentinel-2 views are kept near
				saved locations.
			</p>
		{/if}
	</div>
	<p class="foot faint">{foot}</p>
</section>

<style>
	.sat {
		display: grid;
		gap: 6px;
		padding: 8px 12px 8px 8px;
		border-radius: 18px;
		font-size: 0.85rem;
		color: var(--text);
		background: color-mix(in srgb, var(--surface) 90%, transparent);
	}
	.row {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}
	.seg {
		display: flex;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.seg button {
		font-size: 0.78rem;
		padding: 3px 10px;
		flex: 0 0 auto;
	}
	.step {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 2px;
		font-size: 0.78rem;
		font-variant-numeric: tabular-nums;
	}
	.step button {
		min-width: 32px;
		min-height: 32px;
		border: 0;
		border-radius: 999px;
		background: var(--surface-2);
		color: var(--text);
		font-size: 1.05rem;
		line-height: 1;
		cursor: pointer;
	}
	.step button:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.num {
		padding: 0 4px;
		color: var(--text-2);
	}
	.main {
		min-height: 36px;
		display: flex;
		align-items: center;
		min-width: 0;
	}
	.note {
		margin: 0;
		padding: 0 4px;
		font-size: 0.8rem;
		line-height: 1.3;
		color: var(--text-2);
	}
	.note strong {
		color: var(--text);
		font-weight: 600;
	}
	.foot {
		margin: 0;
		padding-left: 4px;
		font-size: 0.7rem;
		line-height: 1.3;
	}
</style>
