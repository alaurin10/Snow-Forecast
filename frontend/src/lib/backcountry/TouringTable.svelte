<!--
  The weather for being out in, one column per day: the sky above treeline, wind and
  cold at the top, how well the snow refroze the night before, and the daylight. One
  table instead of four cards, so a day reads down its column.
-->
<script lang="ts">
	import { hscroll } from '../hscroll';
	import type { Snapshot } from '../types.gen';
	import { monthDay, weekday } from '../time';
	import { elevation, speed, temperature, type UnitSystem } from '../units';

	interface Props {
		snap: Snapshot;
		units: UnitSystem;
		/** How many days to show. */
		count?: number;
	}

	let { snap, units, count = 5 }: Props = $props();
	const today = $derived(snap.now.slice(0, 10));
	const days = $derived((snap.backcountry?.outlook ?? []).slice(0, count));
	const top = $derived(snap.bands[2]);
	const dayPeriod = (date: string) =>
		top.periods.find((p) => p.date === date && p.kind === 'day') ?? null;
	const sun = (date: string) => snap.sun.find((s) => s.date === date) ?? null;
	const bandLabel = (b: string) => snap.bands.find((x) => x.band === b)?.label ?? b;
	const clock = (iso: string | null | undefined) => {
		if (!iso) return '–';
		const h = Number(iso.slice(11, 13));
		return `${h % 12 || 12}:${iso.slice(14, 16)} ${h < 12 ? 'AM' : 'PM'}`;
	};
	const hm = (s: number | null | undefined) =>
		s === null || s === undefined
			? '–'
			: `${Math.floor(s / 3600)} h ${String(Math.round((s % 3600) / 60)).padStart(2, '0')}`;
	const pct = (v: number | null | undefined) => (v === null || v === undefined ? '–' : `${v}%`);
	const vis = (m: number | null | undefined) => {
		if (m === null || m === undefined) return '–';
		const [v, unit] = units === 'imperial' ? [m / 1609, 'mi'] : [m / 1000, 'km'];
		return v < 0.05 ? `under 0.1 ${unit}` : `${v.toFixed(v < 1 ? 1 : 0)} ${unit}`;
	};
	const cols = $derived(days.length + 1);
</script>

{#if days.length}
	<div class="table-wrap" use:hscroll>
		<table class="data touring">
			<caption class="sr-only">Touring weather for each day</caption>
			<thead>
				<tr>
					<th></th>
					{#each days as d (d.date)}
						<th scope="col"
							>{d.date === today ? 'Today' : weekday(d.date)}
							<span class="faint md">{monthDay(d.date)}</span></th
						>
					{/each}
				</tr>
			</thead>
			<tbody>
				<tr class="group"
					><th colspan={cols} scope="colgroup">Sky at the summit, in daylight</th></tr
				>
				<tr>
					<th scope="row">High cloud</th>
					{#each days as d (d.date)}<td class="num">{pct(d.sky?.cloud_high)}</td>{/each}
				</tr>
				<tr>
					<th scope="row">Mid cloud</th>
					{#each days as d (d.date)}<td class="num">{pct(d.sky?.cloud_mid)}</td>{/each}
				</tr>
				<tr>
					<th scope="row">Low cloud</th>
					{#each days as d (d.date)}<td class="num">{pct(d.sky?.cloud_low)}</td>{/each}
				</tr>
				<tr>
					<th scope="row">Lowest visibility</th>
					{#each days as d (d.date)}<td class="num">{vis(d.sky?.vis_min_m)}</td>{/each}
				</tr>

				<tr class="group"><th colspan={cols} scope="colgroup">Wind and cold up high</th></tr>
				<tr>
					<th scope="row">Ridge wind</th>
					{#each days as d (d.date)}
						<td class="num">{d.wind_from ? `${d.wind_from} ` : ''}{speed(d.wind_kmh, units)}</td>
					{/each}
				</tr>
				<tr>
					<th scope="row">Summit gusts</th>
					{#each days as d (d.date)}
						<td class="num">{speed(dayPeriod(d.date)?.gust_max_kmh, units)}</td>
					{/each}
				</tr>
				<tr>
					<th scope="row">Summit high / low</th>
					{#each days as d (d.date)}
						{@const p = dayPeriod(d.date)}
						<td class="num"
							>{p ? `${temperature(p.tmax_c, units)} / ${temperature(p.tmin_c, units)}` : '–'}</td
						>
					{/each}
				</tr>
				<tr>
					<th scope="row">Freezing level, highest</th>
					{#each days as d (d.date)}<td class="num">{elevation(d.fl_max_m, units)}</td>{/each}
				</tr>

				<tr class="group"><th colspan={cols} scope="colgroup">Refreeze, the night before</th></tr>
				{#each ['summit', 'mid', 'base'] as b (b)}
					<tr>
						<th scope="row">{bandLabel(b)}</th>
						{#each days as d (d.date)}
							{@const n = (d.refreeze ?? []).find((x) => x.band === b)}
							<td>
								<span class="rf rf-{(n?.status ?? 'Unknown').toLowerCase()}"
									>{n?.status ?? '–'}</span
								>
								<span class="faint num low">{temperature(n?.low_c, units)}</span>
							</td>
						{/each}
					</tr>
				{/each}

				<tr class="group"><th colspan={cols} scope="colgroup">Daylight</th></tr>
				<tr>
					<th scope="row">Sunrise</th>
					{#each days as d (d.date)}<td class="num">{clock(sun(d.date)?.sunrise)}</td>{/each}
				</tr>
				<tr>
					<th scope="row">Sunset</th>
					{#each days as d (d.date)}<td class="num">{clock(sun(d.date)?.sunset)}</td>{/each}
				</tr>
				<tr>
					<th scope="row">Day length</th>
					{#each days as d (d.date)}<td class="num">{hm(sun(d.date)?.daylight_s)}</td>{/each}
				</tr>
			</tbody>
		</table>
	</div>
	<p class="faint small">
		Ridge wind is the free-air wind at {elevation(snap.ridge?.level_m ?? top.elev_m, units)}, the
		average of each day’s strongest six hours. Refreeze is Good with a low of about 27 °F (−3 °C) or
		colder under a mostly clear sky, Partial at or just below freezing.
	</p>
{/if}

<style>
	.small {
		font-size: 0.8rem;
		margin: 8px 0 0;
	}
	.touring thead th {
		vertical-align: bottom;
	}
	.md {
		display: block;
		font-size: 0.72rem;
		font-weight: 500;
	}
	.touring tbody th {
		font-weight: 500;
		color: var(--text-2);
	}
	.group th {
		padding-top: 14px;
		border-bottom: 1px solid var(--border);
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-3);
		text-align: left;
	}
	.touring tbody tr.group:first-child th {
		padding-top: 4px;
	}
	.rf {
		font-weight: 600;
	}
	.low {
		margin-left: 5px;
		font-size: 0.8rem;
	}
	.rf-good {
		color: var(--snow);
	}
	.rf-none,
	.rf-unknown {
		color: var(--text-3);
		font-weight: 500;
	}
	/* Phones: a narrow label column that wraps, so three days show before scrolling. */
	@media (max-width: 640px) {
		.touring {
			font-size: 0.8rem;
		}
		.touring th,
		.touring td {
			padding: 6px 6px;
		}
		.touring tbody tr:not(.group) th {
			white-space: normal;
			width: 84px;
			min-width: 84px;
			max-width: 84px;
			line-height: 1.2;
		}
		.low {
			display: block;
			margin-left: 0;
		}
	}
</style>
