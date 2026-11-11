// The map's avalanche layers, page side: which forecast zone a spot is in, the treeline
// band used there, today's published ratings, and the listed problems as terrain to
// match. Ratings are only ever used as published; the API has already applied expiry.
import type { AvalancheView, AvyProblem, ConcernOut, ZoneFeature, ZonesOut } from '../types.gen';
import type { MatchRule } from './terrain/analysis';
import { SECTORS } from './terrain/analysis';
import {
	bandOf,
	bandRanges,
	BANDS,
	problemKind,
	sectors,
	type Band,
	type ConcernInputs,
	type ConcernParams,
	type ConcernProblem
} from './terrain/concern';
import { distanceKm, type WindSource } from './windsource';

/** The official North American danger colours (as `--d1`…`--d5` in theme.css). */
export const DANGER_COLORS: Record<number, string> = {
	1: '#50b848',
	2: '#fff200',
	3: '#f7941e',
	4: '#ed1c24',
	5: '#231f20'
};
/** Expired, not rated, or no rating for today. */
export const NO_RATING_COLOR = '#9aa0a6';

export const BAND_WORDS: Record<Band, string> = {
	alpine: 'Alpine',
	treeline: 'Treeline',
	below: 'Below treeline'
};

type Ring = number[][];

function inRing(lon: number, lat: number, ring: Ring): boolean {
	let inside = false;
	for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
		const [x1, y1] = ring[i];
		const [x2, y2] = ring[j];
		if (y1 > lat !== y2 > lat && lon < ((x2 - x1) * (lat - y1)) / (y2 - y1) + x1) inside = !inside;
	}
	return inside;
}

/** The zone's (multi)polygon as a list of polygons, each a list of rings. */
export function polygons(geometry: ZoneFeature['geometry']): Ring[][] {
	const coords = geometry.coordinates as unknown;
	if (geometry.type === 'Polygon') return [coords as Ring[]];
	if (geometry.type === 'MultiPolygon') return coords as Ring[][];
	return [];
}

export function contains(geometry: ZoneFeature['geometry'], lat: number, lon: number): boolean {
	return polygons(geometry).some(
		(poly) =>
			poly.length > 0 &&
			inRing(lon, lat, poly[0]) &&
			!poly.slice(1).some((h) => inRing(lon, lat, h))
	);
}

const boxes = new WeakMap<ZoneFeature, [number, number, number, number]>();
function boxOf(z: ZoneFeature): [number, number, number, number] {
	let b = boxes.get(z);
	if (!b) {
		b = [Infinity, Infinity, -Infinity, -Infinity];
		for (const poly of polygons(z.geometry))
			for (const [x, y] of poly[0] ?? []) {
				b[0] = Math.min(b[0], x);
				b[1] = Math.min(b[1], y);
				b[2] = Math.max(b[2], x);
				b[3] = Math.max(b[3], y);
			}
		boxes.set(z, b);
	}
	return b;
}

/**
 * The forecast zone a spot is in. Where zones overlap (it happens along borders), one
 * with a current rating wins over one without.
 */
export function zoneAt(
	zones: readonly ZoneFeature[],
	lat: number,
	lon: number
): ZoneFeature | null {
	let found: ZoneFeature | null = null;
	for (const z of zones) {
		const [w, s, e, n] = boxOf(z);
		if (lon < w || lon > e || lat < s || lat > n || !contains(z.geometry, lat, lon)) continue;
		if (z.properties.view.status === 'current') return z;
		found ??= z;
	}
	return found;
}

export interface Treeline {
	/** Bottom and top of the treeline band, metres. */
	band: [number, number];
	/** Where the numbers come from: a rule's name or the owner's location. */
	name: string;
	/** The owner set these numbers for a nearby location. */
	own: boolean;
}

/** The treeline band at a spot: the owner's numbers near a location, else the first rule that matches. */
export function treelineAt(
	data: Pick<ZonesOut, 'treeline' | 'treeline_spots' | 'spot_km'>,
	zone: ZoneFeature | null,
	lat: number,
	lon: number
): Treeline {
	let best: { km: number; band: [number, number]; name: string } | null = null;
	for (const s of data.treeline_spots) {
		const km = distanceKm(lat, lon, s.lat, s.lon);
		if (km <= (data.spot_km ?? 40) && (!best || km < best.km))
			best = { km, band: s.band, name: s.name };
	}
	if (best) return { band: best.band, name: best.name, own: true };
	const doc = zone?.properties.view.doc;
	const center = doc?.center_id?.toLowerCase() ?? null;
	const zname = doc?.zone?.toLowerCase() ?? null;
	for (const r of data.treeline) {
		if (r.center && r.center.toLowerCase() !== center) continue;
		if (r.zone && r.zone.toLowerCase() !== zname) continue;
		if (r.box) {
			const [s, w, n, e] = r.box;
			if (lat < s || lat > n || lon < w || lon > e) continue;
		}
		return { band: r.band, name: r.name, own: false };
	}
	return { band: [1500, 2000], name: 'Default', own: false };
}

/** Today's published ratings by band, if the zone has a current rating for today. */
export function todayRatings(
	view: AvalancheView,
	today: string
): Record<Band, number | null> | null {
	if (view.status !== 'current' || !view.doc) return null;
	const day = (view.doc.days ?? []).find((d) => d.date === today);
	if (!day) return null;
	const out = {
		alpine: day.alpine ?? null,
		treeline: day.treeline ?? null,
		below: day.below ?? null
	};
	return BANDS.some((b) => out[b] != null) ? out : null;
}

/** The highest rating today, 0 when there is none: what colours the zone. */
export function zoneLevel(z: ZoneFeature): number {
	const r = todayRatings(z.properties.view, z.properties.today);
	return r ? Math.max(0, ...BANDS.map((b) => r[b] ?? 0)) : 0;
}

/** A listed problem in the terms the terrain layers use (empty lists: all). */
export function concernProblem(p: AvyProblem): ConcernProblem {
	return {
		name: p.name,
		aspects: sectors(p.aspects ?? []),
		bands: (p.elevations ?? []).filter((e): e is Band => (BANDS as readonly string[]).includes(e))
	};
}

/** A problem as a terrain-match rule: its aspects (all if none listed) in its bands. */
export function problemRule(p: AvyProblem, treeline: [number, number]): MatchRule {
	const c = concernProblem(p);
	return {
		aspects: c.aspects.length ? c.aspects : [...SECTORS],
		ranges: c.bands.length ? bandRanges(c.bands, treeline) : []
	};
}

export { problemKind };

/** The zones for MapLibre: flat properties only (it can't style nested ones). */
export function zonesGeojson(zones: readonly ZoneFeature[]): GeoJSON.FeatureCollection {
	return {
		type: 'FeatureCollection',
		features: zones.map((z) => ({
			type: 'Feature',
			id: undefined,
			geometry: z.geometry as unknown as GeoJSON.Geometry,
			properties: { id: z.id, level: zoneLevel(z), status: z.properties.view.status }
		}))
	};
}

/** "NWAC · West Slopes South", or the center alone. */
export function zoneName(z: ZoneFeature): string {
	const d = z.properties.view.doc;
	if (!d) return 'Avalanche zone';
	return [d.center_id && d.center_id !== 'avcan' ? d.center_id : d.center, d.zone]
		.filter(Boolean)
		.join(' · ');
}

/** A spot's avalanche zone, band and today's published rating for it (the Inspector). */
export interface AvyHere {
	zone: string;
	band: Band;
	/** Today's rating for the band, as published; null when there is none. */
	level: number | null;
	/** Why there is no rating: expired, not rated, none for today. */
	status: string | null;
	treeline: Treeline;
}

/** What the Inspector says about avalanche danger at a spot of known elevation. */
export function avyHere(
	data: Pick<ZonesOut, 'treeline' | 'treeline_spots' | 'spot_km'>,
	zone: ZoneFeature,
	lat: number,
	lon: number,
	elev: number
): AvyHere {
	const treeline = treelineAt(data, zone, lat, lon);
	const band = bandOf(elev, treeline.band);
	const v = zone.properties.view;
	const r = todayRatings(v, zone.properties.today);
	const status =
		v.status === 'expired'
			? 'forecast expired'
			: !r
				? 'no rating today'
				: r[band] == null
					? 'no rating for this band'
					: null;
	return { zone: zoneName(zone), band, level: r?.[band] ?? null, status, treeline };
}

/** What the concern index will use for a view, in words as well as numbers. */
export interface ConcernSetup {
	/** Null when there is nothing to draw; `why` says why. */
	inputs: ConcernInputs | null;
	why: string | null;
	windSectors: number[] | null;
	windScale: number;
	/** How wind and sun count today, for the controls and the Inspector. */
	windNote: string;
	sunNote: string;
}

/**
 * Put the concern index's inputs together for the zone in use: today's published
 * ratings, its problems, and the nearest location's wind (last 48 h) and warming flags.
 */
export function concernSetup(
	zone: ZoneFeature | null,
	treeline: Treeline,
	wind: WindSource | null,
	windSnowCm: number
): ConcernSetup {
	const none = (why: string): ConcernSetup => ({
		inputs: null,
		why,
		windSectors: null,
		windScale: 0,
		windNote: '',
		sunNote: ''
	});
	if (!zone) return none('No avalanche forecast zone here.');
	const v = zone.properties.view;
	const name = zoneName(zone);
	if (v.status === 'expired') return none(`The forecast for ${name} has expired.`);
	const danger = todayRatings(v, zone.properties.today);
	if (!danger) return none(`${name} has no danger rating for today.`);
	const listed = (v.doc?.problems ?? []).map(concernProblem);
	const kinds = (v.doc?.problems ?? []).map((p) => problemKind(p.name));
	const rose = wind?.rose ?? null;
	const hasWind = !!rose && (wind?.scale ?? 0) > 0;
	const slabs = kinds.includes('wind') || kinds.includes('storm');
	const deep = !!rose && rose.snow_cm >= windSnowCm;
	const flags = (wind?.location.flags ?? []).filter((f) => f.date === zone.properties.today);
	const wetDay = kinds.includes('wet') || flags.length > 0;
	const windNote = !wind
		? 'Wind not counted: no saved location close enough.'
		: !hasWind
			? `Wind not counted: little snow for the wind to move at ${wind.location.name} (last 48 h).`
			: slabs || deep
				? `Loaded slopes count more, scoured less (last 48 h at ${wind.location.name}${slabs ? '; wind or storm slabs listed' : '; lots of new snow'}).`
				: `Scoured slopes count less (last 48 h at ${wind.location.name}); loading isn't counted without a slab problem or deep new snow.`;
	const why = kinds.includes('wet')
		? 'a wet-snow problem is listed'
		: flags.some((f) => f.type === 'rain_on_snow')
			? `rain on snow is forecast at ${wind!.location.name}`
			: `rapid warming is forecast at ${wind?.location.name ?? 'the nearest location'}`;
	const sunNote = wetDay
		? `Sunny east-to-west slopes count more today: ${why}.`
		: 'Sun not counted: no wet-snow problem or warming today.';
	return {
		inputs: {
			danger,
			treeline: treeline.band,
			problems: listed,
			wind: hasWind,
			windLoading: slabs || deep,
			sun: wetDay
		},
		why: null,
		windSectors: hasWind ? [...rose!.sectors] : null,
		windScale: hasWind ? wind!.scale : 0,
		windNote,
		sunNote
	};
}

/** The server's concern settings in the shape the scoring code takes. */
export function concernParams(c: ConcernOut): ConcernParams {
	return {
		slope: c.slope.map(([a, f]) => [a, f] as [number, number]),
		matchListed: c.match_listed,
		matchOther: c.match_other,
		matchNone: c.match_none,
		windLoaded: c.wind_loaded,
		windScoured: c.wind_scoured,
		windEffect: c.wind_effect,
		sun: c.sun,
		sunHours: c.sun_hours,
		classes: [c.classes[0], c.classes[1], c.classes[2]]
	};
}

/** "2026-12-10" as [2026, 12, 10]. */
export function ymd(date: string): [number, number, number] {
	const [y, m, d] = date.split('-').map(Number);
	return [y, m, d];
}
