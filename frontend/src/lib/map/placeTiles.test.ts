// Town names a zoom sooner: one tile's places merged from the next zoom's four tiles.
import { describe, expect, it } from 'vitest';
import { VectorTile } from '@mapbox/vector-tile';
import { PbfReader } from 'pbf';
import { fromGeojsonVt } from '@maplibre/vt-pbf';
import { mergePlaces } from './placeTiles';

const child = (places: [string, string, number, number][]) =>
	new VectorTile(
		new PbfReader(
			fromGeojsonVt(
				{
					place: {
						features: places.map(([name, cls, x, y]) => ({
							type: 1,
							geometry: [[x, y]],
							tags: { name, class: cls, rank: 12, name_en: name }
						}))
					}
				} as never,
				{ version: 2, extent: 4096 }
			)
		)
	);

const read = (data: Uint8Array) => {
	const layer = new VectorTile(new PbfReader(data)).layers.place;
	return Array.from({ length: layer.length }, (_, i) => {
		const f = layer.feature(i);
		const p = f.loadGeometry()[0][0];
		return { ...(f.properties as Record<string, unknown>), x: p.x, y: p.y } as Record<
			string,
			unknown
		>;
	});
};

const poiChild = (pois: [string, string, number, number][]) =>
	new VectorTile(
		new PbfReader(
			fromGeojsonVt(
				{
					poi: {
						features: pois.map(([name, cls, x, y]) => ({
							type: 1,
							geometry: [[x, y]],
							tags: { name, class: cls, rank: 2 }
						}))
					}
				} as never,
				{ version: 2, extent: 4096 }
			)
		)
	);

const parkChild = (name: string, cls: string, ring: [number, number][]) =>
	new VectorTile(
		new PbfReader(
			fromGeojsonVt(
				{
					park: { features: [{ type: 3, geometry: [ring], tags: { name, class: cls } }] }
				} as never,
				{ version: 2, extent: 4096 }
			)
		)
	);

describe('places tiles', () => {
	it('names a big park in each quarter whose middle it covers', () => {
		const all: [number, number][] = [
			[0, 0],
			[4096, 0],
			[4096, 4096],
			[0, 4096],
			[0, 0]
		];
		const corner: [number, number][] = [
			[0, 0],
			[1000, 0],
			[1000, 1000],
			[0, 1000],
			[0, 0]
		];
		const data = mergePlaces([
			{
				dx: 0,
				dy: 0,
				tile: parkChild('Okanogan-Wenatchee National Forest', 'forest_reserve', all)
			},
			{
				dx: 1,
				dy: 0,
				tile: parkChild('Okanogan-Wenatchee National Forest', 'forest_reserve', corner)
			},
			{ dx: 0, dy: 1, tile: parkChild('Tiger Mountain State Forest', 'sustainable', all) }
		]);
		const layer = new VectorTile(new PbfReader(data)).layers.park_label;
		const got = Array.from({ length: layer.length }, (_, i) => {
			const f = layer.feature(i);
			const p = f.loadGeometry()[0][0];
			return [f.properties.name, p.x, p.y];
		});
		// Only the first quarter's middle is in the forest; a state forest isn't a big park.
		expect(got).toEqual([['Okanogan-Wenatchee National Forest', 1024, 1024]]);
	});

	it('keeps parks and golf courses among the points of interest, nothing else', () => {
		const data = mergePlaces([
			{
				dx: 0,
				dy: 0,
				tile: poiChild([
					['Rainbow Park', 'park', 100, 100],
					['Whistler Golf Course', 'golf', 200, 200],
					['Southbound Hwy 99 at Blueberry', 'bus', 300, 300],
					['Golf Patron Parking Only', 'parking', 400, 400]
				])
			}
		]);
		const layer = new VectorTile(new PbfReader(data)).layers.poi;
		const names = Array.from({ length: layer.length }, (_, i) => layer.feature(i).properties.name);
		expect(names).toEqual(['Rainbow Park', 'Whistler Golf Course']);
	});

	it('scales each child’s places into its quarter, keeping the name, class and rank', () => {
		const out = read(
			mergePlaces([
				{ dx: 0, dy: 0, tile: child([['Redmond', 'town', 2048, 2048]]) },
				{ dx: 1, dy: 1, tile: child([['Snoqualmie Pass', 'hamlet', 0, 4096]]) },
				{ dx: 1, dy: 0, tile: null } // a child that failed is left out
			])
		);
		expect(out).toEqual([
			{ name: 'Redmond', class: 'town', rank: 12, x: 1024, y: 1024 },
			{ name: 'Snoqualmie Pass', class: 'hamlet', rank: 12, x: 2048, y: 4096 }
		]);
	});

	it('keeps a place once when two children both carry it (tiles overlap at edges)', () => {
		const out = read(
			mergePlaces([
				{ dx: 0, dy: 0, tile: child([['Hyak', 'hamlet', 4100, 100]]) },
				{ dx: 1, dy: 0, tile: child([['Hyak', 'hamlet', 4, 100]]) }
			])
		);
		expect(out.map((p) => p.name)).toEqual(['Hyak']);
	});
});
