// The last few spots (points tapped on the map for a full forecast), kept in this
// browser only, for the Overview and the location palette. Storage can be missing or
// refuse (private windows, blocked site data): then there are simply none.

export interface RecentSpot {
	lat: number;
	lon: number;
	name: string;
	elev_m: number;
	at: number; // when it was last opened (ms)
}

const KEY = 'sw.recentSpots';
export const MAX_RECENT = 10;

export function recentSpots(): RecentSpot[] {
	try {
		const raw = JSON.parse(localStorage.getItem(KEY) ?? '[]') as unknown;
		if (!Array.isArray(raw)) return [];
		return raw
			.filter(
				(s): s is RecentSpot =>
					!!s &&
					typeof s.lat === 'number' &&
					typeof s.lon === 'number' &&
					typeof s.name === 'string'
			)
			.slice(0, MAX_RECENT);
	} catch {
		return [];
	}
}

const same = (a: { lat: number; lon: number }, b: { lat: number; lon: number }) =>
	Math.abs(a.lat - b.lat) < 0.0005 && Math.abs(a.lon - b.lon) < 0.0005;

/** Put a spot at the top (once), keeping the newest MAX_RECENT. */
export function rememberSpot(spot: Omit<RecentSpot, 'at'>, now = Date.now()): RecentSpot[] {
	const list = [{ ...spot, at: now }, ...recentSpots().filter((s) => !same(s, spot))].slice(
		0,
		MAX_RECENT
	);
	try {
		localStorage.setItem(KEY, JSON.stringify(list));
	} catch {
		// storage full or blocked: the list just isn't kept
	}
	return list;
}

export function forgetSpots(): void {
	try {
		localStorage.removeItem(KEY);
	} catch {
		// nothing to do
	}
}

/** The spot page's query for a point, after `resolve('/spot')`. */
export const spotSearch = (lat: number, lon: number) =>
	`?lat=${lat.toFixed(3)}&lon=${lon.toFixed(3)}`;
