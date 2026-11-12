<!--
  Measuring: a line tapped out on the map, a ski run or tour tapped on it, or a GPX track
  (read on this device, never uploaded). Distance, climb and descent, the line's average
  and steepest grade, the steepest ground it crosses, and the elevation profile, coloured
  like the slope overlay.
-->
<script lang="ts">
	import type { UnitSystem } from '../units';
	import { elevation as fmtElevation } from '../units';
	import Profile from './Profile.svelte';
	import {
		distanceText,
		GRADE_RUN_M,
		heightText,
		lineStats,
		slopeColor,
		type Sample
	} from './measure';

	interface Props {
		/** "Measure", a run's name, or the GPX track's. */
		title: string;
		/** Where the line came from, in a few words. */
		note?: string;
		units: UnitSystem;
		/** Taps on the map add points. */
		editing: boolean;
		points: number;
		samples: Sample[] | null;
		status: 'idle' | 'loading' | 'ready' | 'failed';
		error?: string | null;
		onundo?: () => void;
		onclear?: () => void;
		ongpx: (file: File) => void;
		onhover?: (i: number | null) => void;
		onclose: () => void;
	}

	let {
		title,
		note = '',
		units,
		editing,
		points,
		samples,
		status,
		error = null,
		onundo,
		onclear,
		ongpx,
		onhover,
		onclose
	}: Props = $props();

	const st = $derived(samples ? lineStats(samples) : null);
	const ft = $derived(units === 'imperial');
	const run = $derived(ft ? `${Math.round(GRADE_RUN_M * 3.28084)} ft` : `${GRADE_RUN_M} m`);
	let input = $state<HTMLInputElement>();
</script>

<div class="measure" role="region" aria-label="Measure">
	<div class="head">
		<strong class="title">{title}</strong>
		{#if note}<span class="faint note">{note}</span>{/if}
	</div>

	{#if editing && points < 2}
		<p class="hint">
			Tap the map to add points{points ? '; one more for a line' : ''}. Or open a GPX track: it
			stays on this device.
		</p>
	{:else if status === 'loading'}
		<p class="hint" role="status">Measuring the terrain along the line…</p>
	{:else if status === 'failed'}
		<p class="hint" role="alert">{error ?? 'Couldn’t measure the terrain along this line.'}</p>
	{/if}

	{#if st && samples}
		<dl class="stats">
			<div>
				<dt>Distance</dt>
				<dd class="num">{distanceText(st.distance, units)}</dd>
			</div>
			<div>
				<dt>Climb · descent</dt>
				<dd class="num">↑ {heightText(st.climb, units)} · ↓ {heightText(st.descent, units)}</dd>
			</div>
			<div>
				<dt>Low · high</dt>
				<dd class="num">
					{fmtElevation(st.minElev, units)} · {fmtElevation(st.maxElev, units)}
				</dd>
			</div>
			<div>
				<dt>Line: average · steepest</dt>
				<dd class="num" title="The steepest {run} of the line itself">
					{Math.round(st.avgGrade)}° · {Math.round(st.steepGrade)}°
				</dd>
			</div>
			<div>
				<dt>Steepest ground crossed</dt>
				<dd class="num">
					<span class="chip" style:background={slopeColor(st.steepGround)}></span>
					{Math.round(st.steepGround)}°
				</dd>
			</div>
		</dl>
		<Profile {samples} {units} {onhover} />
		<p class="faint small">
			Ground slope from about 10 m terrain, so short steps and cornices don’t show. A line on the
			map, not a judgement of the terrain.
		</p>
	{/if}

	<div class="actions">
		{#if editing}
			<button onclick={onundo} disabled={!points}>Undo</button>
			<button onclick={onclear} disabled={!points}>Clear</button>
		{/if}
		<button onclick={() => input?.click()}>Open GPX…</button>
		<input
			bind:this={input}
			type="file"
			accept=".gpx,application/gpx+xml"
			hidden
			onchange={(e) => {
				const f = e.currentTarget.files?.[0];
				if (f) ongpx(f);
				e.currentTarget.value = '';
			}}
		/>
		<button class="close" onclick={onclose}>Done</button>
	</div>
</div>

<style>
	/* Solid, unlike the other controls: numbers and a chart over a busy map. */
	.measure {
		display: grid;
		gap: 8px;
		padding: 10px 12px;
		border-radius: 16px;
		background: var(--surface);
		border: 1px solid var(--border);
		box-shadow: var(--glass-shadow);
		font-size: 0.8rem;
		color: var(--text);
		max-height: 52vh;
		overflow-y: auto;
	}
	.head {
		display: flex;
		align-items: baseline;
		gap: 8px;
		flex-wrap: wrap;
	}
	.title {
		font-size: 0.9rem;
	}
	.note {
		font-size: 0.75rem;
	}
	.hint {
		margin: 0;
	}
	.stats {
		margin: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
		gap: 4px 12px;
	}
	.stats div {
		min-width: 0;
	}
	dt {
		font-size: 0.7rem;
		color: var(--text-2);
	}
	dd {
		margin: 0;
		font-weight: 600;
		display: flex;
		align-items: center;
		gap: 5px;
	}
	.chip {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 3px;
		border: 1px solid var(--border);
	}
	.small {
		margin: 0;
		font-size: 0.7rem;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
	}
	.actions button {
		font-size: 0.8rem;
		padding: 5px 11px;
		min-height: 32px;
	}
	.actions button:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.actions .close {
		margin-left: auto;
		border: 0;
		background: transparent;
		color: var(--accent);
		font-weight: 600;
	}
</style>
