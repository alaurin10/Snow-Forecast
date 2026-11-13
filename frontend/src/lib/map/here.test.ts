import { describe, expect, it } from 'vitest';
import type { MapStation, ObsProps, ZoneFeature } from '../types.gen';
import {
	areaText,
	glacierArea,
	hereItems,
	osmLink,
	polygonArea,
	ringArea,
	SPOT,
	tapTargets,
	wikiLink,
	type Hit
} from './here';

const hits: Hit[] = [
	{ layer: 'ates-fill', properties: { rating: 'complex', name: 'Bowl', file: 'area.geojson' } },
	{ layer: 'glaciers', properties: { kind: 'glacier', name: 'Snow Glacier', osm: 'w9' } },
	{
		layer: 'runs',
		properties: { kind: 'run', type: 'downhill', difficulty: 'advanced', name: 'Chute', osm: 'w4' },
		geometry: {
			type: 'LineString',
			coordinates: [
				[-121, 47],
				[-121.01, 47.01]
			]
		}
	},
	{
		layer: 'places',
		properties: { kind: 'hut', type: 'alpine_hut', name: 'Hut', ele: 1880, osm: 'n1' }
	},
	// The same hut again (two tiles): one item.
	{
		layer: 'places',
		properties: { kind: 'hut', type: 'alpine_hut', name: 'Hut', ele: 1880, osm: 'n1' }
	}
];

describe('hereItems', () => {
	it('ranks huts, then runs, glaciers and ATES, without repeats', () => {
		const items = hereItems(hits, 'metric', null);
		expect(items.map((i) => [i.type, i.kind, i.name])).toEqual([
			['place', 'Hut', 'Hut'],
			['route', 'Run', 'Chute'],
			['glacier', 'Glacier', 'Snow Glacier'],
			['ates', 'ATES', 'Complex']
		]);
		expect(items[0]).toMatchObject({ ele: 1880, link: 'https://www.openstreetmap.org/node/1' });
		expect(items[1]).toMatchObject({ detail: 'advanced', osm: 'w4' });
		expect(items[1].line).toHaveLength(2);
		expect(items[2]).toMatchObject({ osm: 'w9', link: 'https://www.openstreetmap.org/way/9' });
		expect(items[3]).toMatchObject({ detail: 'Bowl', file: 'area.geojson', color: '#1b1b1f' });
	});

	it('links a mapped Wikipedia article', () => {
		expect(wikiLink('en:Coleman Glacier')).toBe('https://en.wikipedia.org/wiki/Coleman_Glacier');
		expect(wikiLink('fr:Glacier d’Argentière')).toBe(
			'https://fr.wikipedia.org/wiki/Glacier_d%E2%80%99Argenti%C3%A8re'
		);
		expect(wikiLink('Coleman Glacier')).toBeUndefined();
		expect(wikiLink('javascript:alert(1)')).toBeUndefined();
	});

	it('links only well-formed OpenStreetMap ids', () => {
		expect(osmLink('r11')).toBe('https://www.openstreetmap.org/relation/11');
		expect(osmLink('x1')).toBeUndefined();
		expect(osmLink('n1/../x')).toBeUndefined();
		expect(osmLink(undefined)).toBeUndefined();
	});
});

describe('tapTargets', () => {
	const station = { name: 'Olallie Meadows' } as MapStation;
	const report = { title: 'Whumpfing' } as ObsProps;
	const zone = { id: 'z' } as ZoneFeature;

	it('zoomed out: what was aimed at, then the zone, the spot, and areas last', () => {
		const here = hereItems(hits, 'metric', null);
		const ts = tapTargets({ station, report, here, zone, spot: true });
		expect(ts.map((t) => t.chip)).toEqual([
			'Station',
			'Report',
			'Hut',
			'Run',
			'Zone',
			'This spot',
			'Glacier',
			'ATES'
		]);
		expect(ts).toContain(SPOT);
	});

	it('zoomed in: the spot before glaciers and ATES, and the zone last', () => {
		const here = hereItems(hits, 'metric', null);
		const ts = tapTargets({ here, zone, spot: true, close: true });
		expect(ts.map((t) => t.chip)).toEqual(['Hut', 'Run', 'This spot', 'Glacier', 'ATES', 'Zone']);
		// A glacier alone: the spot first, the glacier one chip away.
		const ice = here.filter((i) => i.type === 'glacier');
		expect(tapTargets({ here: ice, spot: true, close: true }).map((t) => t.chip)).toEqual([
			'This spot',
			'Glacier'
		]);
		expect(tapTargets({ zone, spot: true })[0].kind).toBe('zone');
	});

	it('is just the spot on bare ground, and empty without terrain', () => {
		expect(tapTargets({ spot: true })).toEqual([SPOT]);
		expect(tapTargets({ spot: false })).toEqual([]);
		expect(tapTargets({ zone, spot: false }).map((t) => t.kind)).toEqual(['zone']);
	});
});

describe('glacier area', () => {
	// A 0.1° square at 50° N: 0.1° of latitude is ~11.12 km, of longitude ~7.15 km.
	const sq = (w: number, s: number, d: number): [number, number][] => [
		[w, s],
		[w + d, s],
		[w + d, s + d],
		[w, s + d],
		[w, s]
	];

	it('measures a ring on the sphere, either way round', () => {
		const a = ringArea(sq(-122, 50, 0.1));
		expect(a / 1e6).toBeCloseTo(79.6, 0);
		expect(ringArea([...sq(-122, 50, 0.1)].reverse())).toBeCloseTo(a, 3);
		expect(polygonArea([sq(-122, 50, 0.1), sq(-121.95, 50.02, 0.01)])).toBeCloseTo(
			a - ringArea(sq(-121.95, 50.02, 0.01)),
			3
		);
	});

	const aRings = [sq(-122, 50, 0.1), sq(-121.95, 50.02, 0.01)];
	const fc: GeoJSON.FeatureCollection = {
		type: 'FeatureCollection',
		features: [
			{
				type: 'Feature',
				properties: { kind: 'glacier', name: 'A', osm: 'w1' },
				geometry: { type: 'Polygon', coordinates: aRings }
			},
			{
				type: 'Feature',
				properties: { kind: 'glacier', name: 'B', osm: 'r2' },
				geometry: {
					type: 'MultiPolygon',
					coordinates: [[sq(-121, 50, 0.01)], [sq(-120.9, 50, 0.01)]]
				}
			},
			{
				type: 'Feature',
				properties: { kind: 'run', osm: 'w3' },
				geometry: { type: 'Polygon', coordinates: [sq(-123, 50, 0.1)] }
			}
		]
	};

	it('finds the whole glacier by id, or by the point tapped', () => {
		const b = glacierArea(fc, 0, 0, 'r2')!;
		expect(b).toBeCloseTo(2 * ringArea(sq(-121, 50, 0.01)), 0);
		expect(glacierArea(fc, -121.99, 50.01)).toBeCloseTo(polygonArea(aRings), 0);
		// In the hole, on a run, or nowhere: not a glacier.
		expect(glacierArea(fc, -121.945, 50.025)).toBeNull();
		expect(glacierArea(fc, -122.95, 50.05)).toBeNull();
	});

	it('says an area in hectares or km², acres or square miles', () => {
		expect(areaText(42_000, 'metric')).toBe('4 ha');
		expect(areaText(2_340_000, 'metric')).toBe('2.3 km²');
		expect(areaText(42_000_000, 'metric')).toBe('42 km²');
		expect(areaText(42_000, 'imperial')).toBe('10 acres');
		expect(areaText(5_000_000, 'imperial')).toBe('1.9 sq mi');
	});
});
