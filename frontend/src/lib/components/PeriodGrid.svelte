<!-- Day by day as a period table: two rows per day (day, then night), the day named once
     beside them. Columns: temperature and sky, 12-hour snow, snow ratio, snow level,
     chance and amount of precipitation, wind and gust, cloud. Night rows are shaded. -->
<script lang="ts">
	import { hscroll } from '../hscroll';
	import type { HourlyOut, PeriodOut } from '../types.gen';
	import { HEAVY_CM, precipKind } from '../daybars';
	import { periodWeather, wxIcon } from '../periodwx';
	import { compass } from '../conditions';
	import { dateOf, monthDay, weekday } from '../time';
	import { converters, roundTo, snowNum, type UnitSystem } from '../units';
	import WxIcon from './WxIcon.svelte';

	interface Props {
		periods: PeriodOut[];
		hourly: HourlyOut;
		units: UnitSystem;
		onselect?: (p: PeriodOut) => void;
	}

	let { periods, hourly, units, onselect }: Props = $props();
	const c = $derived(converters(units));

	const rows = $derived.by(() => {
		const max = Math.max(2.54, ...periods.map((p) => p.snow_cm ?? 0));
		return periods.map((p, i) => {
			const first = i === 0 || periods[i - 1].date !== p.date;
			const span = periods.filter((q) => q.date === p.date).length;
			const wx = periodWeather(hourly, p);
			const night = p.kind === 'night';
			return {
				p,
				first,
				span,
				night,
				day: p.label === 'Today' || p.label === 'Tonight' ? 'Today' : weekday(p.date),
				date: monthDay(dateOf(p.start)),
				temp: night ? p.tmin_c : p.tmax_c,
				icon: wxIcon(p, wx.wcode),
				dir: wx.wdir,
				// Orange only when this period is itself 6+ in.
				kind: precipKind(p.ptype, p.snow_cm ?? 0, (p.snow_cm ?? 0) >= HEAVY_CM),
				barW: `${(((p.snow_cm ?? 0) / max) * 100).toFixed(1)}%`
			};
		});
	});
	const num = (v: number | null | undefined, f: (x: number) => number | null, d = 0) => {
		const x = v === null || v === undefined ? null : f(v);
		return x === null ? '–' : x.toFixed(d);
	};
	const level = (m: number | null) =>
		m === null
			? '–'
			: roundTo(c.height(m) ?? 0, units === 'imperial' ? 50 : 10).toLocaleString('en-US');
	// Snow ratio zones, as on the chart: 0 heavy & wet … 3 dry powder.
	const zoneOf = (v: number) => (v < 9.5 ? 0 : v < 12.5 ? 1 : v < 15.5 ? 2 : 3);
	const ICON_WORD: Record<string, string> = {
		'clear-day': 'Clear',
		'clear-night': 'Clear',
		'partly-day': 'Partly cloudy',
		'partly-night': 'Partly cloudy',
		cloud: 'Cloudy',
		fog: 'Fog',
		rain: 'Rain',
		snow: 'Snow',
		mix: 'Rain and snow',
		thunder: 'Thunderstorms'
	};
</script>

<div class="wrap" use:hscroll>
	<table>
		<thead>
			<tr>
				<th class="dcol"><span class="sr">Day</span></th>
				<th class="l">Temp</th>
				<th class="l snowh">Snow<small>{c.snowUnit}</small></th>
				<th>Snow<small>ratio</small></th>
				<th>Snow level<small>{c.heightUnit}</small></th>
				<th>Precip<small>chance</small></th>
				<th>Precip<small>{c.waterUnit}</small></th>
				<th>Wind<small>{c.speedUnit}</small></th>
				<th>Gust<small>{c.speedUnit}</small></th>
				<th>Cloud<small>cover</small></th>
			</tr>
		</thead>
		<tbody>
			{#each rows as r (r.p.key)}
				<tr class:night={r.night} class:first={r.first}>
					{#if r.first}
						<th class="dcol" scope="row" rowspan={r.span}>
							<button
								class="daybtn"
								onclick={() => onselect?.(r.p)}
								aria-label="Details for {r.day} {r.date}"
							>
								<strong>{r.day}</strong>
								<span>{r.date}</span>
							</button>
						</th>
					{/if}
					<td class="l">
						<button
							class="temp"
							onclick={() => onselect?.(r.p)}
							aria-label="Details for {r.p.label}"
						>
							<span class="num t">{num(r.temp, c.temp)}°</span>
							<WxIcon icon={r.icon} label={`${r.night ? 'Night' : 'Day'}: ${ICON_WORD[r.icon]}`} />
						</button>
					</td>
					<td class="l snow">
						<span class="sc">
							<span class="sbar {r.kind}" aria-hidden="true"></span>
							<span class="num samt" class:zero={!(r.p.snow_cm ?? 0)}
								>{snowNum(r.p.snow_cm, units)}</span
							>
							<span class="track" aria-hidden="true"
								><span class="fill {r.kind}" style:width={r.barW}></span></span
							>
						</span>
					</td>
					<td class="num ratio">
						{#if r.p.slr && (r.p.snow_cm ?? 0) > 0}
							<span class="slr z{zoneOf(r.p.slr)}">{Math.round(r.p.slr)}:1</span>
							<small>{(r.p.quality ?? '').toLowerCase()}</small>
						{:else}–{/if}
					</td>
					<td class="num">{level(r.p.snow_level_min_m)}</td>
					<td class="num">{r.p.pop_max === null ? '–' : `${Math.round(r.p.pop_max)}%`}</td>
					<td class="num">{num(r.p.water_mm, c.water, c.waterDigits)}</td>
					<td class="num">{compass(r.dir)}&thinsp;{num(r.p.wind_max_kmh, c.speed)}</td>
					<td class="num">{num(r.p.gust_max_kmh, c.speed)}</td>
					<td class="num">{r.p.cloud_mean === null ? '–' : `${Math.round(r.p.cloud_mean)}%`}</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.wrap {
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
		margin: 0 -4px;
	}
	table {
		width: 100%;
		min-width: 760px;
		border-collapse: separate;
		border-spacing: 0;
		font-size: 0.88rem;
		font-variant-numeric: tabular-nums;
	}
	thead th {
		position: sticky;
		top: 0;
		padding: 0 10px 10px;
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--text-3);
		text-align: right;
		vertical-align: bottom;
		line-height: 1.2;
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
		background: var(--surface);
	}
	thead th small {
		display: block;
		font-weight: 500;
		color: var(--text-3);
		opacity: 0.85;
	}
	th.l,
	td.l {
		text-align: left;
	}
	td {
		padding: 9px 10px;
		text-align: right;
		white-space: nowrap;
		border-bottom: 1px solid var(--grid);
		color: var(--text-2);
	}
	tbody tr:hover td {
		background: color-mix(in srgb, var(--accent-soft) 60%, transparent);
	}
	tr.night td {
		background: var(--night);
	}
	tr.first td,
	tr.first th {
		border-top: 1px solid var(--border);
	}
	tbody tr:first-child td,
	tbody tr:first-child th {
		border-top: 0;
	}
	/* The day column stays put while the table scrolls sideways. */
	.dcol {
		position: sticky;
		left: 0;
		z-index: 1;
		width: 64px;
		min-width: 64px;
		background: var(--surface);
		text-align: left;
		vertical-align: middle;
		padding: 0 6px 0 4px;
		border-bottom: 1px solid var(--grid);
		border-right: 1px solid var(--grid);
	}
	thead .dcol {
		z-index: 2;
		border-bottom: 1px solid var(--border);
	}
	.daybtn {
		display: grid;
		gap: 1px;
		border: 0;
		background: none;
		padding: 6px 2px;
		text-align: left;
		cursor: pointer;
		font-size: 0.75rem;
		color: var(--text-3);
	}
	.daybtn strong {
		font-size: 0.95rem;
		font-weight: 600;
		color: var(--text);
	}
	.temp {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		border: 0;
		background: none;
		padding: 0;
		cursor: pointer;
	}
	.t {
		min-width: 2.6em;
		font-size: 0.98rem;
		font-weight: 600;
		color: var(--text);
	}
	td.snow {
		min-width: 170px;
	}
	.sc {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.sbar {
		width: 3px;
		height: 20px;
		border-radius: 2px;
		background: var(--border);
	}
	.samt {
		min-width: 2.4em;
		font-size: 0.98rem;
		font-weight: 600;
		color: var(--text);
	}
	.samt.zero {
		color: var(--text-3);
		font-weight: 400;
	}
	.track {
		flex: 1;
		height: 6px;
		border-radius: 3px;
		background: var(--surface-2);
		overflow: hidden;
		min-width: 60px;
	}
	.fill {
		display: block;
		height: 100%;
		border-radius: 3px;
	}
	.sbar.snow,
	.fill.snow {
		background: var(--snow);
	}
	.sbar.heavy,
	.fill.heavy {
		background: var(--snow-heavy);
	}
	.sbar.mix,
	.fill.mix {
		background: var(--mix);
	}
	.sbar.rain,
	.fill.rain {
		background: var(--rain);
	}
	td.ratio {
		line-height: 1.15;
	}
	td.ratio small {
		display: block;
		font-size: 0.66rem;
		color: var(--text-3);
	}
	.slr {
		display: inline-block;
		padding: 1px 6px;
		border-radius: 6px;
		font-weight: 600;
		color: var(--text);
	}
	.slr.z0 {
		background: color-mix(in srgb, var(--mix) 22%, transparent);
	}
	.slr.z1 {
		background: color-mix(in srgb, var(--snow) 16%, transparent);
	}
	.slr.z2 {
		background: color-mix(in srgb, var(--snow) 30%, transparent);
	}
	.slr.z3 {
		background: color-mix(in srgb, var(--snow) 48%, transparent);
	}
	/* Phones: a shorter snow bar lets the next column peek in, a hint to swipe. */
	@media (max-width: 640px) {
		td.snow {
			min-width: 128px;
		}
		.track {
			min-width: 36px;
		}
	}
	.sr {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
</style>
