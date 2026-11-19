<!--
  The top of the Observed tab: what the snow station says, at a glance. One sentence,
  the depth on the ground with its last month as a sparkline, the new snow over 24 h,
  72 h and 7 days, and the last seven days as cells tinted like the Forecast tab's
  calendar. Measured, not modelled.
-->
<script lang="ts">
	import { scaleLinear } from 'd3-scale';
	import type { Snotel } from '../types.gen';
	import { bucket } from '../calendar';
	import { bandPath, linePath, maxOf } from '../charts/geom';
	import { ago, weekday } from '../time';
	import { converters, elevation, snowNum, temperature, type UnitSystem } from '../units';
	import type { StationRead } from './read';

	interface Props {
		station: Snotel;
		read: StationRead;
		bandLabel: string;
		bandElev: number;
		/** The location's date today (YYYY-MM-DD), so its cell says "Today". */
		today?: string;
		units: UnitSystem;
	}

	let { station, read, bandLabel, bandElev, today, units }: Props = $props();
	const c = $derived(converters(units));

	// The sparkline: depth (or snow water without a depth sensor) over the last 30 days.
	const SW = 120;
	const SH = 36;
	const spark = $derived(read.days.map((d) => (read.hasDepth ? d.depth_cm : d.swe_mm)));
	const sy = $derived(
		scaleLinear()
			.domain([0, maxOf(spark, 1)])
			.range([SH - 2, 2])
	);
	const sxs = $derived(spark.map((_, i) => (i * SW) / Math.max(1, spark.length - 1)));
	const sys = $derived(spark.map((v) => (v === null ? null : sy(v))));

	const week = $derived(read.days.slice(-7));
	const offset = $derived(
		station.elev_m === null
			? ''
			: `${elevation(Math.abs(bandElev - station.elev_m), units)} ${bandElev >= station.elev_m ? 'below' : 'above'} ${bandLabel}`
	);
	const away = (km: number) =>
		units === 'imperial' ? `${(km * 0.621371).toFixed(1)} mi` : `${km.toFixed(1)} km`;
	const tiles = $derived([
		{ label: '24 h', cm: read.new24 },
		{ label: '72 h', cm: read.new72 },
		{ label: '7 days', cm: read.new7 }
	]);
</script>

<section class="card hero" aria-labelledby="obs-hero">
	<span class="eyebrow">At the snow station</span>
	<h2 id="obs-hero" class="headline">{read.headline}.</h2>
	{#if read.notes.length}
		<p class="notes muted">{read.notes.join(' · ')}</p>
	{/if}

	<div class="figures">
		<div class="fig ground">
			<span class="eyebrow">{read.hasDepth ? 'On the ground' : 'Snow water'}</span>
			<div class="groundrow">
				<span class="big num"
					>{#if read.hasDepth}{snowNum(read.depth_cm, units)}<small>{c.snowUnit}</small
						>{:else if station.swe_mm !== null}{c
							.water(station.swe_mm)
							?.toFixed(c.waterDigits)}<small>{c.waterUnit}</small>{:else}–{/if}</span
				>
				{#if spark.some((v) => v !== null)}
					<svg
						class="spark"
						width={SW}
						height={SH}
						viewBox="0 0 {SW} {SH}"
						role="img"
						aria-label="{read.hasDepth
							? 'Snow depth'
							: 'Snow water'} over the last {spark.length} days"
					>
						<path
							class="sarea"
							d={bandPath(
								sxs,
								sys.map((v) => (v === null ? null : SH)),
								sys
							)}
						/>
						<path class="sline" d={linePath(sxs, sys)} />
					</svg>
				{/if}
			</div>
			<span class="faint tiny">last {spark.length} days</span>
		</div>
		<div class="fig">
			<span class="eyebrow">New snow</span>
			<div class="newrow">
				{#each tiles as t (t.label)}
					<div class="tile">
						<span class="mid num"
							>{t.cm === null ? '–' : snowNum(t.cm, units)}{#if t.cm !== null}<small
									>{c.snowUnit}</small
								>{/if}</span
						>
						<span class="faint tiny">{t.label}</span>
					</div>
				{/each}
			</div>
		</div>
	</div>

	{#if week.length}
		<div class="weekhead">
			<span class="eyebrow">Last 7 days</span>
			<span class="faint tiny">new snow · high / low</span>
		</div>
		<ol class="week">
			{#each week as d (d.date)}
				{@const b = bucket(d.new_cm)}
				<li class="day c{b}">
					<span class="wd">{d.date === today ? 'Today' : weekday(d.date)}</span>
					<span class="amt num"
						>{d.new_cm === null
							? '–'
							: Number(snowNum(d.new_cm, units)) > 0
								? snowNum(d.new_cm, units)
								: '0'}</span
					>
					<span class="temps num"
						>{#if d.tmax_c !== null || d.tmin_c !== null}<span class:warm={(d.tmax_c ?? -1) > 0}
								>{temperature(d.tmax_c, units).replace(/[CF]$/, '')}</span
							>
							<span class="lo">{temperature(d.tmin_c, units).replace(/[CF]$/, '')}</span>{/if}</span
					>
				</li>
			{/each}
		</ol>
		<p class="sr-only">
			Each day’s new snow in {units === 'imperial' ? 'inches' : 'centimetres'}, then its high and
			low in {c.tempUnit}.
		</p>
	{/if}

	<p class="meta faint">
		<strong>{station.name ?? station.triplet}</strong> · {station.network ?? 'NRCS SNOTEL'}
		{#if station.elev_m !== null}· {elevation(station.elev_m, units)}{/if}
		{#if station.distance_km !== null && station.distance_km !== undefined}· {away(
				station.distance_km
			)} away{/if}
		{#if offset}· {offset}{/if}
		{#if station.obs_time}· read {ago(station.obs_time)}{/if}
	</p>
</section>

<style>
	.hero {
		display: grid;
		gap: 4px;
	}
	.headline {
		font-family: var(--font-num);
		font-size: 1.45rem;
		font-weight: 650;
		letter-spacing: -0.02em;
		line-height: 1.2;
		margin: 2px 0 0;
	}
	.notes {
		margin: 0;
		font-size: 0.92rem;
	}
	.figures {
		display: grid;
		gap: 14px 28px;
		margin: 14px 0 6px;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 230px), 1fr));
	}
	.fig {
		display: grid;
		gap: 4px;
		align-content: start;
	}
	.groundrow {
		display: flex;
		align-items: flex-end;
		gap: 14px;
	}
	.big {
		font-family: var(--font-num);
		font-size: 2.4rem;
		font-weight: 650;
		line-height: 1;
		letter-spacing: -0.03em;
	}
	.mid {
		font-family: var(--font-num);
		font-size: 1.55rem;
		font-weight: 600;
		line-height: 1.1;
		letter-spacing: -0.02em;
	}
	.big small,
	.mid small {
		font-family: var(--font-ui);
		font-size: 0.8rem;
		font-weight: 500;
		letter-spacing: 0;
		margin-left: 3px;
		color: var(--text-2);
	}
	.spark {
		display: block;
		flex: none;
	}
	.sarea {
		fill: var(--snow);
		opacity: 0.18;
	}
	.sline {
		fill: none;
		stroke: var(--snow);
		stroke-width: 2;
	}
	.newrow {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 8px;
	}
	.tile {
		display: grid;
	}
	.tiny {
		font-size: 0.76rem;
	}
	.weekhead {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 8px;
		margin-top: 10px;
	}
	.week {
		display: grid;
		grid-template-columns: repeat(7, minmax(0, 1fr));
		gap: 4px;
		margin: 4px 0 0;
		padding: 0;
		list-style: none;
	}
	.day {
		display: grid;
		justify-items: center;
		gap: 2px;
		padding: 7px 2px 6px;
		border-radius: 12px;
		background: var(--c0);
		color: var(--c-ink-light);
		min-width: 0;
	}
	.day.c1 {
		background: var(--c1);
	}
	.day.c2 {
		background: var(--c2);
	}
	.day.c3 {
		background: var(--c3);
	}
	.day.c4 {
		background: var(--c4);
		color: var(--c-ink-dark);
	}
	.day.c5 {
		background: var(--c5);
		color: var(--c-ink-dark);
	}
	.day.c0 {
		color: var(--text);
	}
	.wd {
		font-size: 0.72rem;
		font-weight: 600;
		opacity: 0.85;
	}
	.amt {
		font-family: var(--font-num);
		font-size: 1.15rem;
		font-weight: 650;
		line-height: 1.1;
	}
	.temps {
		display: flex;
		gap: 3px;
		font-size: 0.72rem;
		white-space: nowrap;
	}
	.temps .lo {
		opacity: 0.7;
	}
	.temps .warm {
		font-weight: 700;
	}
	.meta {
		margin: 10px 0 0;
		font-size: 0.8rem;
	}
	.meta strong {
		color: var(--text-2);
		font-weight: 600;
	}
	@media (max-width: 640px) {
		.headline {
			font-size: 1.25rem;
		}
		.big {
			font-size: 2rem;
		}
		.temps {
			flex-direction: column;
			align-items: center;
			gap: 0;
		}
	}
</style>
