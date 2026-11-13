// Storm cycles across locations: each location's storms (runs of snowy periods that
// add up to a real amount), grouped into one cycle when their dates overlap.
import type { OverviewPeriod, OverviewRow } from './types.gen';
import { SNOWY_CM, STORM_CM } from './storm';

export interface LocationStorm {
	id: string;
	name: string;
	start: string;
	end: string;
	total_cm: number;
	/** Rain or mixed periods fell during it. */
	wet: boolean;
}

export interface StormCycle {
	start: string;
	end: string;
	/** Most snow any location gets in this cycle (cm). */
	max_cm: number;
	locations: LocationStorm[];
}

/** Every storm in one location's periods, in order. */
export function locationStorms(
	id: string,
	name: string,
	periods: OverviewPeriod[]
): LocationStorm[] {
	const out: LocationStorm[] = [];
	let run: OverviewPeriod[] = [];
	const close = () => {
		const total = run.reduce((a, p) => a + (p.snow_cm ?? 0), 0);
		if (run.length && total >= STORM_CM)
			out.push({
				id,
				name,
				start: run[0].date,
				end: run[run.length - 1].date,
				total_cm: total,
				wet: run.some((p) => p.ptype === 'rain' || p.ptype === 'mix')
			});
		run = [];
	};
	for (const p of periods) {
		if ((p.snow_cm ?? 0) >= SNOWY_CM) run.push(p);
		else close();
	}
	close();
	return out;
}

/** Storms from every location, merged into cycles where their dates overlap. */
export function stormCycles(rows: OverviewRow[]): StormCycle[] {
	const storms = rows
		.flatMap((r) => locationStorms(r.id, r.name, r.periods ?? []))
		.sort((a, b) => a.start.localeCompare(b.start));
	const cycles: StormCycle[] = [];
	for (const s of storms) {
		const last = cycles.at(-1);
		if (last && s.start <= last.end) {
			last.locations.push(s);
			if (s.end > last.end) last.end = s.end;
			last.max_cm = Math.max(last.max_cm, s.total_cm);
		} else cycles.push({ start: s.start, end: s.end, max_cm: s.total_cm, locations: [s] });
	}
	for (const c of cycles) {
		c.locations = foldByLocation(c.locations);
		c.max_cm = Math.max(...c.locations.map((l) => l.total_cm));
		c.locations.sort((a, b) => b.total_cm - a.total_cm);
	}
	return cycles;
}

/** One entry per location: a location can storm twice in one cycle (its two storms
 *  both overlap a longer one elsewhere), and the lists showing a cycle are keyed by
 *  location id. Two storms become one spanning both, with their totals summed. */
function foldByLocation(storms: LocationStorm[]): LocationStorm[] {
	const byId = new Map<string, LocationStorm>();
	for (const s of storms) {
		const had = byId.get(s.id);
		if (!had) byId.set(s.id, { ...s });
		else {
			if (s.start < had.start) had.start = s.start;
			if (s.end > had.end) had.end = s.end;
			had.total_cm += s.total_cm;
			had.wet ||= s.wet;
		}
	}
	return [...byId.values()];
}
