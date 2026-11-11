// Which wind the map's wind-effect layer uses: the loading rose of the nearest saved
// location (snowfall × ridge wind by sector, from its forecast).
import type { MapWindLocation, MapWindOut, RoseOut } from '../types.gen';
import { transport } from './terrain/wind';

/** Further than this from every location, its wind says little about the slopes on screen. */
export const WIND_RANGE_KM = 40;

export const WIND_WINDOWS = [
	{ id: 'past48', label: 'Last 48 h' },
	{ id: 'next24', label: 'Next 24 h' },
	{ id: 'next72', label: 'Next 72 h' }
] as const;
export type WindWindow = (typeof WIND_WINDOWS)[number]['id'];

export function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
	const rad = Math.PI / 180;
	const a =
		Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
		Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
	return 12742 * Math.asin(Math.sqrt(a));
}

export interface WindSource {
	location: MapWindLocation;
	km: number;
	/** Missing when the location's forecast is older than this layer. */
	rose: RoseOut | null;
	/** How much snow the wind could move, 0 to 1 (0: the layer stays clear). */
	scale: number;
}

/** The nearest location's rose for a window, if one is within range of a point. */
export function windSource(
	data: MapWindOut | null,
	lat: number,
	lon: number,
	window: WindWindow
): WindSource | null {
	let best: { location: MapWindLocation; km: number } | null = null;
	for (const location of data?.locations ?? []) {
		const km = distanceKm(lat, lon, location.lat, location.lon);
		if (km <= WIND_RANGE_KM && (!best || km < best.km)) best = { location, km };
	}
	if (!best || !data) return null;
	const rose = best.location.roses.find((r) => r.window === window) ?? null;
	const scale = rose
		? transport({
				snowCm: rose.snow_cm,
				meanKmh: rose.mean_kmh ?? null,
				minSnowCm: data.min_snow_cm,
				minWindKmh: data.min_wind_kmh
			})
		: 0;
	return { ...best, rose, scale };
}
