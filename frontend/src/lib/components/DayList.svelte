<!-- Day by day: one row per date with the snow (day and night halves on one bar),
     high and low, top gust and lowest snow level. Tap a row for the details. -->
<script lang="ts">
	import type { PeriodOut } from '../types.gen';
	import { forecastDays } from '../daybars';
	import { monthDay } from '../time';
	import { converters, elevation, snowNum, speed, water, type UnitSystem } from '../units';

	interface Props {
		periods: PeriodOut[];
		units: UnitSystem;
		onselect?: (p: PeriodOut) => void;
	}

	let { periods, units, onselect }: Props = $props();
	const c = $derived(converters(units));
	const days = $derived(forecastDays(periods));
	const max = $derived(Math.max(2.54, ...days.map((d) => d.cm)));
	const w = (cm: number | null | undefined) => `${(((cm ?? 0) / max) * 100).toFixed(1)}%`;
	const t = (v: number | null) => (v === null ? '–' : `${Math.round(c.temp(v) ?? 0)}°`);
</script>

<ol class="days">
	{#each days as d (d.date)}
		<li>
			<button class="row" onclick={() => onselect?.((d.day ?? d.night) as PeriodOut)}>
				<span class="when">
					<strong>{d.label}</strong>
					<span class="faint">{monthDay(d.date)}</span>
				</span>
				<span class="snow">
					<span class="amt num">{snowNum(d.cm, units)}<small>{c.snowUnit}</small></span>
					<span class="bar" aria-hidden="true">
						{#if (d.day?.snow_cm ?? 0) > 0}
							<span class="seg {d.dayKind}" style:width={w(d.day?.snow_cm)}></span>
						{/if}
						{#if (d.night?.snow_cm ?? 0) > 0}
							<span
								class="seg {d.nightKind}"
								class:gap={(d.day?.snow_cm ?? 0) > 0}
								style:width={w(d.night?.snow_cm)}
							></span>
						{/if}
					</span>
					<span class="split faint">
						{`day ${snowNum(d.day?.snow_cm ?? 0, units)} · night ${snowNum(d.night?.snow_cm ?? 0, units)}`}
						{#if d.note}<em class="note {d.note.toLowerCase()}"
								>{`${d.note} ${water(d.rain_mm, units)}`}</em
							>{/if}
					</span>
				</span>
				<span class="meta">
					<span class="num">{`${t(d.tmax)} / ${t(d.tmin)}`}</span>
					<span><span class="faint">gusts</span>&nbsp;{speed(d.gust, units)}</span>
					<span><span class="faint">snow level</span>&nbsp;{elevation(d.snowLevel, units)}</span>
				</span>
			</button>
		</li>
	{/each}
</ol>

<style>
	.days {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.days li + li {
		border-top: 1px solid var(--grid);
	}
	.row {
		width: 100%;
		display: grid;
		grid-template-columns: 64px minmax(0, 1fr);
		grid-template-areas: 'when snow' 'when meta';
		gap: 4px 14px;
		align-items: center;
		padding: 12px 4px;
		border: 0;
		background: none;
		text-align: left;
		cursor: pointer;
		border-radius: 10px;
	}
	.row:hover {
		background: color-mix(in srgb, var(--surface-2) 50%, transparent);
	}
	.when {
		grid-area: when;
		display: grid;
		gap: 1px;
		font-size: 0.82rem;
		align-self: start;
	}
	.when strong {
		font-size: 0.95rem;
		font-weight: 600;
	}
	.snow {
		grid-area: snow;
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		grid-template-areas: 'amt bar' 'split split';
		gap: 2px 12px;
		align-items: center;
		min-width: 0;
	}
	.amt {
		grid-area: amt;
		font-size: 1.15rem;
		font-weight: 600;
		min-width: 64px;
		white-space: nowrap;
	}
	.amt small {
		font-family: var(--font-ui);
		font-size: 0.72rem;
		font-weight: 500;
		color: var(--text-2);
		margin-left: 2px;
	}
	.note {
		font-family: var(--font-ui);
		font-style: normal;
		font-size: 0.68rem;
		font-weight: 600;
		margin-left: 6px;
		padding: 1px 6px;
		border-radius: 999px;
		color: var(--surface);
	}
	.note.rain {
		background: var(--rain);
	}
	.note.mixed {
		background: var(--mix);
	}
	.bar {
		grid-area: bar;
		display: flex;
		height: 8px;
		border-radius: 4px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.seg {
		height: 100%;
	}
	/* A thin gap, not a different colour, separates night from day. */
	.seg.gap {
		border-left: 2px solid var(--surface);
	}
	.seg.snow {
		background: var(--snow);
	}
	.seg.heavy {
		background: var(--snow-heavy);
	}
	.seg.mix {
		background: var(--mix);
	}
	.seg.rain {
		background: var(--rain);
	}
	.split {
		grid-area: split;
		font-size: 0.72rem;
	}
	.meta {
		grid-area: meta;
		display: flex;
		flex-wrap: wrap;
		gap: 2px 14px;
		font-size: 0.8rem;
		color: var(--text-2);
	}
	@media (min-width: 900px) {
		.row {
			grid-template-columns: 90px minmax(0, 1fr) 360px;
			grid-template-areas: 'when snow meta';
			padding: 10px 8px;
		}
		.meta {
			display: grid;
			grid-template-columns: 80px 1fr 1.3fr;
			gap: 12px;
		}
	}
</style>
