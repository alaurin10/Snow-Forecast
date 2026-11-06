// Day and night snowfall pairs for the compact bars on the Overview, coloured by
// precipitation type. A day with 15.24 cm (6 in) or more counts as heavy snow.
import type { OverviewPeriod, PeriodOut } from './types.gen';
import { weekday } from './time';

export const HEAVY_CM = 15.24;

export type PrecipKind = 'snow' | 'heavy' | 'mix' | 'rain' | 'none';

export interface Half {
	cm: number;
	kind: PrecipKind;
}

export interface DayPair {
	date: string;
	/** Short weekday, e.g. "Th", "Sa". */
	short: string;
	weekend: boolean;
	day: Half | null;
	night: Half | null;
	total: number;
}

const SHORT: Record<string, string> = {
	Sun: 'Su',
	Mon: 'M',
	Tue: 'Tu',
	Wed: 'W',
	Thu: 'Th',
	Fri: 'F',
	Sat: 'Sa'
};

/** The colour class of one half-day: snow turns heavy on a 6+ in day; amounts with no type count as snow. */
export function precipKind(ptype: string | undefined, cm: number, heavyDay: boolean): PrecipKind {
	if (ptype === 'rain') return 'rain';
	if (ptype === 'mix') return 'mix';
	if (ptype === 'snow' || cm > 0) return heavyDay ? 'heavy' : 'snow';
	return 'none';
}

/** Group periods into calendar days (day then night), up to `limit` days. */
export function dayPairs(periods: OverviewPeriod[], limit = 10): DayPair[] {
	const byDate = new Map<string, { day?: OverviewPeriod; night?: OverviewPeriod }>();
	for (const p of periods) {
		const slot = byDate.get(p.date) ?? {};
		if (p.kind === 'night') slot.night = p;
		else slot.day = p;
		byDate.set(p.date, slot);
	}
	return [...byDate.entries()].slice(0, limit).map(([date, { day, night }]) => {
		const total = (day?.snow_cm ?? 0) + (night?.snow_cm ?? 0);
		const heavy = total >= HEAVY_CM;
		const half = (p?: OverviewPeriod): Half | null =>
			p ? { cm: p.snow_cm ?? 0, kind: precipKind(p.ptype, p.snow_cm ?? 0, heavy) } : null;
		const wd = weekday(date);
		return {
			date,
			short: SHORT[wd],
			weekend: wd === 'Sat' || wd === 'Sun',
			day: half(day),
			night: half(night),
			total
		};
	});
}

export interface DayTotal {
	date: string;
	/** "Today", or a short weekday such as "Thu". */
	label: string;
	weekend: boolean;
	/** Snow for the two periods in this bar (cm). */
	cm: number;
	kind: PrecipKind;
}

/**
 * The next `days` days as bars that add up to the "next N days" total: the first
 * 2 × `days` periods, paired in order. A forecast that starts in the evening pairs
 * each night with the next day, which is the snow you ski on that day.
 */
export function dailyTotals(periods: OverviewPeriod[], days = 5): DayTotal[] {
	const out: DayTotal[] = [];
	for (let i = 0; i < days * 2 && i < periods.length; i += 2) {
		const pair = periods.slice(i, i + 2);
		const cm = pair.reduce((a, p) => a + (p.snow_cm ?? 0), 0);
		const heavy = cm >= HEAVY_CM;
		const byKind: Partial<Record<PrecipKind, number>> = {};
		for (const p of pair) {
			const k = precipKind(p.ptype, p.snow_cm ?? 0, false);
			if (k !== 'none') byKind[k] = (byKind[k] ?? 0) + Math.max(p.snow_cm ?? 0, 0.001);
		}
		const top = (Object.entries(byKind) as [PrecipKind, number][]).sort((a, b) => b[1] - a[1])[0];
		let kind: PrecipKind = top ? top[0] : 'none';
		if (kind === 'snow' && heavy) kind = 'heavy';
		const day = pair.find((p) => p.kind !== 'night') ?? pair[0];
		const wd = weekday(day.date);
		out.push({
			date: day.date,
			label: day.label === 'Today' ? 'Today' : wd,
			weekend: wd === 'Sat' || wd === 'Sun',
			cm,
			kind
		});
	}
	return out;
}

export interface ForecastDay {
	date: string;
	label: string;
	day: PeriodOut | null;
	night: PeriodOut | null;
	/** Snow, day plus night (cm). */
	cm: number;
	dayKind: PrecipKind;
	nightKind: PrecipKind;
	tmax: number | null;
	tmin: number | null;
	gust: number | null;
	snowLevel: number | null;
	/** "Rain" or "Mixed" when either half isn't snow. */
	note: string | null;
	/** Rain, day plus night (mm). */
	rain_mm: number;
}

/** The snapshot's day and night periods grouped by calendar date, for the day-by-day list. */
export function forecastDays(periods: PeriodOut[]): ForecastDay[] {
	const byDate = new Map<string, { day?: PeriodOut; night?: PeriodOut }>();
	for (const p of periods) {
		const slot = byDate.get(p.date) ?? {};
		if (p.kind === 'night') slot.night = p;
		else slot.day = p;
		byDate.set(p.date, slot);
	}
	const pick = (xs: (number | null | undefined)[], f: (...v: number[]) => number) => {
		const v = xs.filter((x): x is number => x !== null && x !== undefined);
		return v.length ? f(...v) : null;
	};
	return [...byDate.entries()].map(([date, { day, night }]) => {
		const cm = (day?.snow_cm ?? 0) + (night?.snow_cm ?? 0);
		const heavy = cm >= HEAVY_CM;
		const halves = [day, night].filter((p): p is PeriodOut => !!p);
		const types = halves.map((p) => p.ptype);
		const note = types.includes('rain') ? 'Rain' : types.includes('mix') ? 'Mixed' : null;
		const first = halves[0];
		return {
			date,
			label: first?.label === 'Today' || first?.label === 'Tonight' ? 'Today' : weekday(date),
			day: day ?? null,
			night: night ?? null,
			cm,
			dayKind: day ? precipKind(day.ptype, day.snow_cm ?? 0, heavy) : 'none',
			nightKind: night ? precipKind(night.ptype, night.snow_cm ?? 0, heavy) : 'none',
			tmax: pick([day?.tmax_c, night?.tmax_c], Math.max),
			tmin: pick([day?.tmin_c, night?.tmin_c], Math.min),
			gust: pick([day?.gust_max_kmh, night?.gust_max_kmh], Math.max),
			snowLevel: pick([day?.snow_level_min_m, night?.snow_level_min_m], Math.min),
			note,
			rain_mm: (day?.rain_mm ?? 0) + (night?.rain_mm ?? 0)
		};
	});
}
