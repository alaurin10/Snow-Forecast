// The tiles' water names are left out where the server's own file names them.
import { describe, expect, it, vi } from 'vitest';
import { boxesPolygon, outside, useOwnLabels } from './labels';
import { TILE_WATER_LAYERS } from '../style';

describe('own labels', () => {
	const boxes: [number, number, number, number][] = [[-121.66, 47.26, -121.18, 47.58]];

	it('makes the boxes one MultiPolygon and keeps a layer’s own filter', () => {
		expect(boxesPolygon(boxes).coordinates[0][0]).toEqual([
			[-121.66, 47.26],
			[-121.18, 47.26],
			[-121.18, 47.58],
			[-121.66, 47.58],
			[-121.66, 47.26]
		]);
		const f = outside(['==', ['get', 'class'], 'river'], boxes) as unknown[];
		expect(f[0]).toBe('all');
		expect(f[1]).toEqual(['==', ['get', 'class'], 'river']);
		expect(f[2]).toEqual(['!', ['within', boxesPolygon(boxes)]]);
	});

	it('filters the tiles’ water layers once the file says where it covers', async () => {
		const set = vi.fn();
		const map = {
			getLayer: () => ({}),
			getFilter: () => null,
			setFilter: set
		} as never;
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ boxes, features: [] })));
		vi.stubGlobal('fetch', fetchMock);
		await useOwnLabels(map);
		expect(set.mock.calls.map((c) => c[0])).toEqual(TILE_WATER_LAYERS);
		set.mockClear();
		fetchMock.mockImplementation(async () => new Response('', { status: 503 }));
		await useOwnLabels(map); // no file yet: the tiles name everything
		expect(set).not.toHaveBeenCalled();
		vi.unstubAllGlobals();
	});
});
