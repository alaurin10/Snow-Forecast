import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Map as MlMap } from 'maplibre-gl';
import { FrameStore, PrecipLayer } from './precipOverlay';

/** Just enough of a MapLibre map for the precipitation layer (a custom layer, added
 *  but not drawn: no WebGL here). */
function fakeMap() {
	const layers: Record<string, { terrainTileRevision: number; id: string }> = {};
	const on: Record<string, (() => void)[]> = {};
	let terrain = false;
	const map = {
		addLayer: vi.fn((l: { id: string; terrainTileRevision: number }) => (layers[l.id] = l)),
		getLayer: (id: string) => layers[id],
		removeLayer: vi.fn((id: string) => delete layers[id]),
		addSource: vi.fn(),
		getSource: vi.fn(() => ({ play: vi.fn(), pause: vi.fn() })),
		removeSource: vi.fn(),
		setPaintProperty: vi.fn(),
		setLayoutProperty: vi.fn(),
		on: vi.fn((ev: string, f: () => void) => (on[ev] ??= []).push(f)),
		off: vi.fn((ev: string, f: () => void) => on[ev]?.splice(on[ev].indexOf(f), 1)),
		getTerrain: () => (terrain ? {} : null),
		triggerRepaint: vi.fn(),
		getZoom: () => 8
	};
	const set3d = (v: boolean) => {
		terrain = v;
		for (const f of on.terrain ?? []) f();
	};
	return { map, layers, set3d, on };
}

describe('PrecipLayer', () => {
	afterEach(() => vi.unstubAllGlobals());
	const bounds: [[number, number], [number, number]] = [
		[31, -134],
		[57, -102]
	];
	const bmp = { width: 1600, height: 1000 } as ImageBitmap;
	const make = (map: unknown) => new PrecipLayer(map as MlMap, bounds, 1600, 1000, 0.7, 'labels');

	it('is a custom layer flat, and a draped picture in 3D, under the given layer', () => {
		const { map, layers, set3d, on } = fakeMap();
		const canvas = {
			width: 0,
			height: 0,
			getContext: () => ({ clearRect: vi.fn(), drawImage: vi.fn() })
		};
		vi.stubGlobal('document', { createElement: () => canvas });
		const layer = make(map);
		expect(map.addLayer).toHaveBeenCalledWith(
			expect.objectContaining({ type: 'custom' }),
			'labels'
		);
		expect(typeof (layers[PrecipLayer.ID] as unknown as Record<string, unknown>).render).toBe(
			'function'
		);
		layer.draw('f1.png', bmp, 0, null, 'picture');
		expect(map.addSource).not.toHaveBeenCalled(); // no 3D picture until 3D is on
		set3d(true);
		expect(map.addSource).toHaveBeenCalledWith(
			PrecipLayer.ID_3D,
			expect.objectContaining({ type: 'canvas' })
		);
		expect(layers[PrecipLayer.ID_3D]).toBeDefined();
		expect(map.setLayoutProperty).toHaveBeenLastCalledWith(
			PrecipLayer.ID_3D,
			'visibility',
			'visible'
		);
		expect([canvas.width, canvas.height]).toEqual([1600, 1000]);
		set3d(false);
		expect(map.setLayoutProperty).toHaveBeenLastCalledWith(PrecipLayer.ID_3D, 'visibility', 'none');
		layer.remove();
		expect(on.terrain).toHaveLength(0);
		expect(map.removeSource).toHaveBeenCalledWith(PrecipLayer.ID_3D);
	});

	it('asks for a redraw (and, in 3D, new terrain tiles) for each frame, and on every frame of a fade', () => {
		const { map, layers } = fakeMap();
		const frames: (() => void)[] = [];
		vi.stubGlobal('requestAnimationFrame', (f: () => void) => frames.push(f));
		vi.stubGlobal('cancelAnimationFrame', () => {});
		let now = 1000;
		vi.stubGlobal('performance', { now: () => now });
		const layer = make(map);
		const rev = () => layers[PrecipLayer.ID].terrainTileRevision;
		layer.draw('f1.png', bmp, 0);
		expect(layer.showing).toBe('f1.png');
		expect(rev()).toBe(1);
		expect(frames).toHaveLength(0); // no fade, no animation
		layer.draw('f2.png', bmp, 200, null, 'fine');
		expect(rev()).toBe(2);
		expect(frames).toHaveLength(1);
		now += 100;
		frames.shift()!();
		expect(rev()).toBe(3);
		expect(frames).toHaveLength(1); // still fading
		now += 150;
		frames.shift()!();
		expect(frames).toHaveLength(0); // done
		expect(map.triggerRepaint).toHaveBeenCalledTimes(4);
		layer.setOpacity(0.5);
		expect(rev()).toBe(5);
		layer.remove();
		expect(map.removeLayer).toHaveBeenCalledWith(PrecipLayer.ID);
	});
});

describe('FrameStore', () => {
	afterEach(() => vi.unstubAllGlobals());
	/** Bitmaps that record being closed; decodes finish when `finish` is called. */
	function stubs() {
		const made: { file: string; closed: boolean; close: () => void }[] = [];
		const pending: (() => void)[] = [];
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => ({ ok: true, blob: async () => ({ url }) }))
		);
		vi.stubGlobal(
			'createImageBitmap',
			vi.fn(
				(blob: { url: string }) =>
					new Promise((resolve) =>
						pending.push(() => {
							const b = {
								file: blob.url,
								closed: false,
								close() {
									b.closed = true;
								}
							};
							made.push(b);
							resolve(b);
						})
					)
			)
		);
		const finish = async () => {
			while (!pending.length) await new Promise((r) => setTimeout(r));
			pending.shift()!();
		};
		return { made, finish };
	}

	it('decodes a frame once when it is asked for twice at the same time', async () => {
		const { made, finish } = stubs();
		const store = new FrameStore();
		const f = { file: 'r1-000000000000.png' };
		const a = store.bitmap(f);
		const b = store.bitmap(f);
		await finish();
		expect(await a).toBe(await b);
		expect(made).toHaveLength(1);
		expect(createImageBitmap).toHaveBeenCalledTimes(1);
	});

	it('closes a bitmap that finishes decoding after the map closed', async () => {
		const { made, finish } = stubs();
		const store = new FrameStore();
		const p = store.bitmap({ file: 'r1-000000000000.png' });
		while (!vi.mocked(createImageBitmap).mock.calls.length) await new Promise((r) => setTimeout(r));
		store.clear();
		await finish();
		expect(await p).toBeNull();
		expect(made[0].closed).toBe(true);
	});

	it('cancels downloads under way when the map closes', async () => {
		let signal: AbortSignal | undefined;
		vi.stubGlobal(
			'fetch',
			vi.fn((_url: string, init: { signal: AbortSignal }) => {
				signal = init.signal;
				return new Promise(() => {});
			})
		);
		const store = new FrameStore();
		void store.blob({ file: 'r1-000000000000.png' });
		await new Promise((r) => setTimeout(r));
		expect(signal?.aborted).toBe(false);
		store.clear();
		expect(signal?.aborted).toBe(true);
	});
});
