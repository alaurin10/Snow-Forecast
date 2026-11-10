<!-- One location's day in a popup, opened from the Calendar or a storm: the day and night
     snow, the high and low, and the day hour by hour, with an elevation switch. It loads
     the location's forecast itself, so you stay on the page you came from. -->
<script lang="ts">
	import { resolve } from '$app/paths';
	import { getSnapshot } from '../api';
	import { friendlyError } from '../errors';
	import { prefs } from '../prefs.svelte';
	import { dateOf, monthDay, weekday } from '../time';
	import { elevation, snow, temperature, type UnitSystem } from '../units';
	import type { BandOut, PeriodOut, Snapshot } from '../types.gen';
	import ForecastChart from '../charts/ForecastChart.svelte';
	import Sheet from './Sheet.svelte';

	interface Props {
		id: string;
		/** The location's name, shown while its forecast loads. */
		name: string;
		date: string;
		units: UnitSystem;
		onclose: () => void;
	}

	let { id, name, date, units, onclose }: Props = $props();

	let snap = $state<Snapshot | null>(null);
	let error = $state<string | null>(null);
	$effect(() => {
		snap = null;
		error = null;
		getSnapshot(id)
			.then((s) => (snap = s))
			.catch((e: Error) => (error = friendlyError(e)));
	});

	// The elevation starts at the viewer's default and can be switched here.
	let pick = $state<string | null>(null);
	const band = $derived.by<BandOut | null>(() => {
		const bands = snap?.bands ?? [];
		return (
			bands.find((b) => b.band === (pick ?? prefs.band)) ??
			bands.find((b) => b.band === 'mid') ??
			bands[0] ??
			null
		);
	});
	const start = $derived(band?.hourly.t.find((t) => dateOf(t) === date) ?? null);
	const half = (kind: 'day' | 'night') =>
		band?.periods.find((p) => p.date === date && p.kind === kind) ?? null;
	const day = $derived(half('day'));
	const night = $derived(half('night'));
	const amount = (p: PeriodOut | null) => {
		if (!p) return '–';
		if ((p.snow_cm ?? 0) >= 0.25) return snow(p.snow_cm, units);
		return (p.rain_mm ?? 0) >= 1 ? 'Rain' : 'None';
	};
	const temp = (v: number | null | undefined) =>
		v === null || v === undefined ? '–' : temperature(v, units);
</script>

<Sheet
	title={snap?.location.name ?? name}
	sub="{weekday(date)} {monthDay(date)}{band
		? ` · ${band.label}, ${elevation(band.elev_m, units)}`
		: ''}"
	width={780}
	{onclose}
>
	{#if error}
		<p class="muted" role="alert">{error}</p>
	{:else if !snap || !band}
		<p class="muted" aria-live="polite">Loading…</p>
	{:else}
		{#if snap.bands.length > 1}
			<div class="seg elev" role="group" aria-label="Elevation">
				{#each snap.bands as b (b.band)}
					<button aria-pressed={band.band === b.band} onclick={() => (pick = b.band)}
						>{b.label}</button
					>
				{/each}
			</div>
		{/if}
		<div class="sum">
			<div>
				<span class="eyebrow">Day</span>
				<strong class="num">{amount(day)}</strong>
				{#if day?.quality}<small>{day.quality}</small>{/if}
			</div>
			<div>
				<span class="eyebrow">Night</span>
				<strong class="num">{amount(night)}</strong>
				{#if night?.quality}<small>{night.quality}</small>{/if}
			</div>
			<div>
				<span class="eyebrow">High / low</span>
				<strong class="num"
					>{temp(day?.tmax_c ?? night?.tmax_c)} / {temp(night?.tmin_c ?? day?.tmin_c)}</strong
				>
			</div>
		</div>
		{#if start}
			{#key band.band}
				<ForecastChart {band} bands={snap.bands} {units} range={1} {start} embedded />
			{/key}
		{:else}
			<p class="muted">No hourly forecast for this day.</p>
		{/if}
		<a class="btn more" href={resolve('/location/[id]', { id })}>Full forecast →</a>
	{/if}
</Sheet>

<style>
	.elev {
		justify-self: start;
		max-width: 100%;
		overflow-x: auto;
	}
	.elev button {
		white-space: nowrap;
	}
	.sum {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 8px;
	}
	.sum > div {
		display: grid;
		gap: 2px;
		align-content: start;
		padding: 10px 12px;
		border-radius: 16px;
		background: var(--surface-2);
		min-width: 0;
	}
	.sum strong {
		font-size: 1.2rem;
		font-weight: 700;
	}
	.sum small {
		font-size: 0.74rem;
		color: var(--text-2);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.more {
		justify-self: start;
	}
	@media (max-width: 640px) {
		.sum strong {
			font-size: 1.05rem;
		}
	}
</style>
