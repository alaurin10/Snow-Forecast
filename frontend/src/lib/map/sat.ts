// Recent satellite base map (docs/MAP-PLAN.md, B6). Three tiers, finest on top:
// NASA GIBS's daily VIIRS mosaic everywhere (375 m, the newest day with imagery), HLS at
// 30 m from the same Sentinel-2 pass as the scene shown, and that scene itself at 10 m.
// Sentinel-2 is picked by the server per location. The default view is stitched: each
// part of the ~24 km round the location from the newest pass that saw the ground there,
// cloud cut out by the tile proxy, older passes underneath, with dashed lines and dates
// where one meets another. The viewer can also step through whole clear scenes.
import type { SatComposite, SatLocation, SatOut, SatScene } from '../types.gen';
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
/** Keep in step with S2_RENDER in backend/snowwatch/tiles.py: a new value refetches tiles. */
export const S2_RENDER = 3;

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

/** What the Sentinel-2 tier shows: the stitched newest-clear view, or one whole scene. */
export type SatView =
	{ kind: 'stitched'; composite: SatComposite } | { kind: 'scene'; scene: SatScene };

/** A location's views in the order the controls step through them: stitched first. */
export function satViews(spot: SatLocation | null): SatView[] {
	if (!spot) return [];
	const out: SatView[] = [];
	if (spot.composite?.layers.length) out.push({ kind: 'stitched', composite: spot.composite });
	for (const scene of spot.scenes) out.push({ kind: 'scene', scene });
	return out;
}

/** "21 Oct – 10 Nov": the span of a stitched view's passes. */
export function stitchedSpan(c: SatComposite): string {
	const times = c.layers.map((l) => l.time).sort();
	const a = shortDate(times[0]);
	const b = shortDate(times[times.length - 1]);
	return a === b ? a : `${a} – ${b}`;
}

function overlap(
	a: [number, number, number, number],
	b: [number, number, number, number]
): [number, number, number, number] | null {
	const w = Math.max(a[0], b[0]);
	const s = Math.max(a[1], b[1]);
	const e = Math.min(a[2], b[2]);
	const n = Math.min(a[3], b[3]);
	return w < e && s < n ? [w, s, e, n] : null;
}

/** Dashed lines where one pass's part meets another's, and each part's date. */
export function datesGeojson(c: SatComposite): GeoJSON.FeatureCollection {
	return {
		type: 'FeatureCollection',
		features: [
			...(c.boundaries.length
				? [
						{
							type: 'Feature' as const,
							properties: { kind: 'line' },
							geometry: { type: 'MultiLineString' as const, coordinates: c.boundaries }
						}
					]
				: []),
			...c.labels.map((l) => ({
				type: 'Feature' as const,
				properties: { kind: 'date', label: shortDate(l.time) },
				geometry: { type: 'Point' as const, coordinates: [l.lon, l.lat] }
			}))
		]
	};
}

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
	/** Bottom to top. */
	s2: RecentSource[];
	/** The stitched view's dividing lines and dates. */
	dates: GeoJSON.FeatureCollection | null;
}

const gibs = (layer: string, day: string) => [`/api/tiles/gibs/${layer}/${day}/{z}/{x}/{y}`];

export function recentSpec(data: SatOut | null, view: SatView | null, bands: SatBands): RecentSpec {
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
	if (view?.kind === 'stitched') {
		const layers = view.composite.layers;
		// Oldest at the bottom. The newest pass is drawn wherever it reaches, beyond the
		// worked-out area too; older ones only over the part they fill, which saves tiles.
		const s2 = [...layers].reverse().flatMap((layer) =>
			layer.items.flatMap((it) => {
				const bounds = layer === layers[0] ? it.bbox : overlap(it.bbox, layer.bbox);
				return bounds
					? [
							{
								id: `s2c-${bands}-${it.id}`,
								tiles: [`/api/tiles/s2c/${bands}/${it.id}/{z}/{x}/{y}.webp?r=${S2_RENDER}`],
								tileSize: 512,
								minzoom: S2_MIN_ZOOM - 1,
								maxzoom: S2_MAX_ZOOM,
								bounds,
								attribution: SAT_ATTRIBUTION
							}
						]
					: [];
			})
		);
		return { viirs, hls: null, s2, dates: datesGeojson(view.composite) };
	}
	const scene = view?.kind === 'scene' ? view.scene : null;
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
		tiles: [`/api/tiles/s2/${bands}/${it.id}/{z}/{x}/{y}.webp?r=${S2_RENDER}`],
		tileSize: 512,
		minzoom: S2_MIN_ZOOM - 1,
		maxzoom: S2_MAX_ZOOM,
		bounds: it.bbox,
		attribution: SAT_ATTRIBUTION
	}));
	return { viirs, hls, s2, dates: null };
}
