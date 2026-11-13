<!--
  Controls for the Recent satellite base, in one row: natural colour or snow vs cloud, a
  line saying what's on screen and how old it is, a stepper through the nearest
  location's views (first the stitched newest-clear view, then whole clear scenes, newest
  first), and an (i) for the longer story (how the view is made, a cloudy newest pass).
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
	let more = $state(false);

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
			<button
				aria-pressed={bands === 'snow'}
				aria-label="Snow vs cloud"
				title="Snow vs cloud"
				onclick={() => onbands('snow')}>Snow</button
			>
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
		<button
			class="i"
			class:alert={!!cloudyNote}
			aria-expanded={more}
			aria-label="About this view"
			title="About this view"
			onclick={() => (more = !more)}
		>
			<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
				><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></svg
			>
		</button>
	</div>
	{#if more}
		<p class="foot">{cloudyNote ? `${cloudyNote} ` : ''}{foot}</p>
	{/if}
</section>

<style>
	.sat {
		display: grid;
		gap: 6px;
		padding: 6px 6px 6px 6px;
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
		flex: none;
		display: flex;
	}
	.seg button {
		font-size: 0.78rem;
		padding: 3px 10px;
		flex: 0 0 auto;
	}
	.step {
		flex: none;
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
	/* One line: what's shown, cut short (the whole of it is in the (i)). */
	.main {
		flex: 1;
		height: 36px;
		display: flex;
		align-items: center;
		min-width: 0;
	}
	.note {
		margin: 0;
		padding: 0 2px;
		font-size: 0.8rem;
		line-height: 1.3;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.i {
		flex: none;
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
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
	/* The newest pass was cloudy: the (i) says so. */
	.i.alert {
		color: var(--warn-ink);
	}
	.i svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.note strong {
		color: var(--text);
		font-weight: 600;
	}
	.foot {
		margin: 0;
		padding: 0 6px 4px;
		font-size: 0.74rem;
		line-height: 1.35;
		color: var(--text-2);
	}
</style>
