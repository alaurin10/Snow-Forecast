// Recent satellite base map (docs/MAP-PLAN.md, B6). NASA GIBS's daily VIIRS mosaic
// (375 m, the newest day with imagery) everywhere, and over the 24 km round the location
// nearest the middle of the map one Sentinel-2 view at 10 m, drawn and cut into tiles by
// the server (backend/snowwatch/maps/satrender.py), so the map loads one layer of
// finished tiles. The first view is stitched: each part from the newest pass that saw
// the ground there, outlined and dated on the map. The others are whole clear scenes.
import type { SatComposite, SatLocation, SatOut, SatScene } from '../types.gen';
import type { SatBands } from '../prefs.svelte';
import { distanceKm } from './windsource';

/** A location's views are shown while the map's middle is this close to it. */
export const SAT_RANGE_KM = 60;
/** VIIRS tiles stop at zoom 9; the views' tiles are cut for zooms 9 to 13. */
export const VIIRS_MAX_ZOOM = 9;
export const S2_MIN_ZOOM = 9;
export const S2_MAX_ZOOM = 13;

export const VIIRS_LAYERS: Record<SatBands, string> = {
	natural: 'VIIRS_NOAA20_CorrectedReflectance_TrueColor',
	// Shortwave infrared, near infrared, red: the same idea as Sentinel-2's snow view.
	snow: 'VIIRS_NOAA20_CorrectedReflectance_BandsM11-I2-I1'
};

export const SAT_ATTRIBUTION =
	'Contains modified <a href="https://dataspace.copernicus.eu/">Copernicus Sentinel</a> data, via <a href="https://planetarycomputer.microsoft.com/">Microsoft Planetary Computer</a>';
export const GIBS_ATTRIBUTION =
	'Imagery: <a href="https://earthdata.nasa.gov/gibs">NASA GIBS</a> (VIIRS)';

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

/** What the Sentinel-2 layer shows: the stitched newest-clear view, or one whole scene. */
export type SatView =
	{ kind: 'stitched'; composite: SatComposite } | { kind: 'scene'; scene: SatScene };

/** A location's views in the order the controls step through them: stitched first. */
export function satViews(spot: SatLocation | null): SatView[] {
	if (!spot) return [];
	const out: SatView[] = [];
	if (spot.composite?.layers.length) out.push({ kind: 'stitched', composite: spot.composite });
	for (const scene of spot.scenes ?? []) out.push({ kind: 'scene', scene });
	return out;
}

/** What's on screen in a few words, for the folded controls: "Newest clear · 21 Oct – 4
 *  Nov", "4 Nov · 6 days ago", "Daily mosaic · 10 Nov". */
export function satSummary(
	viirsDate: string | null | undefined,
	spot: SatLocation | null,
	index: number,
	now: number
): string {
	const views = satViews(spot);
	const view = views[Math.min(index, views.length - 1)];
	if (view?.kind === 'stitched') return `Newest clear · ${stitchedSpan(view.composite)}`;
	if (view?.kind === 'scene') return `${shortDate(view.scene.time)} · ${ago(view.scene.time, now)}`;
	return viirsDate ? `Daily mosaic · ${dayLabel(viirsDate)}` : 'Daily mosaic';
}

/** "21 Oct – 10 Nov": the span of a stitched view's passes. */
export function stitchedSpan(c: SatComposite): string {
	const times = c.layers.map((l) => l.time).sort();
	const a = shortDate(times[0]);
	const b = shortDate(times[times.length - 1]);
	return a === b ? a : `${a} – ${b}`;
}

/** A stitched view's dashed lines where two passes' parts meet, and each part as a
 * dated area (the map writes its date wherever the part is on screen). */
export function datesGeojson(c: SatComposite): GeoJSON.FeatureCollection {
	const newest = c.layers[0]?.time;
	return {
		type: 'FeatureCollection',
		features: [
			...((c.lines ?? []).length
				? [
						{
							type: 'Feature' as const,
							properties: { kind: 'line' },
							geometry: { type: 'MultiLineString' as const, coordinates: c.lines ?? [] }
						}
					]
				: []),
			...c.parts.map((p) => ({
				type: 'Feature' as const,
				properties: { kind: 'part', label: shortDate(p.time), newest: p.time === newest },
				geometry: { type: 'MultiPolygon' as const, coordinates: p.polygons }
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

/** What the Recent satellite base draws. */
export interface RecentSpec {
	viirs: RecentSource | null;
	/** The Sentinel-2 view over the location's area. */
	view: RecentSource | null;
	/** The stitched view's parts, outlined and dated. */
	dates: GeoJSON.FeatureCollection | null;
}

const gibs = (layer: string, day: string) => [`/api/tiles/gibs/${layer}/${day}/{z}/{x}/{y}`];

export function recentSpec(
	data: SatOut | null,
	spot: SatLocation | null,
	view: SatView | null,
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
	const name = view?.kind === 'stitched' ? view.composite.view : view?.scene.view;
	const [minzoom, maxzoom] = data?.zooms ?? [S2_MIN_ZOOM, S2_MAX_ZOOM];
	const s2: RecentSource | null =
		name && spot?.box
			? {
					id: `view-${name}-${bands}`,
					tiles: [`/api/sat/tiles/${name}/${bands}/{z}/{x}/{y}.webp`],
					tileSize: 512,
					minzoom,
					maxzoom,
					bounds: spot.box,
					attribution: SAT_ATTRIBUTION
				}
			: null;
	return {
		viirs,
		view: s2,
		dates: view?.kind === 'stitched' ? datesGeojson(view.composite) : null
	};
}
