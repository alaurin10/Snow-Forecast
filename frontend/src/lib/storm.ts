// The next storm: the first run of snowy periods that adds up to a real amount.
import type { PeriodOut } from './types.gen';

/** A period counts as snowing from 1 cm; a storm needs 5 cm (2 in) in total. */
export const SNOWY_CM = 1;
export const STORM_CM = 5;

export interface Storm {
	first: PeriodOut;
	last: PeriodOut;
	peak: PeriodOut;
	total_cm: number;
	/** Lowest snow level during the storm, metres. */
	snow_level_min_m: number | null;
	periods: number;
}

export function nextStorm(periods: PeriodOut[]): Storm | null {
	let run: PeriodOut[] = [];
	const finish = (): Storm | null => {
		const total = run.reduce((a, p) => a + (p.snow_cm ?? 0), 0);
		if (!run.length || total < STORM_CM) return null;
		const levels = run.map((p) => p.snow_level_min_m).filter((v): v is number => v !== null);
		return {
			first: run[0],
			last: run[run.length - 1],
			peak: run.reduce((a, p) => ((p.snow_cm ?? 0) > (a.snow_cm ?? 0) ? p : a)),
			total_cm: total,
			snow_level_min_m: levels.length ? Math.min(...levels) : null,
			periods: run.length
		};
	};
	for (const p of periods) {
		if ((p.snow_cm ?? 0) >= SNOWY_CM) {
			run.push(p);
			continue;
		}
		const storm = finish();
		if (storm) return storm;
		run = [];
	}
	return finish();
}
