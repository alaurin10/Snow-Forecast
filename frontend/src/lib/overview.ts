import type { OverviewRow } from './types.gen';
import type { KindFilter, SortKey } from './prefs.svelte';

/** Filter by kind and sort; locations without data sink to the bottom. */
export function arrange(rows: OverviewRow[], sort: SortKey, kind: KindFilter): OverviewRow[] {
	const kept = rows.filter((r) => kind === 'all' || r.kind === kind);
	if (sort === 'name') return [...kept].sort((a, b) => a.name.localeCompare(b.name));
	const key = (r: OverviewRow): number | null =>
		sort === 'next5'
			? (r.next5_cm ?? null)
			: sort === 'd6_10'
				? (r.d6_10_cm ?? null)
				: (r.last24_cm ?? null);
	return [...kept].sort((a, b) => {
		const ka = key(a);
		const kb = key(b);
		if (ka === null && kb === null) return a.name.localeCompare(b.name);
		if (ka === null) return 1;
		if (kb === null) return -1;
		return kb - ka || a.name.localeCompare(b.name);
	});
}
