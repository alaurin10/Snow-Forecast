// "Save as location" on a spot's page opens Manage at /admin?spot=lat,lon&name=…: the
// "Add a backcountry zone" form, named after the spot, its map zoomed in on the point
// with the point as the mid pin, for the owner to place the low (trailhead) and high
// points; auto-detect then fills in each pin's elevation and the rest.

export interface SpotDraft {
	name: string;
	lat: number;
	lon: number;
}

export function spotDraft(params: URLSearchParams): SpotDraft | null {
	const at = (params.get('spot') ?? '').split(',').map(Number);
	if (at.length !== 2 || !at.every(Number.isFinite)) return null;
	const [lat, lon] = at;
	if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
	return { name: (params.get('name') ?? '').slice(0, 80), lat, lon };
}
