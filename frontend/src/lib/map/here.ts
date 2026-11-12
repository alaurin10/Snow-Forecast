// What a tap on the map landed on, for the Inspector: a ski run or route (whose whole
// line the Measure panel can profile), a hut, trailhead or pass, a glacier, an ATES rating.
import type { UnitSystem } from '../units';
import { elevation as fmtElevation } from '../units';
import { ATES } from './features';
import { joinLines, type LngLat } from './measure';

export interface HereItem {
	/** In words: "Run", "Hut", "ATES" … */
	kind: string;
	name: string;
	detail?: string;
	color?: string;
	/** The line as drawn (cut at tile edges), for a run or route… */
	line?: LngLat[];
	/** …and its OpenStreetMap id, to find the whole of it. */
	osm?: string;
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

const str = (v: unknown) => (typeof v === 'string' ? v : '');

function rendered(g: Hit['geometry']): LngLat[] | undefined {
	if (!g?.coordinates) return undefined;
	if (g.type === 'LineString') return g.coordinates as LngLat[];
	if (g.type === 'MultiLineString') return joinLines(g.coordinates as LngLat[][]);
	return undefined;
}

/** The Inspector's lines for what's under a tap, most specific first, without repeats. */
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
		if (h.layer === 'places') {
			const ele = typeof p.ele === 'number' ? fmtElevation(p.ele, units) : '';
			add(
				{ kind: PLACES[str(p.type)] ?? 'Place', name: name || 'Unnamed', detail: ele },
				`p:${name}:${str(p.type)}`
			);
		} else if (h.layer === 'runs' || h.layer === 'routes') {
			const osm = str(p.osm);
			const route = kind === 'route';
			let line = (osm && lines?.get(osm)) || rendered(h.geometry);
			// A run mapped as its outline (a closed way round a bowl) has no profile to speak of.
			const ring =
				line && line.length > 3 && line[0][0] === line.at(-1)![0] && line[0][1] === line.at(-1)![1];
			if (!route && ring) line = undefined;
			const diff = DIFFICULTY[str(p.difficulty)];
			const type = RUN_TYPES[str(p.type)];
			add(
				{
					kind: route ? 'Route' : (type ?? 'Run'),
					name: name || (route ? 'Unnamed route' : 'Unnamed run'),
					detail: [route && type ? type.toLowerCase() : '', diff].filter(Boolean).join(' · '),
					line: line && line.length >= 2 ? line : undefined,
					osm: line ? osm || undefined : undefined
				},
				`r:${osm || name}`
			);
		} else if (h.layer === 'glaciers') {
			add({ kind: 'Glacier', name: name || 'Glacier ice' }, `g:${name}`);
		} else if (h.layer === 'ates-fill' || h.layer === 'ates-line') {
			const r = ATES[str(p.rating)] ?? ATES.unrated;
			add(
				{
					kind: 'ATES',
					name: r.label,
					color: r.color,
					detail: [name, `from ${str(p.file)}`].filter(Boolean).join(' · ')
				},
				`a:${str(p.rating)}:${name}`
			);
		}
	}
	return out;
}

/** The layers a tap is checked against for the Inspector's list. */
export const HERE_LAYERS = ['places', 'runs', 'routes', 'glaciers', 'ates-fill', 'ates-line'];
