// Which wind the map's wind-effect layer uses: the loading rose of the nearest saved
// location (snowfall × ridge wind by sector, from its forecast); away from every location,
// the rose the server works out from the map's own forecast at that spot (/api/map/point:
// its precipitation timeline and the ridge-level wind), for the next 24 and 72 hours.
import type { MapWindLocation, MapWindOut, PointOut, RoseOut } from '../types.gen';
import { transport } from './terrain/wind';

/** Further than this from every location, its wind says little about the slopes on screen. */
export const WIND_RANGE_KM = 40;
/** The map's forecast at a spot stands for the view within this distance of it. */
export const POINT_RANGE_KM = 10;

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
	/** From the map's own forecast at the spot, not a saved location's. */
	model?: boolean;
}

/**
 * The nearest location's rose for a window, if one is within range of a point; else the
 * map's own forecast there, when `point` (from /api/map/point) is near enough.
 */
export function windSource(
	data: MapWindOut | null,
	lat: number,
	lon: number,
	window: WindWindow,
	point: PointOut | null = null
): WindSource | null {
	let best: { location: MapWindLocation; km: number } | null = null;
	for (const location of data?.locations ?? []) {
		const km = distanceKm(lat, lon, location.lat, location.lon);
		if (km <= WIND_RANGE_KM && (!best || km < best.km)) best = { location, km };
	}
	if (!best && point) return pointSource(point, lat, lon, window);
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

/** The map's forecast at a spot as a wind source (no rose for the past 48 hours). */
export function pointSource(
	point: PointOut,
	lat: number,
	lon: number,
	window: WindWindow
): WindSource | null {
	const km = distanceKm(lat, lon, point.lat, point.lon);
	if (!point.inside || !point.roses.length || km > POINT_RANGE_KM) return null;
	const rose = point.roses.find((r) => r.window === window) ?? null;
	const location: MapWindLocation = {
		id: 'point',
		name: 'The map’s forecast here',
		lat: point.lat,
		lon: point.lon,
		generated_at: point.generated ?? '',
		roses: point.roses,
		flags: []
	};
	const scale = rose
		? transport({
				snowCm: rose.snow_cm,
				meanKmh: rose.mean_kmh ?? null,
				minSnowCm: point.min_snow_cm,
				minWindKmh: point.min_wind_kmh
			})
		: 0;
	return { location, km, rose, scale, model: true };
}
