// Terrain-adjusted snow totals: when the tiles take over, and snow read off a point's
// numbers by elevation.
import { describe, expect, it, vi } from 'vitest';
import {
	elevationLadder,
	setSnowTiles,
	SNOWTILES_ID,
	SNOWTILES_ZOOM,
	snowAtElevation,
	snowTilesUrl
} from './layers/snowtiles';

const ELEVS = Array.from({ length: 19 }, (_, i) => i * 250);
const BOUNDS: [[number, number], [number, number]] = [
	[31, -134],
	[57, -102]
];

describe('snow totals adjusted to terrain', () => {
	it('takes over from the picture zoomed in, when the server has tiles', () => {
		const t = { tiles: '/api/snowtiles/0123456789abcdef/{z}/{x}/{y}.png' };
		expect(snowTilesUrl(t, SNOWTILES_ZOOM)).toBe(t.tiles);
		expect(snowTilesUrl(t, SNOWTILES_ZOOM - 0.1)).toBeNull();
		expect(snowTilesUrl({ tiles: null }, 12)).toBeNull();
		expect(snowTilesUrl(undefined, 12)).toBeNull();
	});

	it('reads snow at any elevation between the bands', () => {
		const cm = ELEVS.map((z) => Math.max(0, (z - 1000) / 25)); // 0 to 1,000 m, then 1 cm / 25 m
		expect(snowAtElevation(cm, ELEVS, 500)).toBe(0);
		expect(snowAtElevation(cm, ELEVS, 1125)).toBeCloseTo(5);
		expect(snowAtElevation(cm, ELEVS, 9000)).toBe(140);
		expect(snowAtElevation(cm, ELEVS, -20)).toBe(0);
		expect(snowAtElevation(null, ELEVS, 1000)).toBeNull();
		expect(snowAtElevation(cm, ELEVS, null)).toBeNull();
		expect(snowAtElevation(cm.slice(1), ELEVS, 1000)).toBeNull(); // mismatched
	});

	it('picks round heights around the spot', () => {
		expect(elevationLadder(1850, false)).toEqual([1000, 1500, 2000, 2500]);
		expect(elevationLadder(300, false)).toEqual([500, 1000, 1500, 2000]);
		expect(elevationLadder(4300, false)).toEqual([3500, 4000, 4500]);
		const ft = elevationLadder(1850, true).map((m) => Math.round(m / 0.3048));
		expect(ft).toEqual([4500, 6000, 7500, 9000]);
	});

	it('adds the tiles once, swaps them with the window, and keeps the picture out of their way', () => {
		const layers = new Set<string>(['precip']);
		const sources = new Map<string, { tiles: string[] }>();
		const map = {
			getLayer: (id: string) => (layers.has(id) ? { id } : undefined),
			getSource: (id: string) => sources.get(id),
			addSource: vi.fn((id: string, spec: { tiles: string[] }) => sources.set(id, spec)),
			addLayer: vi.fn((spec: { id: string }) => layers.add(spec.id)),
			removeLayer: vi.fn((id: string) => layers.delete(id)),
			removeSource: vi.fn((id: string) => sources.delete(id)),
			setLayerZoomRange: vi.fn()
		};
		const opts = { bounds: BOUNDS, opacity: ['literal', 0.7] as never, pictureId: 'precip' };
		const set = (tiles: string | null) => setSnowTiles(map as never, tiles, opts);
		set('/a/{z}/{x}/{y}.png');
		expect(map.addSource).toHaveBeenCalledTimes(1);
		expect(map.addSource.mock.calls[0][1]).toMatchObject({
			type: 'raster',
			tileSize: 512,
			minzoom: SNOWTILES_ZOOM - 1,
			maxzoom: 11,
			bounds: [-134, 31, -102, 57]
		});
		expect(map.addLayer.mock.calls[0][0]).toMatchObject({ id: SNOWTILES_ID, minzoom: 8 });
		expect(map.setLayerZoomRange).toHaveBeenLastCalledWith('precip', 0, SNOWTILES_ZOOM);
		set('/a/{z}/{x}/{y}.png'); // the same: nothing redone
		expect(map.addSource).toHaveBeenCalledTimes(1);
		set('/b/{z}/{x}/{y}.png'); // another window
		expect(map.removeSource).toHaveBeenCalledTimes(1);
		expect(sources.get(SNOWTILES_ID)?.tiles).toEqual(['/b/{z}/{x}/{y}.png']);
		set(null); // another layer, or no tiles: the picture at every zoom again
		expect(layers.has(SNOWTILES_ID)).toBe(false);
		expect(map.setLayerZoomRange).toHaveBeenLastCalledWith('precip', 0, 24);
	});
});
