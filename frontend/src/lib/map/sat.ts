// Recent satellite base map (docs/MAP-PLAN.md, B6). Three tiers, finest on top:
// NASA GIBS's daily VIIRS mosaic everywhere (375 m, the newest day with imagery), HLS at
// 30 m from the same Sentinel-2 pass as the scene shown, and that scene itself at 10 m.
// Sentinel-2 scenes are picked by the server per location (newest views that see the
// ground there); the map shows the scene of the location nearest its middle.
import type { SatLocation, SatOut, SatScene } from '../types.gen';
import type { SatBands } from '../prefs.svelte';
import { distanceKm } from './windsource';

/** A location's scene is shown while the map's middle is this close to it. */
export const SAT_RANGE_KM = 60;
/** VIIRS tiles stop at zoom 9, HLS at 12; Sentinel-2 is fetched to 14 (512 px tiles). */
export const VIIRS_MAX_ZOOM = 9;
export const HLS_MIN_ZOOM = 8;
export const HLS_MAX_ZOOM = 12;
export const S2_MIN_ZOOM = 10;
export const S2_MAX_ZOOM = 14;

export const VIIRS_LAYERS: Record<SatBands, string> = {
	natural: 'VIIRS_NOAA20_CorrectedReflectance_TrueColor',
	// Shortwave infrared, near infrared, red: the same idea as Sentinel-2's snow view.
	snow: 'VIIRS_NOAA20_CorrectedReflectance_BandsM11-I2-I1'
};
export const HLS_LAYER = 'HLS_S30_Nadir_BRDF_Adjusted_Reflectance';

export const SAT_ATTRIBUTION =
	'Contains modified <a href="https://dataspace.copernicus.eu/">Copernicus Sentinel</a> data, via <a href="https://planetarycomputer.microsoft.com/">Microsoft Planetary Computer</a>';
export const GIBS_ATTRIBUTION =
	'Imagery: <a href="https://earthdata.nasa.gov/gibs">NASA GIBS</a> (VIIRS, HLS)';

export function nearestSpot(
	data: SatOut | null,
	lat: number,
	lon: number,
	maxKm = SAT_RANGE_KM
): { spot: SatLocation; km: number } | null {
	let best: { spot: SatLocation; km: number } | null = null;
	for (const spot of data?.locations ?? []) {
		const km = distanceKm(lat, lon, spot.lat, spot.lon);
		if (km <= maxKm && (!best || km < best.km)) best = { spot, km };
	}
	return best;
}

const MS_DAY = 86400000;

/** "today", "yesterday" or "6 days ago", by calendar day on this device. */
export function ago(iso: string, now: number): string {
	const day = (ms: number) => {
		const d = new Date(ms);
		return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / MS_DAY;
	};
	const n = Math.round(day(now) - day(Date.parse(iso)));
	return n <= 0 ? 'today' : n === 1 ? 'yesterday' : `${n} days ago`;
}

/** "4 Nov", on this device's calendar. */
export function shortDate(iso: string): string {
	return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

/** A YYYY-MM-DD day (as GIBS names them) as "10 Nov". */
export function dayLabel(day: string): string {
	const [y, m, d] = day.split('-').map(Number);
	return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-GB', {
		day: 'numeric',
		month: 'short',
		timeZone: 'UTC'
	});
}

/** The chip: "Sentinel-2C · 4 Nov · 6 days ago · 92% clear". */
export function sceneLabel(scene: SatScene, now: number): string {
	return [
		scene.platform,
		shortDate(scene.time),
		ago(scene.time, now),
		`${scene.clear_pct}% clear`
	].join(' · ');
}

/** The UTC day of a scene, which is the day GIBS files its HLS under. */
export const sceneDay = (scene: SatScene) => scene.time.slice(0, 10);

export interface RecentSource {
	id: string;
	tiles: string[];
	tileSize: number;
	minzoom: number;
	maxzoom: number;
	bounds?: [number, number, number, number];
	attribution: string;
}

/** What the Recent satellite base draws, bottom to top. */
export interface RecentSpec {
	viirs: RecentSource | null;
	hls: RecentSource | null;
	s2: RecentSource[];
}

const gibs = (layer: string, day: string) => [`/api/tiles/gibs/${layer}/${day}/{z}/{x}/{y}`];

export function recentSpec(
	data: SatOut | null,
	scene: SatScene | null,
	bands: SatBands
): RecentSpec {
	const viirs: RecentSource | null = data?.viirs_date
		? {
				id: `viirs-${bands}-${data.viirs_date}`,
				tiles: gibs(VIIRS_LAYERS[bands], data.viirs_date),
				tileSize: 256,
				minzoom: 0,
				maxzoom: VIIRS_MAX_ZOOM,
				attribution: GIBS_ATTRIBUTION
			}
		: null;
	// GIBS has no snow-vs-cloud view of HLS: in that view the daily VIIRS one shows instead.
	const hls: RecentSource | null =
		scene?.hls && bands === 'natural'
			? {
					id: `hls-${sceneDay(scene)}`,
					tiles: gibs(HLS_LAYER, sceneDay(scene)),
					tileSize: 256,
					minzoom: HLS_MIN_ZOOM,
					maxzoom: HLS_MAX_ZOOM,
					attribution: GIBS_ATTRIBUTION
				}
			: null;
	const s2 = (scene?.items ?? []).map((it) => ({
		id: `s2-${bands}-${it.id}`,
		tiles: [`/api/tiles/s2/${bands}/${it.id}/{z}/{x}/{y}.webp`],
		tileSize: 512,
		minzoom: S2_MIN_ZOOM - 1,
		maxzoom: S2_MAX_ZOOM,
		bounds: it.bbox,
		attribution: SAT_ATTRIBUTION
	}));
	return { viirs, hls, s2 };
}
