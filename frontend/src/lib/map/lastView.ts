// The full map's last view (centre, zoom, tilt, turn), kept for this tab's session, so
// leaving the map for a spot's forecast and coming back finds it where it was: look at a
// point's forecast, go back, tap the next one. Storage can be missing or refuse (private
// windows, blocked site data): then the map opens as it would anyway.

export interface MapViewState {
	lng: number;
	lat: number;
	zoom: number;
	bearing: number;
	pitch: number;
}

const KEY = 'sw.mapView';
/** A spot's Map button opens on its point; a kept view this close is used instead. */
export const NEAR_KM = 25;

export function saveView(v: MapViewState): void {
	try {
		sessionStorage.setItem(KEY, JSON.stringify(v));
	} catch {
		// not kept: the map opens as usual next time
	}
}

export function lastView(): MapViewState | null {
	try {
		const v = JSON.parse(sessionStorage.getItem(KEY) ?? 'null') as Partial<MapViewState> | null;
		if (!v) return null;
		const nums = [v.lng, v.lat, v.zoom, v.bearing, v.pitch];
		if (!nums.every((n) => typeof n === 'number' && Number.isFinite(n))) return null;
		return v as MapViewState;
	} catch {
		return null;
	}
}

/** Whether a kept view is centred near a point (km, roughly). */
export function near(v: MapViewState, p: { lat: number; lon: number }, km = NEAR_KM): boolean {
	const dy = (v.lat - p.lat) * 111.2;
	const dx = (v.lng - p.lon) * 111.2 * Math.cos((p.lat * Math.PI) / 180);
	return Math.hypot(dx, dy) <= km;
}
