<!-- Day by day on a phone: one row per day (sky, high and low, wind, then day and night
     snow), no sideways scrolling. A row opens to its day and night halves; from there the
     hours open as a chart in a popup, so you never leave the list. -->
<script lang="ts">
	import type { HourlyOut, PeriodOut } from '../types.gen';
	import { bucket, EDGES_CM } from '../calendar';
	import { ICON_WORD, periodWeather, wxIcon } from '../periodwx';
	import { compass } from '../conditions';
	import { monthDay, weekday } from '../time';
	import { converters, elevation, snowNum, speed, type UnitSystem } from '../units';
	import WxIcon from './WxIcon.svelte';

	interface Props {
		periods: PeriodOut[];
		hourly: HourlyOut;
		units: UnitSystem;
		/** Open one half-day's details (each model, the ensemble range). */
		onperiod?: (p: PeriodOut) => void;
		/** Open a day's hours as a chart; `start` is the day's first hour. */
		onhourly?: (date: string, start: string) => void;
	}

	let { periods, hourly, units, onperiod, onhourly }: Props = $props();
	const c = $derived(converters(units));
	let open = $state<string | null>(null);

	const WET_MM = 1;
	const half = (p: PeriodOut) => {
		const wx = periodWeather(hourly, p);
		const icon = wxIcon(p, wx.wcode);
		const cm = p.snow_cm ?? 0;
		const rainy = cm < EDGES_CM[0] && (p.rain_mm ?? 0) >= WET_MM;
		return {
			p,
			icon,
			night: p.kind === 'night',
			dir: wx.wdir,
			b: bucket(cm),
			rainy,
			cell: Number(snowNum(cm, units)) > 0 ? snowNum(cm, units) : rainy ? 'rain' : '–',
			note:
				cm >= EDGES_CM[0] && p.slr
					? `${Math.round(p.slr)}:1 · ${(p.quality ?? 'snow').toLowerCase()}`
					: rainy
						? 'too warm for snow'
						: ICON_WORD[icon]
		};
	};
	type Half = ReturnType<typeof half>;

	const days = $derived.by(() => {
		const by: Record<string, { day?: Half; night?: Half }> = {};
		for (const p of periods) {
			const slot = (by[p.date] ??= {});
			if (p.kind === 'night') slot.night = half(p);
			else slot.day = half(p);
		}
		// ISO dates sort in date order.
		const dates = Object.keys(by).sort();
		return dates.map((date) => {
			const { day, night } = by[date];
			const halves = [day, night].filter((x): x is Half => !!x);
			const first = halves[0];
			const windy = halves.reduce((a, x) =>
				(x.p.wind_max_kmh ?? 0) > (a.p.wind_max_kmh ?? 0) ? x : a
			);
			const temps = (f: (p: PeriodOut) => number | null) =>
				halves.map((x) => f(x.p)).filter((v): v is number => v !== null);
			const hi = temps((p) => p.tmax_c);
			const lo = temps((p) => p.tmin_c);
			return {
				date,
				name: first.p.label === 'Today' || first.p.label === 'Tonight' ? 'Today' : weekday(date),
				sub: monthDay(date),
				day,
				night,
				halves,
				icon: first.icon,
				hi: hi.length ? Math.round(c.temp(Math.max(...hi)) ?? 0) : null,
				lo: lo.length ? Math.round(c.temp(Math.min(...lo)) ?? 0) : null,
				wind: `${compass(windy.dir)} ${speed(windy.p.wind_max_kmh, units)}`,
				start: first.p.start
			};
		});
	});
	const pct = (v: number | null) => (v === null ? '–' : `${Math.round(v)}%`);
</script>

<div class="head" aria-hidden="true">
	<span class="grow">High / low, wind</span>
	<span class="cellh">Day</span>
	<span class="cellh">Night</span>
	<span class="chev"></span>
</div>
<ul class="days">
	{#each days as d (d.date)}
		{@const isOpen = open === d.date}
		<li>
			<button class="row" aria-expanded={isOpen} onclick={() => (open = isOpen ? null : d.date)}>
				<span class="when"><strong>{d.name}</strong><small>{d.sub}</small></span>
				<WxIcon icon={d.icon} size={24} label={ICON_WORD[d.icon]} />
				<span class="grow temps">
					<span class="num">{d.hi ?? '–'}° <span class="faint">/ {d.lo ?? '–'}°</span></span>
					<small>{d.wind}</small>
				</span>
				{#each [d.day, d.night] as h, i (i)}
					{#if h}
						<span class="heat cell b{h.b}" class:rainy={h.rainy}>{h.cell}</span>
					{:else}
						<span class="cell"></span>
					{/if}
				{/each}
				<svg
					class="chev"
					class:up={isOpen}
					viewBox="0 0 24 24"
					width="16"
					height="16"
					aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg
				>
			</button>
			{#if isOpen}
				<div class="halves">
					{#each d.halves as h (h.p.key)}
						<button class="hcard" class:night={h.night} onclick={() => onperiod?.(h.p)}>
							<span class="htop">
								<strong>{h.night ? 'Night' : 'Day'}</strong>
								<WxIcon icon={h.icon} size={20} label={ICON_WORD[h.icon]} />
							</span>
							<span class="hbig num"
								>{h.rainy
									? c.water(h.p.rain_mm)?.toFixed(c.waterDigits)
									: snowNum(h.p.snow_cm, units)}
								<small>{h.rainy ? `${c.waterUnit} of rain` : `${c.snowUnit} of snow`}</small></span
							>
							<span class="hnote">{h.note}</span>
							<span class="stats">
								<span
									><small>{h.night ? 'Low' : 'High'}</small>{Math.round(
										c.temp(h.night ? h.p.tmin_c : h.p.tmax_c) ?? 0
									)}{c.tempUnit}</span
								>
								<span><small>Chance</small>{pct(h.p.pop_max)}</span>
								<span class="wide"
									><small>Wind</small>{compass(h.dir)}
									{speed(h.p.wind_max_kmh, units)}, gusts {speed(h.p.gust_max_kmh, units)}</span
								>
								<span class="wide"
									><small>Snow level</small>{elevation(h.p.snow_level_min_m, units)}</span
								>
							</span>
							<span class="more">Each model ›</span>
						</button>
					{/each}
				</div>
				<button class="hourly" onclick={() => onhourly?.(d.date, d.start)}>
					<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
						><path d="M4 19V5M4 19h16M8 15v-4M12 15V8M16 15v-6" /></svg
					>
					Hour by hour
				</button>
			{/if}
		</li>
	{/each}
</ul>

<style>
	.head,
	.row {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.head {
		font-size: 0.7rem;
		color: var(--text-3);
		padding: 0 0 4px 82px;
	}
	.grow {
		flex: 1 1 auto;
		min-width: 0;
	}
	.cellh,
	.cell {
		flex: 0 0 48px;
		text-align: center;
	}
	.chev {
		flex: 0 0 16px;
		fill: none;
		stroke: var(--text-3);
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.chev.up {
		transform: rotate(180deg);
	}
	.days {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		border-top: 1px solid var(--grid);
	}
	.row {
		width: 100%;
		min-height: 56px;
		padding: 0;
		border: 0;
		background: none;
		text-align: left;
		cursor: pointer;
	}
	.when {
		flex: 0 0 50px;
		display: grid;
	}
	.when strong {
		font-size: 0.93rem;
		font-weight: 600;
	}
	small {
		font-size: 0.72rem;
		color: var(--text-3);
	}
	.temps {
		display: grid;
		font-size: 0.93rem;
		white-space: nowrap;
	}
	.temps small {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.cell {
		height: 34px;
		font-size: 0.85rem;
	}
	.halves {
		display: flex;
		gap: 8px;
	}
	.hcard {
		flex: 1 1 0;
		min-width: 0;
		display: grid;
		gap: 4px;
		align-content: start;
		padding: 10px 12px;
		border-radius: 14px;
		border: 1px solid var(--border);
		background: var(--surface-2);
		text-align: left;
		cursor: pointer;
	}
	.hcard.night {
		background: color-mix(in srgb, var(--surface-2) 55%, var(--bg));
	}
	.htop {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 0.78rem;
		color: var(--accent-ink);
	}
	.hbig {
		font-size: 1.6rem;
		font-weight: 600;
		line-height: 1.05;
		letter-spacing: -0.02em;
	}
	.hbig small {
		font-family: var(--font-ui);
		font-weight: 400;
		letter-spacing: 0;
		color: var(--text-2);
	}
	.hnote {
		font-size: 0.78rem;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 6px 8px;
		margin-top: 6px;
		padding-top: 8px;
		border-top: 1px solid var(--border);
		font-size: 0.82rem;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.stats span {
		display: grid;
	}
	.stats .wide {
		grid-column: 1 / -1;
	}
	.more {
		margin-top: 4px;
		font-size: 0.75rem;
		color: var(--text-3);
	}
	.hourly {
		width: 100%;
		height: 44px;
		margin: 8px 0 12px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		border-radius: 14px;
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--accent-ink);
		font-size: 0.88rem;
		font-weight: 500;
		cursor: pointer;
	}
	.hourly svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
</style>
