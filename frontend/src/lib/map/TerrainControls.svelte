<!--
  Controls for the two terrain layers that need them. Sun & shade: a date, and either a
  time of day (terrain shadows at that moment, with the hills lit from where the sun is)
  or the day's hours of direct sun. Wind effect: which stretch of the forecast the wind
  and new snow come from, and whose forecast that is.
-->
<script lang="ts">
	import { snow, speed, type UnitSystem } from '../units';
	import type { AreaState } from './layers/analysis';
	import { SUN_CLASSES } from './terrain/shade';
	import { compass16, type SunDay, type SunPosition } from './terrain/sun';
	import { LOADED_COLOR, SCOURED_COLOR } from './terrain/wind';
	import { WIND_RANGE_KM, WIND_WINDOWS, type WindSource, type WindWindow } from './windsource';

	interface Props {
		overlay: 'sun' | 'wind';
		units: UnitSystem;
		/** The map is zoomed out too far for the layer to be worked out. */
		tooFar: boolean;
		state: AreaState;
		offline: boolean;
		sunMode: 'shade' | 'hours';
		/** YYYY-MM-DD, the day at the place on screen. */
		sunDate: string;
		/** The moment the shade is shown for (Unix milliseconds). */
		sunTime: number;
		day: SunDay;
		position: SunPosition | null;
		windWindow: WindWindow;
		/** Wind for the middle of the map; null when no location is near enough. */
		wind: WindSource | null;
		/** The locations' wind has been fetched. */
		windLoaded: boolean;
		/** Away from every location: the map's own forecast here has been asked for. */
		pointTried?: boolean;
	}

	let {
		overlay,
		units,
		tooFar,
		state: work,
		offline,
		sunMode = $bindable(),
		sunDate = $bindable(),
		sunTime = $bindable(),
		day,
		position,
		windWindow = $bindable(),
		wind,
		windLoaded,
		pointTried = true
	}: Props = $props();

	const STEP = 15 * 60000;
	const from = $derived(day.sunrise == null ? 0 : Math.ceil(day.sunrise / STEP) * STEP);
	const to = $derived(day.sunset == null ? 0 : Math.floor(day.sunset / STEP) * STEP);
	const clock = (ms: number, zone = false) =>
		new Date(ms).toLocaleTimeString('en-US', {
			hour: 'numeric',
			minute: '2-digit',
			timeZoneName: zone ? 'short' : undefined
		});
	const range = $derived(
		units === 'imperial' ? `${Math.round(WIND_RANGE_KM / 1.609)} mi` : `${WIND_RANGE_KM} km`
	);
	const away = $derived(
		wind
			? units === 'imperial'
				? `${Math.round(wind.km / 1.609)} mi`
				: `${Math.round(wind.km)} km`
			: ''
	);
	const failed = $derived(
		offline ? 'No saved terrain for this view.' : "The terrain here couldn't be loaded."
	);
</script>

<section class="terrain glass" aria-label={overlay === 'sun' ? 'Sun and shade' : 'Wind effect'}>
	{#if overlay === 'sun'}
		<div class="row">
			<div class="seg" role="group" aria-label="Show">
				<button aria-pressed={sunMode === 'shade'} onclick={() => (sunMode = 'shade')}>Shade</button
				>
				<button aria-pressed={sunMode === 'hours'} onclick={() => (sunMode = 'hours')}
					>Sun hours</button
				>
			</div>
			{#if work === 'working'}<i class="spin" aria-label="Working"></i>{/if}
			<input class="date" type="date" bind:value={sunDate} aria-label="Date" required />
		</div>
		<div class="main">
			{#if tooFar}
				<p class="note">Zoom in to see where the sun reaches.</p>
			{:else if work === 'failed'}
				<p class="note">{failed}</p>
			{:else if day.sunrise == null || day.sunset == null}
				<p class="note">The sun doesn't rise and set here on this day.</p>
			{:else if sunMode === 'shade'}
				<div class="slider">
					<input
						type="range"
						min={from}
						max={to}
						step={STEP}
						bind:value={sunTime}
						aria-label="Time of day"
						aria-valuetext={clock(sunTime, true)}
					/>
					<div class="ends" aria-hidden="true">
						<span>Sunrise {clock(day.sunrise)}</span><span>Sunset {clock(day.sunset)}</span>
					</div>
				</div>
				<div class="time">
					<strong class="num">{clock(sunTime, true)}</strong>
					{#if position}
						<span
							>{position.altitude > 0
								? `Sun ${Math.round(position.altitude)}° up, ${compass16(position.azimuth)}`
								: 'Sun is down'}</span
						>
					{/if}
				</div>
			{:else}
				<div class="classes" aria-label="Hours of direct sun">
					{#each SUN_CLASSES as c (c.from)}
						<span><i style:background={c.color}></i>{c.label}</span>
					{/each}
				</div>
			{/if}
		</div>
		<p class="foot faint">
			{sunMode === 'shade' ? 'Shade' : 'Direct sun through the day,'} from the shape of the terrain alone.
			Trees and cloud aren't counted.
		</p>
	{:else}
		<div class="row">
			<div class="seg" role="group" aria-label="Wind and new snow from">
				{#each WIND_WINDOWS as w (w.id)}
					<button aria-pressed={windWindow === w.id} onclick={() => (windWindow = w.id)}
						>{w.label}</button
					>
				{/each}
			</div>
			{#if work === 'working'}<i class="spin" aria-label="Working"></i>{/if}
		</div>
		<div class="main">
			{#if tooFar}
				<p class="note">Zoom in to see the wind effect.</p>
			{:else if !windLoaded}
				<p class="note">Loading the wind…</p>
			{:else if !wind}
				<p class="note">
					No saved location within {range} of here{#if !pointTried}; checking the map's forecast…{:else},
						and the map's forecast has no ridge wind here{/if}.
				</p>
			{:else if !wind.rose && wind.model}
				<p class="note">
					Away from saved locations only the next 24 and 72 hours are known (from the map's
					forecast).
				</p>
			{:else if !wind.rose}
				<p class="note">
					{wind.location.name}'s forecast doesn't have this yet. It will after its next update.
				</p>
			{:else if work === 'failed'}
				<p class="note">{failed}</p>
			{:else}
				<p class="note">
					<strong
						>{#if wind.rose.wind_from}{wind.rose.wind_from} wind {speed(wind.rose.mean_kmh, units)},
							{snow(wind.rose.snow_cm, units)} of new snow{:else}{wind.rose.label}: nothing to show{/if}</strong
					>
					{#if wind.model}
						<span class="faint">· the map's forecast here (ridge-level wind, model snow)</span>
					{:else}
						<span class="faint">· {wind.location.name} summit forecast, {away} away</span>
					{/if}
				</p>
			{/if}
		</div>
		<div class="foot">
			<span class="scale" aria-hidden="true">
				<span>Scoured</span>
				<i
					style:background="linear-gradient(90deg, {SCOURED_COLOR}, transparent 45%, transparent
					55%, {LOADED_COLOR})"
				></i>
				<span>Loaded</span>
			</span>
			<span class="faint cap"
				>Likely wind effect from model wind and terrain shape. Local gusts and trees aren't
				modelled.</span
			>
		</div>
	{/if}
</section>

<style>
	.terrain {
		display: grid;
		gap: 6px;
		padding: 8px 12px 8px 8px;
		border-radius: 18px;
		font-size: 0.85rem;
		color: var(--text);
		/* Solid enough to read over a map in shadow. */
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
	.date {
		margin-left: auto;
		min-width: 0;
		font: inherit;
		font-size: 0.78rem;
		color: var(--text);
		background: var(--surface-2);
		border: 0;
		border-radius: 999px;
		padding: 4px 10px;
		color-scheme: light dark;
	}
	/* One height whatever it shows, so the box doesn't jump as the layer changes. */
	.main {
		min-height: 44px;
		display: flex;
		align-items: center;
		gap: 10px;
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
	.slider {
		flex: 1;
		min-width: 0;
		padding-left: 4px;
	}
	.slider input {
		width: 100%;
		margin: 0;
		accent-color: var(--accent);
	}
	.ends {
		display: flex;
		justify-content: space-between;
		font-size: 0.68rem;
		color: var(--text-2);
		line-height: 1;
		white-space: nowrap;
	}
	.time {
		display: grid;
		text-align: right;
		flex: 0 0 7.2rem;
		width: 7.2rem;
		line-height: 1.25;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.time span {
		font-size: 0.72rem;
		color: var(--text-2);
	}
	.classes {
		display: flex;
		flex-wrap: wrap;
		gap: 3px 10px;
		padding-left: 4px;
		font-size: 0.72rem;
	}
	.classes span {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		white-space: nowrap;
	}
	.classes i {
		width: 12px;
		height: 10px;
		border-radius: 3px;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.12);
	}
	.foot {
		margin: 0;
		padding-left: 4px;
		font-size: 0.7rem;
		line-height: 1.3;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 2px 12px;
	}
	.scale {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-weight: 600;
	}
	.scale i {
		width: 64px;
		height: 9px;
		border-radius: 3px;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.15);
	}
	.cap {
		flex: 1 1 220px;
	}
	.spin {
		width: 11px;
		height: 11px;
		flex-shrink: 0;
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
