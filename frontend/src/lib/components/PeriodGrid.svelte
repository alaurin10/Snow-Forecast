<!-- Day by day on wider screens: the phone's day rows with every column there is room for.
     One row per day: the day and its rating, sky, high and low, the day and night snow as
     cells on the snow ramp, then snow ratio, snow level, chance and amount of
     precipitation, wind, gust and cloud, each showing the day over the night. A snow cell
     opens that half-day's details. Pointing at a row shades that day on the chart, and the
     row of the day under the chart's pointer lights up. -->
<script lang="ts">
	import { hscroll } from '../hscroll';
	import type { DayOut, HourlyOut, PeriodOut } from '../types.gen';
	import { bucket, EDGES_CM } from '../calendar';
	import { ICON_WORD, periodWeather, wxIcon } from '../periodwx';
	import { compass } from '../conditions';
	import { monthDay, weekday } from '../time';
	import { converters, roundTo, snowNum, type UnitSystem } from '../units';
	import WxIcon from './WxIcon.svelte';

	interface Props {
		periods: PeriodOut[];
		hourly: HourlyOut;
		units: UnitSystem;
		/** Ski-day ratings, by date. */
		days?: DayOut[];
		onselect?: (p: PeriodOut) => void;
		/** The day to light up (the one under the chart's pointer). */
		focusDate?: string | null;
		/** The day under the pointer here, or null when it leaves the table. */
		onhoverdate?: (date: string | null) => void;
	}

	let {
		periods,
		hourly,
		units,
		days = [],
		onselect,
		focusDate = null,
		onhoverdate
	}: Props = $props();
	const c = $derived(converters(units));
	const WET_MM = 1;

	const half = (p: PeriodOut | undefined) => {
		if (!p) return null;
		const cm = p.snow_cm ?? 0;
		const rainy = cm < EDGES_CM[0] && (p.rain_mm ?? 0) >= WET_MM;
		const shown = Number(snowNum(cm, units)) > 0;
		return {
			p,
			b: shown ? bucket(cm) : 0,
			rainy,
			cell: shown ? snowNum(cm, units) : rainy ? 'rain' : '–',
			wx: periodWeather(hourly, p)
		};
	};
	const rows = $derived.by(() => {
		const dates = [...new Set(periods.map((p) => p.date))];
		return dates.map((date) => {
			const day = periods.find((p) => p.date === date && p.kind === 'day');
			const night = periods.find((p) => p.date === date && p.kind === 'night');
			const lead = day ?? night!;
			const wx = periodWeather(hourly, lead);
			const rating = days.find((d) => d.date === date)?.rating ?? '';
			return {
				date,
				name: lead.label === 'Today' || lead.label === 'Tonight' ? 'Today' : weekday(date),
				md: monthDay(date),
				rating,
				icon: wxIcon(lead, wx.wcode),
				hi: day?.tmax_c ?? null,
				lo: night?.tmin_c ?? day?.tmin_c ?? null,
				d: half(day),
				n: half(night)
			};
		});
	});
	const num = (v: number | null | undefined, f: (x: number) => number | null, digits = 0) => {
		const x = v === null || v === undefined ? null : f(v);
		return x === null ? '–' : x.toFixed(digits);
	};
	const level = (m: number | null | undefined) =>
		m === null || m === undefined
			? '–'
			: roundTo(c.height(m) ?? 0, units === 'imperial' ? 50 : 10).toLocaleString('en-US');
	type Half = ReturnType<typeof half>;
	const cols: { name: string; sub: string; v: (h: NonNullable<Half>) => string }[] = $derived([
		{
			name: 'Snow ratio',
			sub: '',
			v: (h) => (h.p.slr && (h.p.snow_cm ?? 0) > 0 ? `${Math.round(h.p.slr)}:1` : '–')
		},
		{ name: 'Snow level', sub: c.heightUnit, v: (h) => level(h.p.snow_level_min_m) },
		{
			name: 'Chance',
			sub: 'precip',
			v: (h) => (h.p.pop_max === null ? '–' : `${Math.round(h.p.pop_max)}%`)
		},
		{
			name: 'Precip',
			sub: c.waterUnit,
			v: (h) => num(h.p.water_mm, c.water, c.waterDigits)
		},
		{
			name: 'Wind',
			sub: c.speedUnit,
			v: (h) => `${compass(h.wx.wdir)} ${num(h.p.wind_max_kmh, c.speed)}`
		},
		{ name: 'Gust', sub: c.speedUnit, v: (h) => num(h.p.gust_max_kmh, c.speed) },
		{
			name: 'Cloud',
			sub: 'cover',
			v: (h) => (h.p.cloud_mean === null ? '–' : `${Math.round(h.p.cloud_mean)}%`)
		}
	]);
	const RATE_CLASS: Record<string, string> = { Great: 'great', Good: 'good', Fair: 'fair' };
</script>

<div class="wrap" use:hscroll>
	<div class="table" role="table" aria-label="Day by day">
		<div class="row head" role="row">
			<span role="columnheader">Day</span>
			<span role="columnheader"><span class="sr-only">Sky</span></span>
			<span role="columnheader">High / low</span>
			<span role="columnheader" class="c">Snow, {c.snowUnit}<small>day · night</small></span>
			{#each cols as k (k.name)}
				<span role="columnheader" class="r">{k.name}<small>{k.sub || ' '}</small></span>
			{/each}
		</div>
		{#each rows as r (r.date)}
			<div
				class="row"
				class:on={focusDate === r.date}
				role="row"
				tabindex="-1"
				onpointerenter={() => onhoverdate?.(r.date)}
				onpointerleave={() => onhoverdate?.(null)}
			>
				<span role="cell" class="day">
					<strong>{r.name}</strong>
					<small
						>{r.md}{#if r.rating}&ensp;<b class={RATE_CLASS[r.rating] ?? 'poor'}>{r.rating}</b
							>{/if}</small
					>
				</span>
				<span role="cell" class="sky">
					<WxIcon icon={r.icon} label={ICON_WORD[r.icon]} />
				</span>
				<span role="cell" class="num temp"
					><strong>{num(r.hi, c.temp)}°</strong> <span>/ {num(r.lo, c.temp)}°</span></span
				>
				<span role="cell" class="cells">
					{#each [r.d, r.n] as h, k (k)}
						{#if h}
							<button
								class="heat b{h.b}"
								class:rainy={h.rainy}
								class:word={h.cell === 'rain'}
								onclick={() => onselect?.(h.p)}
								aria-label="{r.name} {k ? 'night' : 'day'}: {h.cell === '–'
									? 'no snow'
									: h.cell === 'rain'
										? 'rain'
										: `${h.cell} ${c.snowUnit} of snow`}. Details">{h.cell}</button
							>
						{:else}
							<span class="heat b0 empty" aria-hidden="true"></span>
						{/if}
					{/each}
				</span>
				{#each cols as k (k.name)}
					<span role="cell" class="num r stack"
						><span>{r.d ? k.v(r.d) : '–'}</span><span class="night">{r.n ? k.v(r.n) : '–'}</span
						></span
					>
				{/each}
			</div>
		{/each}
	</div>
</div>

<style>
	.wrap {
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
	}
	.table {
		min-width: 860px;
		display: grid;
	}
	.row {
		display: grid;
		grid-template-columns: 108px 34px 86px 122px repeat(7, minmax(0, 1fr));
		align-items: center;
		gap: 8px;
		padding: 7px 10px;
		min-height: 58px;
		border-top: 1px solid var(--grid);
		border-radius: 14px;
		transition: background-color var(--ease);
	}
	.row:not(.head):hover,
	.row.on {
		background: var(--hover);
	}
	.row.head {
		min-height: 0;
		padding-bottom: 8px;
		border-top: 0;
		align-items: end;
		font-size: 0.76rem;
		font-weight: 600;
		color: var(--text-2);
	}
	.head small {
		display: block;
		font-weight: 400;
		color: var(--text-3);
	}
	.c {
		text-align: center;
	}
	.r {
		text-align: right;
	}
	.day strong {
		display: block;
		font-size: 0.98rem;
		font-weight: 600;
	}
	.day small {
		font-size: 0.78rem;
		color: var(--text-2);
	}
	.day b {
		font-weight: 600;
		color: var(--text-3);
	}
	.day b.great {
		color: var(--accent);
	}
	.day b.good {
		color: var(--text);
	}
	.day b.fair {
		color: var(--text-2);
	}
	.sky {
		display: grid;
		place-items: center;
		color: var(--text-2);
	}
	.temp {
		font-size: 0.98rem;
		white-space: nowrap;
	}
	.temp strong {
		font-weight: 600;
	}
	.temp span {
		color: var(--text-2);
	}
	.cells {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 3px;
	}
	.cells .heat {
		height: 38px;
		border: 0;
		font-size: 0.95rem;
		cursor: pointer;
		transition: transform 200ms cubic-bezier(0.3, 1.6, 0.5, 1);
	}
	.cells .heat:active {
		transform: scale(0.95);
	}
	.cells > :first-child {
		border-radius: 12px 4px 4px 12px;
	}
	.cells > :last-child {
		border-radius: 4px 12px 12px 4px;
	}
	.cells .word {
		font-family: var(--font-ui);
		font-size: 0.8rem;
		font-weight: 600;
	}
	.cells .empty {
		height: 38px;
	}
	.stack {
		display: grid;
		gap: 1px;
		font-size: 0.9rem;
		line-height: 1.3;
		white-space: nowrap;
	}
	.stack .night {
		color: var(--text-2);
	}
</style>
