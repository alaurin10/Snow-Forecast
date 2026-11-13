// What a tap on the map landed on, as the map panel's targets, most specific first: a
// snow station, a field report, a hut, trailhead or pass, a ski run or route (whose whole
// line the Measure panel can profile), a glacier, an ATES rating, the avalanche zone, and
// last the spot itself (its terrain and weather). The panel opens on the first; the rest
// are chips that switch its content in place.
import type { MapStation, ObsProps, ZoneFeature } from '../types.gen';
import type { UnitSystem } from '../units';
import { elevation as fmtElevation } from '../units';
import { ATES } from './features';
import { joinLines, type LngLat } from './measure';

/** A map feature at the tap, in the order they rank. */
export type HereType = 'place' | 'route' | 'glacier' | 'ates';

export interface HereItem {
	type: HereType;
	/** In words: "Run", "Hut", "ATES" … */
	kind: string;
	name: string;
	detail?: string;
	color?: string;
	/** Metres above sea level, as mapped (huts, passes). */
	ele?: number;
	/** The line as drawn (cut at tile edges), for a run or route… */
	line?: LngLat[];
	/** …and its OpenStreetMap id, to find the whole of it. */
	osm?: string;
	/** The feature on openstreetmap.org, when its id is known. */
	link?: string;
	/** The ATES file it came from. */
	file?: string;
}

/** A rendered feature, as MapLibre's queryRenderedFeatures gives it (the parts used). */
export interface Hit {
	layer: string;
	properties: Record<string, unknown>;
	geometry?: { type: string; coordinates?: unknown };
}

/** Every run's and route's whole line by its OpenStreetMap id (what's drawn is cut into tiles). */
export type SkiLines = Map<string, LngLat[]>;

export function skiLines(fc: GeoJSON.FeatureCollection): SkiLines {
	const out: SkiLines = new Map();
	for (const f of fc.features) {
		const id = f.properties?.osm;
		if (typeof id !== 'string') continue;
		if (f.geometry.type === 'LineString') out.set(id, f.geometry.coordinates as LngLat[]);
		else if (f.geometry.type === 'MultiLineString')
			out.set(id, joinLines(f.geometry.coordinates as LngLat[][]));
	}
	return out;
}

const DIFFICULTY: Record<string, string> = {
	novice: 'beginner',
	easy: 'easy',
	intermediate: 'intermediate',
	advanced: 'advanced',
	expert: 'expert',
	extreme: 'extreme',
	freeride: 'freeride'
};
const RUN_TYPES: Record<string, string> = {
	downhill: 'Run',
	skitour: 'Ski tour',
	backcountry: 'Backcountry',
	nordic: 'Nordic',
	sled: 'Sled run',
	hike: 'Snowshoe',
	snow_park: 'Terrain park'
};
const PLACES: Record<string, string> = {
	alpine_hut: 'Hut',
	wilderness_hut: 'Hut',
	shelter: 'Shelter',
	trailhead: 'Trailhead',
	pass: 'Pass',
	saddle: 'Col'
};
const OSM_TYPES: Record<string, string> = { n: 'node', w: 'way', r: 'relation' };

const str = (v: unknown) => (typeof v === 'string' ? v : '');

/** "w123" → its page on openstreetmap.org. */
export function osmLink(id: string | undefined): string | undefined {
	const m = id ? /^([nwr])(\d+)$/.exec(id) : null;
	return m ? `https://www.openstreetmap.org/${OSM_TYPES[m[1]]}/${m[2]}` : undefined;
}

function rendered(g: Hit['geometry']): LngLat[] | undefined {
	if (!g?.coordinates) return undefined;
	if (g.type === 'LineString') return g.coordinates as LngLat[];
	if (g.type === 'MultiLineString') return joinLines(g.coordinates as LngLat[][]);
	return undefined;
}

const RANK: Record<HereType, number> = { place: 0, route: 1, glacier: 2, ates: 3 };

/** The map features under a tap, most specific first, without repeats. */
export function hereItems(hits: Hit[], units: UnitSystem, lines: SkiLines | null): HereItem[] {
	const out: HereItem[] = [];
	const seen = new Set<string>();
	const add = (item: HereItem, key: string) => {
		if (seen.has(key)) return;
		seen.add(key);
		out.push(item);
	};
	for (const h of hits) {
		const p = h.properties;
		const kind = str(p.kind);
		const name = str(p.name);
		const id = str(p.osm) || undefined;
		if (h.layer === 'places') {
			const ele = typeof p.ele === 'number' ? p.ele : undefined;
			add(
				{
					type: 'place',
					kind: PLACES[str(p.type)] ?? 'Place',
					name: name || 'Unnamed',
					detail: ele != null ? fmtElevation(ele, units) : '',
					ele,
					link: osmLink(id)
				},
				`p:${id ?? `${name}:${str(p.type)}`}`
			);
		} else if (h.layer === 'runs' || h.layer === 'routes') {
			const route = kind === 'route';
			let line = (id && lines?.get(id)) || rendered(h.geometry);
			// A run mapped as its outline (a closed way round a bowl) has no profile to speak of.
			const ring =
				line && line.length > 3 && line[0][0] === line.at(-1)![0] && line[0][1] === line.at(-1)![1];
			if (!route && ring) line = undefined;
			const diff = DIFFICULTY[str(p.difficulty)];
			const type = RUN_TYPES[str(p.type)];
			add(
				{
					type: 'route',
					kind: route ? 'Route' : (type ?? 'Run'),
					name: name || (route ? 'Unnamed route' : 'Unnamed run'),
					detail: [route && type ? type.toLowerCase() : '', diff].filter(Boolean).join(' · '),
					line: line && line.length >= 2 ? line : undefined,
					osm: line ? id : undefined,
					link: osmLink(id)
				},
				`r:${id || name}`
			);
		} else if (h.layer === 'glaciers') {
			add(
				{
					type: 'glacier',
					kind: 'Glacier',
					name: name || 'Glacier ice',
					osm: id,
					link: osmLink(id)
				},
				`g:${id ?? name}`
			);
		} else if (h.layer === 'ates-fill' || h.layer === 'ates-line') {
			const r = ATES[str(p.rating)] ?? ATES.unrated;
			add(
				{
					type: 'ates',
					kind: 'ATES',
					name: r.label,
					color: r.color,
					detail: name,
					file: str(p.file) || undefined
				},
				`a:${str(p.rating)}:${name}`
			);
		}
	}
	// Stable: within a type, the order MapLibre drew them (topmost first).
	return out.sort((a, b) => RANK[a.type] - RANK[b.type]);
}

/** The layers a tap is checked against for map features. */
export const HERE_LAYERS = ['places', 'runs', 'routes', 'glaciers', 'ates-fill', 'ates-line'];

/** One thing the map panel can show for a tap. */
export type Target =
	| { kind: 'station'; chip: string; station: MapStation }
	| { kind: 'report'; chip: string; report: ObsProps }
	| { kind: 'feature'; chip: string; item: HereItem }
	| { kind: 'zone'; chip: string; zone: ZoneFeature }
	| { kind: 'spot'; chip: string };

export const SPOT: Target = { kind: 'spot', chip: 'This spot' };

/**
 * Everything a tap landed on, most specific first: station → field report → hut,
 * trailhead or pass → run or route → glacier → ATES → avalanche zone → the spot itself
 * (always last, when it can be measured, so terrain numbers stay one tap away).
 */
export function tapTargets(o: {
	station?: MapStation | null;
	report?: ObsProps | null;
	here?: HereItem[];
	zone?: ZoneFeature | null;
	spot: boolean;
}): Target[] {
	const out: Target[] = [];
	if (o.station) out.push({ kind: 'station', chip: 'Station', station: o.station });
	if (o.report) out.push({ kind: 'report', chip: 'Report', report: o.report });
	for (const item of o.here ?? []) out.push({ kind: 'feature', chip: item.kind, item });
	if (o.zone) out.push({ kind: 'zone', chip: 'Zone', zone: o.zone });
	if (o.spot) out.push(SPOT);
	return out;
}

// ---- Glaciers: the whole outline, from the map's OpenStreetMap file ------------------

type Ring = LngLat[];
const R = 6378137;
const rad = (d: number) => (d * Math.PI) / 180;

/** A ring's area on the sphere, in square metres (unsigned). */
export function ringArea(ring: Ring): number {
	const n = ring.length;
	if (n < 3) return 0;
	let sum = 0;
	for (let i = 0; i < n; i++) {
		const [lon1, lat1] = ring[i];
		const [lon2, lat2] = ring[(i + 1) % n];
		sum += rad(lon2 - lon1) * (2 + Math.sin(rad(lat1)) + Math.sin(rad(lat2)));
	}
	return Math.abs((sum * R * R) / 2);
}

/** A polygon's area: its outline less its holes. */
export function polygonArea(rings: Ring[]): number {
	if (!rings.length) return 0;
	return Math.max(0, ringArea(rings[0]) - rings.slice(1).reduce((s, r) => s + ringArea(r), 0));
}

function inRing(ring: Ring, lon: number, lat: number): boolean {
	let inside = false;
	for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
		const [xi, yi] = ring[i];
		const [xj, yj] = ring[j];
		if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
	}
	return inside;
}

function polygons(g: GeoJSON.Geometry): Ring[][] {
	if (g.type === 'Polygon') return [g.coordinates as Ring[]];
	if (g.type === 'MultiPolygon') return g.coordinates as Ring[][];
	return [];
}

/**
 * The glacier's whole area in square metres: found by its OpenStreetMap id, else as the
 * glacier whose outline holds the tapped point. Null if neither finds it.
 */
export function glacierArea(
	fc: GeoJSON.FeatureCollection,
	lon: number,
	lat: number,
	osm?: string
): number | null {
	const ice = fc.features.filter((f) => f.properties?.kind === 'glacier');
	const byId = osm ? ice.find((f) => f.properties?.osm === osm) : undefined;
	const holds = (f: GeoJSON.Feature) =>
		polygons(f.geometry).some(
			(p) => p.length && inRing(p[0], lon, lat) && !p.slice(1).some((h) => inRing(h, lon, lat))
		);
	const f = byId ?? ice.find(holds);
	if (!f) return null;
	return polygons(f.geometry).reduce((s, p) => s + polygonArea(p), 0);
}

/** An area in words: hectares or km², acres or square miles. */
export function areaText(m2: number, units: UnitSystem): string {
	if (units === 'imperial') {
		const acres = m2 / 4046.856;
		if (acres >= 640) return `${(acres / 640).toFixed(acres >= 6400 ? 0 : 1)} sq mi`;
		return `${Math.round(acres).toLocaleString('en-US')} acres`;
	}
	if (m2 >= 1e6) return `${(m2 / 1e6).toFixed(m2 >= 1e7 ? 0 : 1)} km²`;
	return `${Math.max(1, Math.round(m2 / 1e4)).toLocaleString('en-US')} ha`;
}
