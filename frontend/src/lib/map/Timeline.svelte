<!--
  The weather layer's controls at the foot of the map: Radar & forecast (a player and a
  slider from the last three hours of radar, through the nowcast, to ten days out) or
  Snow total (a window picker), and the colour key for whichever is showing.
-->
<script lang="ts">
	import type { UnitSystem } from '../units';
	import { prefs } from '../prefs.svelte';
	import {
		RAMPS,
		rampTop,
		TOTAL,
		totalLabel,
		totalName,
		totalSources,
		totalSpan,
		totalTick,
		type Frame,
		type Timeline,
		type Total
	} from '../radar';

	interface Props {
		timeline: Timeline | null;
		units: UnitSystem;
		totalsMode: boolean;
		/** The frame on the slider. */
		frame: number;
		playing: boolean;
		/** The snow total's window, in hours. */
		totalWindow: number;
		total: Total | undefined;
		current: Frame | undefined;
		label: { when: string; rel: string } | null;
		/** The frame on the slider is still being decoded. */
		waiting: boolean;
		/** Frames downloaded so far (file names). */
		ready: Set<string>;
		loadError: string | null;
	}

	let {
		timeline,
		units,
		totalsMode,
		frame = $bindable(),
		playing = $bindable(),
		totalWindow = $bindable(),
		total,
		current,
		label,
		waiting,
		ready,
		loadError
	}: Props = $props();

	const unit = $derived(units === 'imperial' ? 'in' : 'cm');
	const legendRamps = [RAMPS.snow, RAMPS.mix, RAMPS.rain];
	const frames = $derived(timeline?.frames ?? []);
	const totals = $derived(timeline?.totals ?? []);
	const count = $derived(frames.length);
	const pct = (i: number) => (count > 1 ? (i / (count - 1)) * 100 : 0);
	/** The slider's width in pixels, so day names can be kept far enough apart to read. */
	let trackWidth = $state(300);
	/** A day name needs about this much room (a three-letter name and its tick mark). */
	const TICK_PX = 30;
	// Under the slider: "Now" where the radar ends, then each new day of the forecast.
	// Beyond two days a day is only a few frames wide, so names that would crowd the one
	// before are left out.
	const ticks = $derived.by(() => {
		const out: { at: number; name: string; now?: boolean }[] = [];
		const nowAt = timeline?.now ?? -1;
		if (nowAt >= 0 && nowAt < count - 1) out.push({ at: pct(nowAt), name: 'Now', now: true });
		let prevDay = -1;
		frames.forEach((f, i) => {
			if (f.kind !== 'forecast') return;
			const start = new Date((f.t - (f.span_h || 1) * 3600) * 1000);
			const day = start.getDate();
			const newDay = prevDay >= 0 && day !== prevDay;
			prevDay = day;
			const last = out[out.length - 1];
			if (newDay && !(last && ((pct(i) - last.at) / 100) * trackWidth < TICK_PX))
				out.push({ at: pct(i), name: start.toLocaleDateString('en-US', { weekday: 'short' }) });
		});
		return out;
	});
	// The nowcast's stretch of the slider, between the radar and the forecast.
	const nowcastBand = $derived.by(() => {
		const from = timeline?.now ?? -1;
		const to = timeline?.nowcastEnd ?? -1;
		if (from < 0 || to <= from) return null;
		return { left: pct(from), width: pct(to) - pct(from) };
	});
	// Beyond ~48 h: 3- and 6-hour averages, a coarser stretch of the slider.
	const extendedBand = $derived.by(() => {
		const from = timeline?.extendedFrom ?? -1;
		if (from < 1 || count < 2) return null;
		const left = (pct(from - 1) + pct(from)) / 2;
		return { left, width: 100 - left };
	});
	// The slider track: downloaded frames shaded, like a video's buffered range.
	const buffered = $derived.by(() => {
		if (count < 2 || ready.size >= count) return 'none';
		const w = 100 / (count - 1);
		const stops: string[] = [];
		frames.forEach((f, i) => {
			const c = ready.has(f.file) ? 'var(--buffered)' : 'transparent';
			stops.push(`${c} ${Math.max(0, (i - 0.5) * w)}%`, `${c} ${Math.min(100, (i + 0.5) * w)}%`);
		});
		return `linear-gradient(90deg, ${stops.join(', ')})`;
	});
</script>

<section class="controls glass" aria-label="Precipitation">
	<div class="modes seg" role="group" aria-label="Show">
		<button aria-pressed={!totalsMode} onclick={() => prefs.setMapWeather('radar')}
			>Radar & forecast</button
		>
		<button aria-pressed={totalsMode} onclick={() => prefs.setMapWeather('totals')}
			>Snow total</button
		>
	</div>
	<!-- Fixed rows, so the box keeps its size whatever it shows. -->
	<div class="main">
		{#if totalsMode}
			{#if total}
				<div class="totals">
					<div class="seg" role="group" aria-label="Window">
						{#each totals as t (t.window)}
							<button
								aria-pressed={t.window === total.window}
								aria-label={totalName(t)}
								onclick={() => (totalWindow = t.window)}>{totalLabel(t)}</button
							>
						{/each}
					</div>
					<span class="span faint" title={totalSources(total)}>{totalSpan(total)}</span>
				</div>
			{:else if loadError}
				<p class="note">{loadError}</p>
			{:else}
				<p class="note">Snow totals aren't drawn yet.</p>
			{/if}
		{:else if count && label && current}
			<div class="player">
				<button
					class="play"
					onclick={() => (playing = !playing)}
					aria-label={playing ? 'Pause' : 'Play'}
				>
					<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
						{#if playing}<path d="M8 5v14M16 5v14" />{:else}<path d="M7 5l12 7-12 7z" />{/if}
					</svg>
				</button>
				<div class="track" bind:clientWidth={trackWidth}>
					<input
						type="range"
						min="0"
						max={Math.max(0, count - 1)}
						bind:value={frame}
						oninput={() => (playing = false)}
						aria-label="Time"
						aria-valuetext={`${label.when}, ${label.rel}`}
						style:--buffer={buffered}
					/>
					{#if nowcastBand || extendedBand}
						<div class="bands" aria-hidden="true">
							{#if nowcastBand}
								<span
									class="nowband"
									title="Nowcast"
									style:left="{nowcastBand.left}%"
									style:width="{nowcastBand.width}%"
								></span>
							{/if}
							{#if extendedBand}
								<span
									class="extband"
									title="3- and 6-hour averages"
									style:left="{extendedBand.left}%"
									style:width="{extendedBand.width}%"
								></span>
							{/if}
						</div>
					{/if}
					<div class="ticks" aria-hidden="true">
						{#each ticks as d (d.at)}
							<span class:now={d.now} style:left="{d.at}%">{d.name}</span>
						{/each}
					</div>
				</div>
				<div class="time" aria-live="off">
					<strong class="num">{label.when}</strong>
					<span class:fc={current.kind === 'forecast'} class:nc={current.kind === 'nowcast'}
						>{#if waiting}<i class="spin" aria-label="Loading"></i>{/if}{label.rel}</span
					>
				</div>
			</div>
		{:else if loadError}
			<p class="note">{loadError}</p>
		{:else}
			<p class="note">Loading…</p>
		{/if}
	</div>
	<div class="foot">
		{#if totalsMode}
			{#if total}
				<div class="key total-key" aria-label="Snow total, {unit}">
					<span class="name">{unit}</span>
					<span class="ticks-ramp">
						{#each TOTAL as s (s.from)}
							<span class="cell" style:background={s.color}>{totalTick(s.from, units)}</span>
						{/each}
					</span>
				</div>
			{/if}
		{:else}
			<div class="key">
				{#each legendRamps as r (r.kind)}
					<span class="kind">
						<span class="name">{r.label}</span>
						<span class="ramp" aria-hidden="true">
							{#each r.steps as s (s.from)}<i style:background={s.color}></i>{/each}
						</span>
						<span class="top">{rampTop(r, units)}</span>
					</span>
				{/each}
			</div>
		{/if}
	</div>
</section>

<style>
	.controls {
		--buffered: color-mix(in srgb, var(--accent) 28%, transparent);
	}
	/* A note inside the controls sits in the flow, not over the map. */
	.controls .note {
		position: static;
		max-width: none;
		margin: 0;
		padding: 0 4px;
		color: var(--text-2);
		font-weight: 500;
		cursor: default;
	}
	.controls {
		position: absolute;
		left: 10px;
		right: 10px;
		bottom: 10px;
		z-index: 1000;
		max-width: 640px;
		margin: 0 auto;
		display: grid;
		gap: 6px;
		padding: 8px 12px 8px 8px;
		border-radius: 18px;
		font-size: 0.85rem;
	}
	/* Clear the floating tab bar on phones. */
	@media (max-width: 1099px) {
		.controls {
			bottom: calc(84px + env(safe-area-inset-bottom));
		}
	}
	.modes {
		justify-self: start;
	}
	.modes button {
		font-size: 0.78rem;
		padding: 3px 10px;
	}
	/* Two fixed rows under the mode switch, so the box never changes size: the player
	   (or the total's window), then one line of key. */
	.main {
		height: 50px;
		display: flex;
		align-items: center;
		min-width: 0;
	}
	.main > * {
		flex: 1;
		min-width: 0;
	}
	.main .note {
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		overflow: hidden;
		font-size: 0.8rem;
		line-height: 1.3;
	}
	.foot {
		height: 18px;
		display: flex;
		align-items: center;
		min-width: 0;
		overflow: hidden;
	}
	.foot .key {
		flex: 1;
		min-width: 0;
		flex-wrap: nowrap;
		white-space: nowrap;
		overflow: hidden;
	}
	/* The window picker scrolls sideways on a phone; the dates sit under it. */
	.totals {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 3px;
	}
	.totals .seg {
		flex: 0 0 auto;
		display: flex;
		overflow-x: auto;
		scrollbar-width: none;
		-webkit-overflow-scrolling: touch;
	}
	.totals .seg::-webkit-scrollbar {
		display: none;
	}
	.totals .span {
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.totals .seg button {
		font-size: 0.78rem;
		padding: 3px 9px;
	}
	.totals .span {
		font-size: 0.75rem;
	}
	.totals .seg button {
		min-width: 44px;
		flex: 0 0 auto;
		white-space: nowrap;
	}
	.total-key {
		gap: 6px;
	}
	.ticks-ramp {
		display: flex;
		flex: 1;
		min-width: 0;
		border-radius: 4px;
		overflow: hidden;
	}
	.ticks-ramp .cell {
		flex: 1;
		text-align: center;
		font: 600 0.62rem/1.6 var(--font-num, sans-serif);
		color: #1f1b2e;
	}
	.player {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.play {
		width: 38px;
		height: 38px;
		flex-shrink: 0;
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 999px;
		background: var(--accent);
		color: var(--on-accent);
		cursor: pointer;
	}
	.play svg {
		fill: currentColor;
		stroke: currentColor;
		stroke-width: 2.4;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.track {
		flex: 1;
		min-width: 0;
		position: relative;
	}
	.track input {
		width: 100%;
		margin: 0;
		accent-color: var(--accent);
		background: var(--buffer, none);
		border-radius: 999px;
	}
	.ticks {
		position: relative;
		height: 13px;
		margin: 0 8px;
	}
	.ticks span {
		position: absolute;
		top: 0;
		transform: translateX(-50%);
		font-size: 0.68rem;
		color: var(--text-2);
		border-left: 1px solid var(--border);
		padding-left: 3px;
		line-height: 1;
		white-space: nowrap;
	}
	.ticks span.now {
		color: var(--accent-ink);
		font-weight: 600;
		border-left-color: var(--accent);
	}
	/* One width whatever it says, so the slider beside it never changes size while it's
	   being dragged. Wide enough for the longest labels ("Tue 11 PM–12 AM",
	   "6-hour avg · in 10 days", "radar · 2 h 48 min ago"). */
	.time {
		display: grid;
		text-align: right;
		flex: 0 0 8.1rem;
		width: 8.1rem;
		line-height: 1.25;
		font-variant-numeric: tabular-nums;
	}
	.time strong {
		color: var(--text);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.time span {
		position: relative;
		color: var(--text-2);
		font-size: 0.72rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.time span.fc {
		color: var(--accent-ink);
	}
	.time span.nc {
		color: var(--text);
	}
	/* The nowcast's stretch: a thin bar just above the slider, inset like the ticks. */
	.bands {
		position: absolute;
		top: -3px;
		left: 8px;
		right: 8px;
		height: 3px;
		pointer-events: none;
	}
	.nowband {
		position: absolute;
		top: 0;
		height: 100%;
		border-radius: 2px;
		background: color-mix(in srgb, var(--accent) 60%, transparent);
	}
	/* The 3- and 6-hour stretch: dashed, to read as coarser. */
	.extband {
		position: absolute;
		top: 0;
		height: 100%;
		border-radius: 2px;
		background: repeating-linear-gradient(
			90deg,
			color-mix(in srgb, var(--text-2) 55%, transparent) 0 4px,
			transparent 4px 7px
		);
	}
	.spin {
		display: inline-block;
		width: 9px;
		height: 9px;
		margin-right: 5px;
		border: 2px solid currentColor;
		border-right-color: transparent;
		border-radius: 50%;
		vertical-align: -1px;
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
	.note {
		margin: 4px 6px;
		color: var(--text-2);
	}
	.key {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 12px;
		font-size: 0.7rem;
		color: var(--text-2);
		padding-left: 4px;
	}
	.kind {
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}
	.kind .name {
		font-weight: 600;
		color: var(--text);
	}
	.ramp {
		display: inline-flex;
		height: 9px;
		border-radius: 3px;
		overflow: hidden;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.08);
	}
	.ramp i {
		width: 9px;
	}
	/* Phones: keep the key to one line; the amounts are in the info panel. */
	@media (max-width: 480px) {
		.key .top {
			display: none;
		}
	}
</style>
