// Terrain-adjusted snow totals: when the tiles take over, and snow read off a point's
// numbers by elevation.
import { describe, expect, it, vi } from 'vitest';
import {
	elevationLadder,
	setSnowTiles,
	SNOWTILES_ID,
	snowTileLayers,
	snowTilesId,
	SNOWTILES_ZOOM,
	snowAtElevation,
	snowTilesUrl
} from './layers/snowtiles';
import { TOTAL_OPACITY } from './style';

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

	it('adds a window once, puts the next over it, and drops the old once the new is in', () => {
		vi.useFakeTimers();
		const order: string[] = ['precip', 'precip-b'];
		const sources = new Map<string, { tiles: string[]; setTiles: ReturnType<typeof vi.fn> }>();
		const handlers: Record<string, ((e: { sourceId?: string }) => void)[]> = {};
		const loaded = new Set<string>();
		const map = {
			getLayer: (id: string) => (order.includes(id) ? { id } : undefined),
			getLayersOrder: () => [...order],
			getSource: (id: string) => sources.get(id),
			addSource: vi.fn((id: string, spec: { tiles: string[] }) =>
				sources.set(id, { ...spec, setTiles: vi.fn() })
			),
			addLayer: vi.fn((spec: { id: string }, before?: string) =>
				order.splice(before ? order.indexOf(before) : order.length, 0, spec.id)
			),
			removeLayer: vi.fn((id: string) => order.splice(order.indexOf(id), 1)),
			removeSource: vi.fn((id: string) => sources.delete(id)),
			isSourceLoaded: (id: string) => loaded.has(id),
			on: (ev: string, f: (e: { sourceId?: string }) => void) => (handlers[ev] ??= []).push(f),
			off: (ev: string, f: (e: { sourceId?: string }) => void) =>
				handlers[ev]?.splice(handlers[ev].indexOf(f), 1),
			fire: (ev: string, e: { sourceId?: string }) => [...(handlers[ev] ?? [])].forEach((f) => f(e))
		};
		const opts = { bounds: BOUNDS, opacity: TOTAL_OPACITY, beforeId: 'precip' };
		const set = (tiles: string | null) => setSnowTiles(map as never, tiles, opts);
		const A = '/api/snowtiles/aaaaaaaaaaaaaaaa/{z}/{x}/{y}.png';
		const B = '/api/snowtiles/bbbbbbbbbbbbbbbb/{z}/{x}/{y}.png';
		const a = snowTilesId(A);
		const b = snowTilesId(B);
		expect(a).toBe(`${SNOWTILES_ID}-aaaaaaaaaaaaaaaa`);
		set(A);
		expect(map.addSource).toHaveBeenCalledTimes(1);
		expect(map.addSource.mock.calls[0][1]).toMatchObject({
			type: 'raster',
			tileSize: 512,
			minzoom: SNOWTILES_ZOOM - 1,
			maxzoom: 11,
			bounds: [-134, 31, -102, 57]
		});
		// Up to where the opacity reaches 0, under the precipitation.
		expect(map.addLayer.mock.calls[0][0]).toMatchObject({ id: a, minzoom: 8, maxzoom: 15 });
		expect(snowTileLayers(map as never)).toEqual([a]);
		set(A); // the same: nothing redone
		expect(map.addSource).toHaveBeenCalledTimes(1);

		// Another window: on top, the old one kept until the new one's tiles are in.
		set(B);
		expect(snowTileLayers(map as never)).toEqual([a, b]);
		map.fire('sourcedata', { sourceId: b });
		expect(snowTileLayers(map as never)).toEqual([a, b]); // not loaded yet
		loaded.add(b);
		map.fire('sourcedata', { sourceId: b });
		expect(snowTileLayers(map as never)).toEqual([b]);

		// A tile that fails is asked for again, a few times.
		map.fire('error', { sourceId: b });
		map.fire('error', { sourceId: b }); // one retry at a time
		vi.advanceTimersByTime(1500);
		expect(sources.get(b)!.setTiles).toHaveBeenCalledTimes(1);
		expect(sources.get(b)!.setTiles).toHaveBeenCalledWith([B]);
		for (const ms of [4000, 10000, 30000]) {
			map.fire('error', { sourceId: b });
			vi.advanceTimersByTime(ms);
		}
		expect(sources.get(b)!.setTiles).toHaveBeenCalledTimes(3);

		// Slow tiles: the old window goes after a while anyway.
		set(A);
		expect(snowTileLayers(map as never)).toEqual([b, a]);
		vi.advanceTimersByTime(8000);
		expect(snowTileLayers(map as never)).toEqual([a]);

		set(null); // another layer, or no tiles
		expect(snowTileLayers(map as never)).toEqual([]);
		vi.useRealTimers();
	});
});
