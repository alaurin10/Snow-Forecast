// Many locations (milestone 4: up to ~50) on the Overview and Calendar: grouped by
// region (the state or province), with a filter and favourites kept in this browser.
// Storage can be missing or refuse (private windows, blocked site data): then there are
// simply no favourites.

/** Lists this long or longer get the filter, favourites and region groups. */
export const MANY = 9;

const STATES: Record<string, string> = {
	AK: 'Alaska',
	AZ: 'Arizona',
	CA: 'California',
	CO: 'Colorado',
	ID: 'Idaho',
	MT: 'Montana',
	NM: 'New Mexico',
	NV: 'Nevada',
	OR: 'Oregon',
	UT: 'Utah',
	WA: 'Washington',
	WY: 'Wyoming',
	AB: 'Alberta',
	BC: 'British Columbia',
	YT: 'Yukon'
};

/** The group a location's region falls in: its state or province ("Snoqualmie Pass,
 *  WA" or "WA Cascades" → Washington; "Washington" stays), else the region itself,
 *  else "Other". */
export function regionGroup(region: string | null | undefined): string {
	const r = (region ?? '').trim();
	if (!r) return 'Other';
	const last = r.split(',').at(-1)!.trim();
	if (STATES[last.toUpperCase()]) return STATES[last.toUpperCase()];
	// "WA Cascades", "BC Interior (Selkirks)": a leading code.
	const first = r.split(/\s+/)[0];
	if (first === first.toUpperCase() && STATES[first]) return STATES[first];
	const named = Object.values(STATES).find((n) => n.toLowerCase() === last.toLowerCase());
	return named ?? last;
}

export interface Group<T> {
	label: string;
	rows: T[];
}

interface Grouped {
	id: string;
	name: string;
	region: string;
}

/** Rows matching the filter (name or region, any case). */
export function filterRows<T>(rows: T[], q: string, of: (t: T) => Grouped): T[] {
	const words = q.toLowerCase().split(/\s+/).filter(Boolean);
	if (!words.length) return rows;
	return rows.filter((t) => {
		const r = of(t);
		const hay = `${r.name} ${r.region} ${regionGroup(r.region)}`.toLowerCase();
		return words.every((w) => hay.includes(w));
	});
}

/** Favourites first, then each region in the order its first row comes (so the Manage
 *  order, or most snow first, carries through), rows in their order within. */
export function groupRows<T>(
	rows: T[],
	favs: ReadonlySet<string>,
	of: (t: T) => Grouped
): Group<T>[] {
	const out: Group<T>[] = [];
	const fav = rows.filter((t) => favs.has(of(t).id));
	if (fav.length) out.push({ label: 'Favourites', rows: fav });
	// A plain list of groups (not a Map: this module also holds runes state).
	const by: Group<T>[] = [];
	for (const t of rows) {
		if (favs.has(of(t).id)) continue;
		const label = regionGroup(of(t).region);
		let g = by.find((x) => x.label === label);
		if (!g) by.push((g = { label, rows: [] }));
		g.rows.push(t);
	}
	out.push(...by);
	return out;
}

const KEY = 'sw.favourites';

function load(): string[] {
	try {
		const raw = JSON.parse(localStorage.getItem(KEY) ?? '[]') as unknown;
		return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string') : [];
	} catch {
		return [];
	}
}

class Favourites {
	ids = $state<string[]>(load());
	set = $derived(new Set(this.ids));

	has(id: string): boolean {
		return this.set.has(id);
	}

	toggle(id: string): void {
		this.ids = this.has(id) ? this.ids.filter((x) => x !== id) : [...this.ids, id];
		try {
			localStorage.setItem(KEY, JSON.stringify(this.ids));
		} catch {
			// storage full or blocked: kept for this visit only
		}
	}
}

export const favourites = new Favourites();
