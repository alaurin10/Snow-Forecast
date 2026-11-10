// Day and night snowfall pairs for the compact bars on the Overview, coloured by
// precipitation type. A day with 15.24 cm (6 in) or more counts as heavy snow.
import type { OverviewPeriod } from './types.gen';
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

const KIND_WORDS: Record<PrecipKind, string> = {
	snow: '',
	heavy: ' (heavy)',
	mix: ' (mixed with rain)',
	rain: ' (mostly rain)',
	none: ''
};

/** The bars in words, for screen readers: "Today 2 in, Thu none, Fri 5 in (mostly rain)". */
export function describeDays(days: DayTotal[], fmt: (cm: number) => string): string {
	return days
		.map((d) => `${d.label} ${d.cm >= 0.1 ? fmt(d.cm) + KIND_WORDS[d.kind] : 'none'}`)
		.join(', ');
}
