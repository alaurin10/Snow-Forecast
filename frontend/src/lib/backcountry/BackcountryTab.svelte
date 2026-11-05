<!--
  The Backcountry tab: facts for planning a tour, side by side. Snow Watch never
  scores whether a tour is safe; the avalanche center's forecast is shown as
  published and linked.
-->
<script lang="ts">
	import type { AvalancheView, Snapshot } from '../types.gen';
	import { compass } from '../conditions';
	import { dateOf, dayHour, weekday } from '../time';
	import { elevation, snow, speed, temperature, water, type UnitSystem } from '../units';
	import DangerPyramid from './DangerPyramid.svelte';
	import LoadingRose from './LoadingRose.svelte';

	interface Props {
		snap: Snapshot;
		avy: AvalancheView | null;
		units: UnitSystem;
	}

	let { snap, avy, units }: Props = $props();

	const today = $derived(dateOf(snap.now));
	const bc = $derived(snap.backcountry ?? null);
	const ridge = $derived(snap.ridge ?? null);
	const hours = $derived(snap.bands[2].hourly.t);
	const ridgeMax = $derived.by(() => {
		if (!ridge) return null;
		let best: { i: number; v: number } | null = null;
		ridge.kmh.slice(0, 48).forEach((v, i) => {
			if (v !== null && (!best || v > best.v)) best = { i, v };
		});
		return best as { i: number; v: number } | null;
	});
	const nights = $derived([...new Set((bc?.refreeze ?? []).map((n) => n.date))]);
	const bandLabel = (b: string) => snap.bands.find((x) => x.band === b)?.label ?? b;
	const sun = $derived(snap.sun.filter((d) => d.date >= today).slice(0, 3));
	const dayName = (date: string) => (date === today ? 'Today' : weekday(date));
	const clock = (iso: string | null) => {
		if (!iso) return '–';
		const h = Number(iso.slice(11, 13));
		return `${h % 12 || 12}:${iso.slice(14, 16)} ${h < 12 ? 'AM' : 'PM'}`;
	};
	const hm = (s: number | null) =>
		s === null
			? '–'
			: `${Math.floor(s / 3600)} h ${String(Math.round((s % 3600) / 60)).padStart(2, '0')} min`;
	const rise = (m: number | null) =>
		m === null ? '–' : `${m > 0 ? '+' : ''}${elevation(m, units)}`;
	const tempRise = (c: number | null) => {
		if (c === null) return '–';
		const v = units === 'imperial' ? (c * 9) / 5 : c;
		return `${v > 0 ? '+' : ''}${v.toFixed(0)}°${units === 'imperial' ? 'F' : 'C'}`;
	};
</script>

<div class="bc">
	<section class="card wide">
		<DangerPyramid view={avy} tz={snap.location.tz} {today} />
	</section>

	<section class="card">
		<h2>Wind at ridge height</h2>
		{#if ridge}
			<p class="facts">
				<span
					><span class="k">Now</span>
					<strong class="num">{speed(ridge.kmh[0], units)}</strong> from {compass(
						ridge.dir[0]
					)}</span
				>
				{#if ridgeMax}
					<span
						><span class="k">Strongest, next 48 h</span>
						<strong class="num">{speed(ridgeMax.v, units)}</strong>
						{compass(ridge.dir[ridgeMax.i])}, {dayHour(hours[ridgeMax.i])}</span
					>
				{/if}
			</p>
			<p class="faint small">
				Free-air wind at {elevation(ridge.level_m, units)}, from the 850 and 700 hPa levels. It's
				the dashed line on the hourly wind chart.
			</p>
		{:else}
			<p class="muted small">No free-air wind in this run; the roses use the summit wind.</p>
		{/if}
		{#if bc}
			<div class="roses">
				{#each bc.rose as r (r.window)}
					<LoadingRose rose={r} title={r.window === 'past72' ? 'Last 72 h' : 'Next 48 h'} {units} />
				{/each}
			</div>
			<p class="faint small">
				Wedges show where snow-carrying wind came from; it drifts onto the opposite (lee) slopes.
			</p>
		{/if}
	</section>

	{#if bc}
		<section class="card">
			<h2>Storm snow and warming</h2>
			<dl class="pairs">
				<dt>New snow, last 72 h (summit)</dt>
				<dd class="num">{snow(bc.storm.past72_cm, units)}</dd>
				<dt>New snow, next 48 h (summit)</dt>
				<dd class="num">{snow(bc.storm.next48_cm, units)}</dd>
				<dt>Biggest freezing-level rise in 24 h</dt>
				<dd>
					<span class="num">{rise(bc.warming.fl_rise_m)}</span>
					{#if bc.warming.fl_rise_at && (bc.warming.fl_rise_m ?? 0) > 0}<span class="muted">
							by {dayHour(bc.warming.fl_rise_at)}</span
						>{/if}
				</dd>
				<dt>Biggest warming in 24 h ({bandLabel('mid')})</dt>
				<dd>
					<span class="num">{tempRise(bc.warming.temp_rise_c)}</span>
					{#if bc.warming.temp_rise_at && (bc.warming.temp_rise_c ?? 0) > 0}<span class="muted">
							by {dayHour(bc.warming.temp_rise_at)}</span
						>{/if}
				</dd>
				<dt>Rain on snow, next 48 h ({bandLabel('mid')})</dt>
				<dd class="num">
					{bc.warming.rain_on_snow_mm === null
						? 'no snow on the ground'
						: water(bc.warming.rain_on_snow_mm, units)}
				</dd>
			</dl>
		</section>

		<section class="card">
			<h2>Overnight refreeze</h2>
			<div class="table-wrap">
				<table class="data">
					<thead>
						<tr>
							<th></th>
							{#each nights as d (d)}<th>{d === today ? 'Tonight' : weekday(d)}</th>{/each}
						</tr>
					</thead>
					<tbody>
						{#each ['summit', 'mid', 'base'] as b (b)}
							<tr>
								<th scope="row">{bandLabel(b)}</th>
								{#each nights as d (d)}
									{@const n = bc.refreeze.find((x) => x.band === b && x.date === d)}
									<td>
										<span class="rf rf-{(n?.status ?? 'Unknown').toLowerCase()}"
											>{n?.status ?? '–'}</span
										>
										<span class="faint num low">{temperature(n?.low_c, units)}</span>
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="faint small">
				Good: a low of about 27 °F (−3 °C) or colder under a mostly clear sky. Partial: at or just
				below freezing.
			</p>
		</section>

		<section class="card">
			<h2>Sky above treeline</h2>
			<div class="table-wrap">
				<table class="data">
					<thead>
						<tr>
							<th></th>
							{#each bc.sky as s (s.date)}<th>{dayName(s.date)}</th>{/each}
						</tr>
					</thead>
					<tbody>
						<tr>
							<th scope="row">High cloud</th>
							{#each bc.sky as s (s.date)}<td class="num">{s.cloud_high ?? '–'}%</td>{/each}
						</tr>
						<tr>
							<th scope="row">Mid cloud</th>
							{#each bc.sky as s (s.date)}<td class="num">{s.cloud_mid ?? '–'}%</td>{/each}
						</tr>
						<tr>
							<th scope="row">Low cloud</th>
							{#each bc.sky as s (s.date)}<td class="num">{s.cloud_low ?? '–'}%</td>{/each}
						</tr>
						<tr>
							<th scope="row">Lowest visibility</th>
							{#each bc.sky as s (s.date)}
								<td class="num"
									>{s.vis_min_m === null
										? '–'
										: units === 'imperial'
											? `${(s.vis_min_m / 1609).toFixed(s.vis_min_m < 1609 ? 1 : 0)} mi`
											: `${(s.vis_min_m / 1000).toFixed(s.vis_min_m < 1000 ? 1 : 0)} km`}</td
								>
							{/each}
						</tr>
					</tbody>
				</table>
			</div>
			<p class="faint small">Daytime averages at the summit.</p>
		</section>
	{/if}

	<section class="card">
		<h2>Daylight</h2>
		<div class="table-wrap">
			<table class="data">
				<thead>
					<tr><th></th><th>Sunrise</th><th>Sunset</th><th>Daylight</th></tr>
				</thead>
				<tbody>
					{#each sun as d (d.date)}
						<tr>
							<th scope="row">{dayName(d.date)}</th>
							<td class="num">{clock(d.sunrise)}</td>
							<td class="num">{clock(d.sunset)}</td>
							<td class="num">{hm(d.daylight_s)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</section>

	<p class="faint small wide note">
		Snow Watch doesn't judge whether a tour is safe. Read the avalanche center's forecast, and
		decide in the field.
	</p>
</div>

<style>
	.bc {
		display: grid;
		gap: 12px;
	}
	@media (min-width: 900px) {
		.bc {
			grid-template-columns: 1fr 1fr;
		}
		.wide {
			grid-column: 1 / -1;
		}
	}
	h2 {
		margin: 0 0 8px;
	}
	.small {
		font-size: 0.82rem;
	}
	.facts {
		display: grid;
		gap: 4px;
		margin: 0 0 6px;
	}
	.k {
		display: inline-block;
		min-width: 9.5em;
		color: var(--text-2);
		font-size: 0.85rem;
	}
	.roses {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
		margin-top: 8px;
	}
	.pairs {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 6px 12px;
		margin: 0;
		font-size: 0.88rem;
	}
	.pairs dt {
		color: var(--text-2);
	}
	.pairs dd {
		margin: 0;
		text-align: right;
	}
	.rf {
		display: block;
		font-weight: 600;
	}
	.low {
		display: block;
		font-size: 0.8rem;
	}
	.rf-good {
		color: var(--snow);
	}
	.rf-partial {
		color: var(--text);
	}
	.rf-none,
	.rf-unknown {
		color: var(--text-3);
	}
	.note {
		margin: 0;
	}
</style>
