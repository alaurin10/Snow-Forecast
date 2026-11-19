// The Recent satellite layers: every location's views in order, the old ones kept until
// the new ones' tiles are in.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setRecent, recentLayers } from './sat';
import type { RecentSource, RecentSpec } from '../sat';

/** Enough of a MapLibre map: an ordered list of layers, sources, and sourcedata. */
function fakeMap() {
	const order: string[] = [];
	const sources = new Set<string>();
	const loaded = new Set<string>();
	const handlers = new Set<(e: { sourceId?: string }) => void>();
	const map = {
		getLayersOrder: () => [...order],
		getLayer: (id: string) => (order.includes(id) ? { id } : undefined),
		getSource: (id: string) => (sources.has(id) ? { id } : undefined),
		addSource: (id: string) => void sources.add(id),
		removeSource: (id: string) => void sources.delete(id),
		addLayer: (l: { id: string }, before?: string) => {
			const i = before ? order.indexOf(before) : -1;
			order.splice(i < 0 ? order.length : i, 0, l.id);
		},
		removeLayer: (id: string) => void order.splice(order.indexOf(id), 1),
		moveLayer: (id: string, before?: string) => {
			order.splice(order.indexOf(id), 1);
			const i = before ? order.indexOf(before) : -1;
			order.splice(i < 0 ? order.length : i, 0, id);
		},
		isSourceLoaded: (id: string) => loaded.has(id),
		on: (_: string, f: (e: { sourceId?: string }) => void) => void handlers.add(f),
		off: (_: string, f: (e: { sourceId?: string }) => void) => void handlers.delete(f)
	};
	const load = (id: string) => {
		loaded.add(id);
		for (const f of [...handlers]) f({ sourceId: id });
	};
	return { map: map as never, order, load };
}

const src = (id: string): RecentSource => ({
	id,
	tiles: [`/t/${id}/{z}/{x}/{y}`],
	tileSize: 512,
	minzoom: 7,
	maxzoom: 13,
	attribution: ''
});
const spec = (wides: string[], views: string[]): RecentSpec => ({
	viirs: src('viirs-natural-2026-11-10'),
	wides: wides.map(src),
	views: views.map(src),
	dates: null
});

describe('recent satellite layers', () => {
	afterEach(() => vi.useRealTimers());

	it('draws the mosaic, then every wide view, then every 10 m view, under the shading', () => {
		const { map, order } = fakeMap();
		order.push('shade');
		setRecent(map, spec(['wide-a', 'wide-b'], ['view-a', 'view-b']), 'shade');
		expect(order).toEqual([
			'recent-viirs-natural-2026-11-10',
			'recent-wide-a',
			'recent-wide-b',
			'recent-view-a',
			'recent-view-b',
			'shade'
		]);
	});

	it('keeps the views it replaces until the new ones are in, then removes them', () => {
		vi.useFakeTimers();
		const { map, order, load } = fakeMap();
		setRecent(map, spec(['wide-a'], ['view-a', 'view-b']));
		// Step to another view of b, and the nearest location becomes a (on top).
		setRecent(map, spec(['wide-a'], ['view-b2', 'view-a']));
		// The old view stays, over the wide views and under the new ones, till they load.
		expect(recentLayers(map)).toEqual([
			'recent-viirs-natural-2026-11-10',
			'recent-wide-a',
			'recent-view-b',
			'recent-view-b2',
			'recent-view-a'
		]);
		load('recent-view-b2');
		expect(order).not.toContain('recent-view-b');
		// Dropping a view with nothing new to wait for removes it at once.
		setRecent(map, spec([], ['view-a']));
		expect(recentLayers(map)).toEqual(['recent-viirs-natural-2026-11-10', 'recent-view-a']);
		// A slow new view hands over after a few seconds anyway.
		setRecent(map, spec([], ['view-c']));
		expect(recentLayers(map)).toContain('recent-view-a');
		vi.advanceTimersByTime(7000);
		expect(recentLayers(map)).toEqual(['recent-viirs-natural-2026-11-10', 'recent-view-c']);
		// Off: nothing left.
		setRecent(map, { viirs: null, wides: [], views: [], dates: null });
		expect(recentLayers(map)).toEqual([]);
	});
});
