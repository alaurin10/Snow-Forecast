// Recent satellite base map (docs/MAP-PLAN.md, B6). NASA GIBS's daily VIIRS mosaic
// (375 m, the newest day with imagery) everywhere; round the location nearest the middle
// of the map a stitched Sentinel-2 view of the 72 km round at 30 m (the wide view); and
// over the 24 km in its middle one Sentinel-2 view at 10 m. All are drawn and cut into
// tiles by the server (backend/snowwatch/maps/satrender.py), so the map loads finished
// tiles. Stitched views take each part from the newest pass that saw the ground there,
// outlined and dated on the map. The centre's other views are whole clear scenes.
import type { SatComposite, SatLocation, SatOut, SatScene } from '../types.gen';
import type { SatBands } from '../prefs.svelte';
import { distanceKm } from './windsource';

/** A location's views are shown while the map's middle is this close to it. */
export const SAT_RANGE_KM = 60;
/** VIIRS tiles stop at zoom 9; the views' tiles are cut for zooms 9 to 13. */
export const VIIRS_MAX_ZOOM = 9;
export const S2_MIN_ZOOM = 9;
export const S2_MAX_ZOOM = 13;
/** The wide view's tiles are cut for zooms 7 to 12. */
export const WIDE_MIN_ZOOM = 7;
export const WIDE_MAX_ZOOM = 12;

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

/** The chip, date first (the satellite's name is behind the (i)): "4 Nov · 6 days ago ·
 *  92% clear". */
export function sceneLabel(scene: SatScene, now: number): string {
	return [shortDate(scene.time), ago(scene.time, now), `${scene.clear_pct}% clear`].join(' · ');
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

/** What's on screen in a few words, for the folded controls: "Newest clear · 21 Oct–4
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

/** "21 Oct–10 Nov", or "2–9 Nov" within a month: the span of a stitched view's passes,
 *  kept short so it fits the folded controls on a phone. */
export function stitchedSpan(c: SatComposite): string {
	const times = c.layers.map((l) => l.time).sort();
	const a = shortDate(times[0]);
	const b = shortDate(times[times.length - 1]);
	if (a === b) return a;
	const [da, ma] = a.split(' ');
	const [db, mb] = b.split(' ');
	return ma === mb ? `${da}–${db} ${mb}` : `${a}–${b}`;
}

/** A stitched view's dashed lines where two passes' parts meet, and each part as a
 * dated area (the map writes its date wherever the part is on screen). The wide view's
 * are marked `wide`, and drawn quieter. */
export function datesGeojson(c: SatComposite, wide = false): GeoJSON.FeatureCollection {
	const newest = c.layers[0]?.time;
	return {
		type: 'FeatureCollection',
		features: [
			...((c.lines ?? []).length
				? [
						{
							type: 'Feature' as const,
							properties: { kind: 'line', ...(wide ? { wide } : {}) },
							geometry: { type: 'MultiLineString' as const, coordinates: c.lines ?? [] }
						}
					]
				: []),
			...c.parts.map((p) => ({
				type: 'Feature' as const,
				properties: {
					kind: 'part',
					label: shortDate(p.time),
					newest: p.time === newest,
					...(wide ? { wide } : {})
				},
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
	/** Every location's 30 m stitched view of the wider area round it, bottom first. */
	wides: RecentSource[];
	/** Every location's 10 m view over its own area, bottom first (over all the wides). */
	views: RecentSource[];
	/** The stitched views' parts, outlined and dated. */
	dates: GeoJSON.FeatureCollection | null;
}

/** Both stitched views' outlines and dates in one collection (either may be missing). */
function mergeDates(
	wide: SatComposite | null | undefined,
	centre: SatComposite | null
): GeoJSON.FeatureCollection | null {
	const features = [
		...(wide?.layers.length ? datesGeojson(wide, true).features : []),
		...(centre?.layers.length ? datesGeojson(centre).features : [])
	];
	return features.length ? { type: 'FeatureCollection', features } : null;
}

const gibs = (layer: string, day: string) => [`/api/tiles/gibs/${layer}/${day}/{z}/{x}/{y}`];

function viewSource(
	data: SatOut | null,
	spot: SatLocation,
	view: SatView | null,
	bands: SatBands
): RecentSource | null {
	const name = view?.kind === 'stitched' ? view.composite.view : view?.scene.view;
	const [minzoom, maxzoom] = data?.zooms ?? [S2_MIN_ZOOM, S2_MAX_ZOOM];
	return name && spot.box
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
}

function wideSource(data: SatOut | null, spot: SatLocation, bands: SatBands): RecentSource | null {
	const [wmin, wmax] = data?.wide_zooms ?? [WIDE_MIN_ZOOM, WIDE_MAX_ZOOM];
	return spot.wide && spot.wide_box
		? {
				id: `wide-${spot.wide.view}-${bands}`,
				tiles: [`/api/sat/tiles/${spot.wide.view}/${bands}/{z}/{x}/{y}.webp`],
				tileSize: 512,
				minzoom: wmin,
				maxzoom: wmax,
				bounds: spot.wide_box,
				attribution: SAT_ATTRIBUTION
			}
		: null;
}

/**
 * What the Recent satellite base draws: every location's views, so areas that touch or
 * overlap read as one. `spot` (the location nearest the map's middle) shows `view`, the
 * one its controls step to, and the others their first (stitched, if they have one).
 * Bottom first: the 30 m wide views, then the 10 m ones, so 10 m is on top wherever it
 * reaches; within each, `spot`'s goes last, on top. Only `spot`'s parts are outlined
 * and dated.
 */
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
	const others = (data?.locations ?? []).filter((l) => l.id !== spot?.id);
	const wides = [...others, ...(spot ? [spot] : [])]
		.map((l) => wideSource(data, l, bands))
		.filter((x): x is RecentSource => !!x);
	const views = [
		...others.map((l) => viewSource(data, l, satViews(l)[0] ?? null, bands)),
		spot ? viewSource(data, spot, view, bands) : null
	].filter((x): x is RecentSource => !!x);
	return {
		viirs,
		wides,
		views,
		dates: mergeDates(spot?.wide, view?.kind === 'stitched' ? view.composite : null)
	};
}
