// Town, hamlet and park names over imagery, a zoom sooner than OpenFreeMap's tiles list
// them. Each zoom's tiles leave out smaller places (zoom 8's have no Redmond, zoom 10's
// no hamlets like Snoqualmie Pass, zoom 13's no town parks or golf courses), which
// Esri's label pictures showed. So the `places://` tiles are made in the browser from
// the four tiles of the next zoom: their places, and their parks and golf courses among
// the points of interest, scaled into the one tile. The map draws those names from these
// (style.ts, `labels-fine`).
//
// They also name the big parks (national parks and forests, wildernesses) in each quarter
// of the tile whose middle is inside one, as Esri's 256 px pictures each did: a forest's
// own name point is often far off screen.
import { VectorTile } from '@mapbox/vector-tile';
import { PbfReader } from 'pbf';
import { fromGeojsonVt } from '@maplibre/vt-pbf';
import type { AddProtocolAction } from 'maplibre-gl';

export const PLACES_TILES = 'places://{z}/{x}/{y}';
/** The tiles go to zoom 14, so places tiles to 13 (the map stretches them beyond). */
export const PLACES_MAX_ZOOM = 13;
const EXTENT = 4096;
const CHILDREN: [number, number][] = [
	[0, 0],
	[1, 0],
	[0, 1],
	[1, 1]
];

interface Child {
	dx: number;
	dy: number;
	tile: VectorTile | null;
}

interface PlaceFeature {
	type: 1;
	geometry: [number, number][];
	tags: Record<string, string | number | boolean>;
}

/** Which of a child's layers are kept, and which of their points. */
const KEEP: Record<string, (props: Record<string, unknown>) => boolean> = {
	place: () => true,
	poi: (p) => (p.class === 'park' || p.class === 'golf') && !!p.name
};
const TAGS = new Set(['name', 'class', 'subclass', 'rank', 'capital']);
/** Parks named in each quarter they cover (`park_label`). */
export const BIG_PARKS = [
	'national_park',
	'forest_reserve',
	'wilderness_preserve',
	'protected_area'
];

/** Whether a point is inside a polygon's rings (even-odd, so holes count). */
function inside(x: number, y: number, rings: { x: number; y: number }[][]): boolean {
	let hit = false;
	for (const ring of rings) {
		for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
			const a = ring[i];
			const b = ring[j];
			if (a.y > y !== b.y > y && x < ((b.x - a.x) * (y - a.y)) / (b.y - a.y) + a.x) hit = !hit;
		}
	}
	return hit;
}

/** One tile's places, parks and golf courses from its four children (`dx`, `dy`: which
 *  quarter each is). A point in two children (tiles carry a margin round their edges)
 *  is kept once. */
export function mergePlaces(children: Child[]): Uint8Array {
	const layers: Record<string, { features: PlaceFeature[] }> = { park_label: { features: [] } };
	const seen = new Set<string>();
	for (const name of Object.keys(KEEP)) layers[name] = { features: [] };
	for (const { dx, dy, tile } of children) {
		// The big parks this quarter's middle is in.
		const parks = tile?.layers.park;
		if (parks) {
			const mid = parks.extent / 2;
			const named = new Set<string>();
			for (let i = 0; i < parks.length; i++) {
				const f = parks.feature(i);
				const { name, class: cls } = f.properties;
				if (f.type !== 3 || !name || !BIG_PARKS.includes(String(cls)) || named.has(String(name)))
					continue;
				if (!inside(mid, mid, f.loadGeometry())) continue;
				named.add(String(name));
				layers.park_label.features.push({
					type: 1,
					geometry: [[(dx * EXTENT + EXTENT / 2) / 2, (dy * EXTENT + EXTENT / 2) / 2]],
					tags: { name: String(name), class: String(cls) }
				});
			}
		}
		for (const [name, keep] of Object.entries(KEEP)) {
			const layer = tile?.layers[name];
			if (!layer) continue;
			const scale = EXTENT / layer.extent;
			for (let i = 0; i < layer.length; i++) {
				const f = layer.feature(i);
				if (f.type !== 1 || !keep(f.properties)) continue;
				const tags: PlaceFeature['tags'] = {};
				for (const [k, v] of Object.entries(f.properties)) if (TAGS.has(k)) tags[k] = v;
				for (const ring of f.loadGeometry()) {
					for (const p of ring) {
						const x = Math.round((dx * EXTENT + p.x * scale) / 2);
						const y = Math.round((dy * EXTENT + p.y * scale) / 2);
						const key = `${name}|${tags.name}|${tags.class}|${x >> 4}|${y >> 4}`;
						if (seen.has(key)) continue;
						seen.add(key);
						layers[name].features.push({ type: 1, geometry: [[x, y]], tags });
					}
				}
			}
		}
	}
	return fromGeojsonVt(layers as never, { version: 2, extent: EXTENT });
}

/** The `places://` protocol: fetches the next zoom's four label tiles through the
 *  server's cache and merges their places. A child that fails is left out. */
export const placesProtocol: AddProtocolAction = async (params, abort) => {
	const m = /^places:\/\/(\d+)\/(\d+)\/(\d+)/.exec(params.url);
	if (!m) throw new Error(`not a places tile: ${params.url}`);
	const [z, x, y] = m.slice(1).map(Number);
	const children = await Promise.all(
		CHILDREN.map(async ([dx, dy]): Promise<Child> => {
			try {
				const r = await fetch(`/api/tiles/labels/${z + 1}/${2 * x + dx}/${2 * y + dy}.pbf`, {
					signal: abort.signal
				});
				if (!r.ok) return { dx, dy, tile: null };
				return {
					dx,
					dy,
					tile: new VectorTile(new PbfReader(new Uint8Array(await r.arrayBuffer())))
				};
			} catch (e) {
				if (abort.signal.aborted) throw e;
				return { dx, dy, tile: null };
			}
		})
	);
	const data = mergePlaces(children);
	return {
		data: data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer
	};
};
