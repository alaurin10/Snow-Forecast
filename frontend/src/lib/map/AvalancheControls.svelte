<!--
  Controls for the two avalanche terrain layers, at the foot of the map.
  Avalanche problems: today's listed problems for the zone in the middle of the map, as
  the terrain they describe (their aspects and elevation bands, steeper than a chosen
  angle), with the treeline numbers used. Concern index: the app's own experimental
  estimate, with its fixed caption, its key and what went into it today.
-->
<script lang="ts">
	import type { ZoneFeature } from '../types.gen';
	import { elevation, type UnitSystem } from '../units';
	import { dangerWord } from '../conditions';
	import type { AreaState } from './layers/analysis';
	import { BAND_WORDS, DANGER_COLORS, todayRatings, zoneName, type Treeline } from './avalanche';
	import { MATCH_COLOR } from './terrain/analysis';
	import { BANDS, CONCERN_CLASSES } from './terrain/concern';

	interface Props {
		overlay: 'problems' | 'concern';
		units: UnitSystem;
		zonesState: 'idle' | 'loading' | 'ready' | 'failed';
		/** The zone in the middle of the map. */
		zone: ZoneFeature | null;
		treeline: Treeline | null;
		/** Zoomed out too far for the layer. */
		tooFar: boolean;
		state: AreaState;
		/** Which listed problem to show (an index), or all of them. */
		pick: number | 'all';
		slopeMin: number;
		/** Concern index: why it can't be drawn (null when it can), and how wind and sun count. */
		concernWhy?: string | null;
		windNote?: string;
		sunNote?: string;
		caption?: string;
		onzone?: () => void;
	}

	let {
		overlay,
		units,
		zonesState,
		zone,
		treeline,
		tooFar,
		state: work,
		pick = $bindable(),
		slopeMin = $bindable(),
		concernWhy = null,
		windNote = '',
		sunNote = '',
		caption = '',
		onzone
	}: Props = $props();

	const view = $derived(zone?.properties.view ?? null);
	const ratings = $derived(zone && view ? todayRatings(view, zone.properties.today) : null);
	const problems = $derived(ratings ? (view?.doc?.problems ?? []) : []);
	const name = $derived(zone ? zoneName(zone) : '');
	const tl = $derived(
		treeline
			? `Treeline taken as ${elevation(treeline.band[0], units)}–${elevation(treeline.band[1], units)}`
			: ''
	);
	/** Why the problems layer shows nothing, or null. */
	const problemsWhy = $derived.by(() => {
		if (!zone) return 'No avalanche forecast zone here.';
		if (view?.status === 'expired') return `The forecast for ${name} has expired.`;
		if (!ratings) return `${name} has no danger rating for today.`;
		if (!problems.length) return `${name} lists no avalanche problems today.`;
		return null;
	});
	$effect(() => {
		if (typeof pick === 'number' && pick >= problems.length) pick = 'all';
	});
</script>

<section
	class="avy glass"
	aria-label={overlay === 'problems' ? 'Avalanche problems' : 'Concern index'}
>
	{#if zonesState === 'loading' || zonesState === 'idle'}
		<p class="note">Loading avalanche zones…</p>
	{:else if zonesState === 'failed'}
		<p class="note">Couldn't load the avalanche zones. Check the avalanche center directly.</p>
	{:else}
		<div class="row">
			{#if zone}
				<button class="zone" onclick={() => onzone?.()} title="The forecast, as published"
					>{name} <span aria-hidden="true">›</span></button
				>
			{/if}
			{#if ratings}
				<span class="bands" aria-label="Today's danger by elevation, as published">
					{#each BANDS as b (b)}
						{@const lvl = ratings[b]}
						<span
							class="lvl"
							class:dark={lvl === 5}
							style:background={lvl ? DANGER_COLORS[lvl] : 'var(--surface-2)'}
							title={`${BAND_WORDS[b]}: ${lvl ?? '–'} ${dangerWord(lvl)}`}
							>{BAND_WORDS[b].split(' ')[0].slice(0, 3)} {lvl ?? '–'}</span
						>
					{/each}
				</span>
			{/if}
			{#if work === 'working' && overlay === 'concern'}<i class="spin" aria-label="Working"
				></i>{/if}
		</div>

		{#if overlay === 'problems'}
			{#if problemsWhy}
				<p class="note">{problemsWhy}</p>
			{:else}
				<div class="seg" role="group" aria-label="Problem">
					{#if problems.length > 1}
						<button aria-pressed={pick === 'all'} onclick={() => (pick = 'all')}>All</button>
					{/if}
					{#each problems as p, i (i)}
						<button
							aria-pressed={pick === i || (problems.length === 1 && pick === 'all')}
							onclick={() => (pick = i)}
							title={[p.aspects?.join(' '), p.elevations?.join(', ')].filter(Boolean).join(' · ')}
							>{p.name}</button
						>
					{/each}
				</div>
				<div class="row">
					<span class="key"><i style:background={MATCH_COLOR}></i>Steeper than</span>
					<div class="seg small" role="group" aria-label="Slopes steeper than">
						{#each [25, 30, 35] as d (d)}
							<button aria-pressed={slopeMin === d} onclick={() => (slopeMin = d)}>{d}°</button>
						{/each}
					</div>
				</div>
				{#if tooFar}<p class="note">Zoom in to see the terrain.</p>{/if}
			{/if}
			<p class="foot faint">
				Terrain matching the problems' aspects and elevations as published. {tl}{treeline?.own
					? ` (your numbers for ${treeline.name})`
					: ' (approximate)'}. Not a rating of any slope.
			</p>
		{:else}
			{#if concernWhy}
				<p class="note">{concernWhy}</p>
			{:else if tooFar}
				<p class="note">Zoom in to see the concern index.</p>
			{:else if work === 'failed'}
				<p class="note">The terrain here couldn't be loaded.</p>
			{:else}
				<div class="classes" aria-label="Concern index key">
					{#each CONCERN_CLASSES as c (c.label)}
						<span><i style:background={c.color}></i>{c.label}</span>
					{/each}
				</div>
				<p class="foot faint">{windNote} {sunNote}</p>
			{/if}
			<p class="cap"><strong>Experimental.</strong> {caption}</p>
			<p class="foot faint">
				Classes are relative to each other, not danger levels. {tl}{treeline?.own
					? ` (your numbers for ${treeline.name})`
					: ' (approximate)'}. Tap the map for the factors at a spot.
			</p>
		{/if}
	{/if}
</section>

<style>
	.avy {
		display: grid;
		gap: 6px;
		padding: 8px 12px;
		border-radius: 18px;
		font-size: 0.85rem;
		color: var(--text);
		background: color-mix(in srgb, var(--surface) 92%, transparent);
	}
	.row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 6px 10px;
		min-width: 0;
	}
	.zone {
		border: 0;
		background: transparent;
		color: var(--text);
		font: inherit;
		font-weight: 650;
		padding: 2px 0;
		cursor: pointer;
		text-align: left;
	}
	.zone span {
		color: var(--text-2);
	}
	.bands {
		display: inline-flex;
		gap: 3px;
	}
	.lvl {
		font-size: 0.7rem;
		font-weight: 650;
		padding: 2px 6px;
		border-radius: 6px;
		color: #1f1b2e;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.12);
		font-variant-numeric: tabular-nums;
	}
	.lvl.dark {
		color: #fff;
	}
	.seg {
		display: flex;
		overflow-x: auto;
		scrollbar-width: none;
		justify-self: start;
		max-width: 100%;
	}
	.seg button {
		font-size: 0.78rem;
		padding: 3px 10px;
		flex: 0 0 auto;
	}
	.key {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.75rem;
	}
	.key i,
	.classes i {
		width: 12px;
		height: 10px;
		border-radius: 3px;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.12);
	}
	.classes {
		display: flex;
		flex-wrap: wrap;
		gap: 3px 10px;
		font-size: 0.75rem;
	}
	.classes span {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		white-space: nowrap;
	}
	.note {
		margin: 0;
		font-size: 0.8rem;
		line-height: 1.3;
		color: var(--text-2);
	}
	.cap {
		margin: 0;
		font-size: 0.75rem;
		line-height: 1.3;
	}
	.foot {
		margin: 0;
		font-size: 0.7rem;
		line-height: 1.3;
	}
	.spin {
		width: 11px;
		height: 11px;
		margin-left: auto;
		border: 2px solid var(--text-2);
		border-right-color: transparent;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.spin {
			animation-duration: 3s;
		}
	}
</style>
