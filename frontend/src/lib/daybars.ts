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
