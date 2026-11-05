// Plan a day: sorting the rows for one date.
import type { PlanRow } from './types.gen';
import type { PlanSort } from './prefs.svelte';

/** New snow for the day: the night before plus the day (cm), or null without data. */
export function newSnow(row: PlanRow): number | null {
	const d = row.day;
	if (!d || (d.overnight_cm === null && d.day_cm === null)) return null;
	return (d.overnight_cm ?? 0) + (d.day_cm ?? 0);
}

const byName = (a: PlanRow, b: PlanRow) => a.name.localeCompare(b.name);

/** Rows without a forecast for the date always go last. */
export function sortPlan(rows: PlanRow[], key: PlanSort): PlanRow[] {
	const out = [...rows];
	const snowDesc = (a: PlanRow, b: PlanRow) => (newSnow(b) ?? -1) - (newSnow(a) ?? -1);
	out.sort((a, b) => {
		const missing = Number(a.day === null) - Number(b.day === null);
		if (missing) return missing;
		if (key === 'name') return byName(a, b);
		if (key === 'rating') {
			const r = (b.day?.score ?? 0) - (a.day?.score ?? 0);
			if (r) return r;
		}
		return snowDesc(a, b) || byName(a, b);
	});
	return out;
}
