<!--
  Controls for the Recent satellite base: which view of the nearest location is shown
  (first the stitched newest-clear view, then whole clear scenes, newest first), natural
  colour or snow vs cloud, and a line saying what's on screen and how old it is.
-->
<script lang="ts">
	import type { SatLocation, SatOut } from '../types.gen';
	import type { SatBands } from '../prefs.svelte';
	import { ago, dayLabel, S2_MIN_ZOOM, satViews, sceneLabel, shortDate, stitchedSpan } from './sat';

	interface Props {
		data: SatOut | null;
		loadState: 'idle' | 'loading' | 'ready' | 'failed';
		/** The location nearest the middle of the map, if one is close enough. */
		spot: SatLocation | null;
		/** Which of its views is shown (0: stitched, when there is one). */
		index: number;
		bands: SatBands;
		zoom: number;
		now: number;
		onbands: (b: SatBands) => void;
	}

	let { data, loadState, spot, index = $bindable(), bands, zoom, now, onbands }: Props = $props();

	const views = $derived(satViews(spot));
	const view = $derived(views[Math.min(index, views.length - 1)] ?? null);
	const scene = $derived(view?.kind === 'scene' ? view.scene : null);
	const stitched = $derived(view?.kind === 'stitched' ? view.composite : null);
	const viirs = $derived(data?.viirs_date ? dayLabel(data.viirs_date) : null);
	const zoomIn = $derived(zoom < S2_MIN_ZOOM ? '. Zoom in for 10 m detail' : '');
	/** The newest pass was cloudy where the location is: say so, with its date. */
	const cloudyNote = $derived(
		stitched?.latest_pass &&
			(!stitched.at_location ||
				stitched.latest_pass.slice(0, 10) > stitched.at_location.slice(0, 10))
			? `The newest pass, ${shortDate(stitched.latest_pass)}, was cloudy there.`
			: ''
	);
	const foot = $derived(
		[
			bands === 'snow' ? 'Snow shows cyan, cloud white.' : '',
			stitched
				? 'Each outlined part is the newest Sentinel-2 pass (10 m) that saw the ground there; small cloud gaps are filled from the next newest.'
				: scene
					? `One Sentinel-2 pass (10 m) over the whole 24 km area, at least ${data?.min_clear_pct ?? 85}% of it clear.`
					: '',
			`NOAA-20 VIIRS daily${viirs ? `, ${viirs}` : ''}${spot ? ' beyond the area and where no pass was clear' : ''}.`
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
		{#if views.length > 1}
			<div class="step" role="group" aria-label="View">
				<button
					onclick={() => (index = Math.min(views.length - 1, index + 1))}
					disabled={index >= views.length - 1}
					aria-label="Older view"
					title="Older view">‹</button
				>
				<span class="num">{index + 1}/{views.length}</span>
				<button
					onclick={() => (index = Math.max(0, index - 1))}
					disabled={index <= 0}
					aria-label="Newer view"
					title="Newer view">›</button
				>
			</div>
		{/if}
	</div>
	<div class="main">
		{#if loadState === 'loading' && !data}
			<p class="note">Loading recent imagery…</p>
		{:else if !data}
			<p class="note">Recent imagery isn't available right now.</p>
		{:else if spot && stitched}
			<p class="note" role="status">
				<strong
					>Newest clear view · {stitched.layers.length === 1
						? '1 pass'
						: `${stitched.layers.length} passes`}, {stitchedSpan(stitched)}</strong
				>
				<span class="faint"
					>· {spot.name}: {stitched.at_location
						? `seen ${shortDate(stitched.at_location)}, ${ago(stitched.at_location, now)}`
						: 'its own spot is in a gap, under cloud in every pass'}{zoomIn}</span
				>
			</p>
		{:else if spot && scene}
			<p class="note" role="status">
				<strong>{sceneLabel(scene, now)}</strong>
				<span class="faint"
					>· {spot.name}{scene.snow_pct ? `, ${scene.snow_pct}% snow` : ''}{zoomIn}</span
				>
			</p>
		{:else if spot}
			<p class="note">
				No clear Sentinel-2 view of {spot.name} in the last {data.scene_days ?? 60} days{viirs
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
	<p class="foot faint">{cloudyNote ? `${cloudyNote} ` : ''}{foot}</p>
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
