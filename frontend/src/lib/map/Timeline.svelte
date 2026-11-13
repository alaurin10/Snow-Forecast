<!--
  The weather layer's controls at the foot of the map (the layer itself is chosen in the
  row of types above it, or in Layers): for the loops,
  a player and a slider (radar from three hours ago, through the nowcast, to ten days out;
  snow level and wind to three and a half days; clouds over the last three hours); for the
  others, a window picker; and the colour key for whichever is showing.
-->
<script lang="ts">
	import { elevation, type UnitSystem } from '../units';
	import { prefs, type MapWeather } from '../prefs.svelte';
	import { RAMPS, rampTop, TOTAL, totalTick, type Frame, type RampStep } from '../radar';
	import {
		DEPTH,
		depthTick,
		levelTick,
		SNOWLEVEL,
		WIND,
		windTick,
		type Pick,
		type WeatherView
	} from './weather';
	import { TERRAIN_NOTE } from './layers/snowtiles';

	interface Props {
		view: WeatherView;
		weather: MapWeather;
		units: UnitSystem;
		/** The frame on the slider. */
		frame: number;
		playing: boolean;
		/** The picked picture's window, in hours (0 for snow on the ground). */
		pickId: number;
		pick: Pick | undefined;
		current: Frame | undefined;
		label: { when: string; rel: string } | null;
		/** The frame on the slider is still being decoded. */
		waiting: boolean;
		/** Frames downloaded so far (file names). */
		ready: Set<string>;
		loadError: string | null;
		/** The snow level draped on the terrain (zoomed in), metres; null when it isn't. */
		snowLine?: number | null;
		/** The snow total on screen is the terrain-adjusted one (zoomed in). */
		adjusted?: boolean;
	}

	let {
		view,
		weather,
		units,
		frame = $bindable(),
		playing = $bindable(),
		pickId = $bindable(),
		pick,
		current,
		label,
		waiting,
		ready,
		loadError,
		snowLine = null,
		adjusted = false
	}: Props = $props();

	const legendRamps = [RAMPS.snow, RAMPS.mix, RAMPS.rain];
	const frames = $derived(view.frames);
	const count = $derived(frames.length);
	const pct = (i: number) => (count > 1 ? (i / (count - 1)) * 100 : 0);
	/** The slider's width in pixels, so day names can be kept far enough apart to read. */
	let trackWidth = $state(300);
	/** A day name needs about this much room (a three-letter name and its tick mark). */
	const TICK_PX = 30;
	// Under the slider: "Now" where the observations end, then each new day of the
	// forecast. Beyond two days a day is only a few frames wide, so names that would crowd
	// the one before are left out.
	const ticks = $derived.by(() => {
		const out: { at: number; name: string; now?: boolean }[] = [];
		const nowAt = view.now;
		if (nowAt >= 0 && nowAt < count - 1) out.push({ at: pct(nowAt), name: 'Now', now: true });
		let prevDay = -1;
		frames.forEach((f, i) => {
			if (f.kind !== 'forecast') return;
			const start = new Date((f.t - f.span_h * 3600) * 1000);
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
		const from = view.now;
		const to = view.nowcastEnd;
		if (from < 0 || to <= from) return null;
		return { left: pct(from), width: pct(to) - pct(from) };
	});
	// Beyond ~48 h: 3- and 6-hour averages, a coarser stretch of the slider.
	const extendedBand = $derived.by(() => {
		const from = view.extendedFrom;
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
	/** The key for the layers drawn in cells: its steps, tick text and unit. */
	const cells = $derived.by<{
		steps: RampStep[];
		tick: (v: number) => string;
		unit: string;
	} | null>(() => {
		const imp = units === 'imperial';
		if (weather === 'totals' || weather === 'snowfall')
			return { steps: TOTAL, tick: (v) => totalTick(v, units), unit: imp ? 'in' : 'cm' };
		if (weather === 'depth')
			return { steps: DEPTH, tick: (v) => depthTick(v, units), unit: imp ? 'in' : 'cm' };
		if (weather === 'snowlevel')
			return { steps: SNOWLEVEL, tick: (v) => levelTick(v, units), unit: imp ? 'ft' : 'm' };
		if (weather === 'wind')
			return { steps: WIND, tick: (v) => windTick(v, units), unit: imp ? 'mph' : 'km/h' };
		return null;
	});
	/** A cell dark enough to need light text (relative luminance under ~0.3). */
	function darkCell(hex: string): boolean {
		const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
		return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.42;
	}
	/** Said when a layer has nothing to show yet. */
	const empty = $derived(
		weather === 'totals'
			? "Snow totals aren't drawn yet."
			: weather === 'snowfall'
				? "Observed snowfall isn't available yet."
				: weather === 'depth'
					? "Snow on the ground isn't available yet."
					: weather === 'radar'
						? 'Loading…'
						: "This layer isn't drawn yet."
	);
</script>

<section class="controls glass" aria-label="Precipitation">
	<!-- Fixed rows, so the box keeps its size whatever it shows. -->
	<div class="main">
		{#if view.mode === 'pick'}
			{#if pick}
				<div class="totals">
					{#if view.picks.length > 1}
						<div class="seg" role="group" aria-label="Window">
							{#each view.picks as p (p.id)}
								<button
									aria-pressed={p.id === pick.id}
									aria-label={p.name}
									onclick={() => (pickId = p.id)}>{p.label}</button
								>
							{/each}
						</div>
					{:else}
						<strong class="one">{pick.name}</strong>
					{/if}
					<span
						class="span faint"
						title={adjusted ? `${TERRAIN_NOTE} ${pick.sources}` : pick.sources}
						>{pick.span}{#if adjusted}<span class="adj">&nbsp;· adjusted to terrain</span
							>{/if}</span
					>
				</div>
			{:else if loadError}
				<p class="note">{loadError}</p>
			{:else}
				<p class="note">{empty}</p>
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
			<p class="note">{empty}</p>
		{/if}
	</div>
	<div class="foot">
		{#if weather === 'wind'}
			<div class="seg sub" role="group" aria-label="Wind">
				<button aria-pressed={prefs.mapWind === 'gust'} onclick={() => prefs.setMapWind('gust')}
					>Gusts</button
				>
				<button
					aria-pressed={prefs.mapWind === 'ridge'}
					onclick={() => prefs.setMapWind('ridge')}
					title="The free-air wind at about 3,000 m">Ridge</button
				>
			</div>
		{/if}
		{#if snowLine != null}
			<span class="key line-key">
				<i class="sw snowy" aria-hidden="true"></i>Snow above {elevation(snowLine + 150, units)}
				<i class="sw mixy" aria-hidden="true"></i>mix ±{units === 'imperial' ? '500 ft' : '150 m'}
				<span class="faint">at the map's centre</span>
			</span>
		{:else if cells}
			<div class="key total-key" aria-label="Key, {cells.unit}">
				<span class="name">{cells.unit}</span>
				<span class="ticks-ramp">
					{#each cells.steps as s (s.from)}
						<span class="cell" class:dark={darkCell(s.color)} style:background={s.color}
							>{cells.tick(s.from)}</span
						>
					{/each}
				</span>
			</div>
		{:else if weather === 'clouds'}
			<span class="key faint">GOES-West · true colour by day, infrared at night</span>
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
	/* Placed by the map's dock (MapView), under the terrain controls when both show. */
	.controls {
		display: grid;
		gap: 6px;
		padding: 8px 12px 8px 8px;
		border-radius: 18px;
		font-size: 0.85rem;
	}
	.foot .sub {
		flex: 0 0 auto;
		margin-right: 6px;
	}
	.foot .sub button {
		font-size: 0.7rem;
		padding: 1px 7px;
	}
	.totals .one {
		font-size: 0.82rem;
	}
	.ticks-ramp .cell.dark {
		color: #fff;
	}
	.line-key {
		gap: 5px;
	}
	.sw {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 3px;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.2);
	}
	.sw.snowy {
		background: rgb(240 247 255);
	}
	.sw.mixy {
		background: rgb(244 166 198);
		margin-left: 4px;
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
