import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Map as MlMap } from 'maplibre-gl';
import { FrameStore, PrecipLayer } from './precipOverlay';

/** Just enough of a MapLibre map for the precipitation layer. */
function fakeMap(terrain: boolean) {
	const sources: Record<
		string,
		{ play: ReturnType<typeof vi.fn>; pause: ReturnType<typeof vi.fn> }
	> = {};
	const layers = new Set<string>();
	const paint: Record<string, Record<string, unknown>> = {};
	const listeners: (() => void)[] = [];
	const releaseAllRTT = vi.fn();
	const map = {
		addSource: vi.fn((id: string) => (sources[id] = { play: vi.fn(), pause: vi.fn() })),
		addLayer: vi.fn((l: { id: string; paint: Record<string, unknown> }) => {
			layers.add(l.id);
			paint[l.id] = { ...l.paint };
		}),
		getLayer: (id: string) => layers.has(id),
		getSource: (id: string) => sources[id],
		removeLayer: (id: string) => layers.delete(id),
		removeSource: (id: string) => delete sources[id],
		setPaintProperty: vi.fn((id: string, k: string, v: unknown) => (paint[id][k] = v)),
		on: vi.fn((_: string, f: () => void) => listeners.push(f)),
		off: vi.fn((_: string, f: () => void) => listeners.splice(listeners.indexOf(f), 1)),
		triggerRepaint: vi.fn(),
		terrain: terrain ? { tileManager: { releaseAllRTT } } : null
	};
	return { map, sources, paint, listeners, releaseAllRTT };
}

describe('PrecipLayer', () => {
	afterEach(() => vi.unstubAllGlobals());
	const ctx = {
		clearRect: vi.fn(),
		drawImage: vi.fn(),
		globalAlpha: 1,
		globalCompositeOperation: 'source-over'
	};
	// These tests run without a DOM: the layer only needs canvases with a 2D context.
	const withCanvas = () =>
		vi.stubGlobal('document', { createElement: () => ({ getContext: () => ctx }) });
	const bounds: [[number, number], [number, number]] = [
		[31, -134],
		[57, -102]
	];
	const bmp = {} as ImageBitmap;
	const [A, B] = PrecipLayer.IDS;

	it('draws each frame into the layer not showing, then fades it in over the other', () => {
		withCanvas();
		const { map, sources, paint } = fakeMap(false);
		const layer = new PrecipLayer(map as unknown as MlMap, bounds, 4, 4, 0.7);
		expect(paint[A]['raster-opacity']).toBe(0.7);
		expect(paint[B]['raster-opacity']).toBe(0);
		layer.draw('f1.png', bmp, 200);
		expect(sources[B].pause).toHaveBeenCalledTimes(1); // uploaded once
		expect(paint[B]).toMatchObject({
			'raster-opacity': 0.7,
			'raster-opacity-transition': { duration: 200, delay: 0 }
		});
		expect(paint[A]).toMatchObject({
			'raster-opacity': 0,
			'raster-opacity-transition': { duration: 200, delay: 0 }
		});
		layer.draw('f2.png', bmp, 200);
		expect(sources[A].pause).toHaveBeenCalledTimes(1);
		expect(paint[A]['raster-opacity']).toBe(0.7);
		expect(paint[B]['raster-opacity']).toBe(0);
		expect(layer.showing).toBe('f2.png');
		// The opacity follows the layer on screen.
		layer.setOpacity(0.5);
		expect(paint[A]['raster-opacity']).toBe(0.5);
		expect(paint[B]['raster-opacity']).toBe(0);
	});

	it('mixes the hand-over frame under the new one, each at its share', () => {
		withCanvas();
		const { map } = fakeMap(false);
		const seen: [number, string][] = [];
		ctx.drawImage.mockImplementation(() =>
			seen.push([ctx.globalAlpha, ctx.globalCompositeOperation])
		);
		const layer = new PrecipLayer(map as unknown as MlMap, bounds, 4, 4, 0.7);
		layer.draw('f1.png', bmp, 0, { bmp, weight: 0.25 });
		expect(seen).toEqual([
			[0.25, 'lighter'],
			[0.75, 'lighter']
		]);
		expect([ctx.globalAlpha, ctx.globalCompositeOperation]).toEqual([1, 'source-over']);
		ctx.drawImage.mockReset();
	});

	it('in 3D, redraws the drape through the fade, then stops', () => {
		withCanvas();
		const { map, listeners, releaseAllRTT } = fakeMap(true);
		let now = 1000;
		vi.stubGlobal('performance', { now: () => now });
		const layer = new PrecipLayer(map as unknown as MlMap, bounds, 4, 4, 0.7);
		layer.draw('f1.png', bmp, 200);
		expect(releaseAllRTT).toHaveBeenCalledTimes(1);
		expect(listeners).toHaveLength(1);
		listeners[0]();
		expect(releaseAllRTT).toHaveBeenCalledTimes(2);
		now += 300;
		listeners[0]();
		expect(listeners).toHaveLength(0);
		expect(map.triggerRepaint).toHaveBeenCalledTimes(2);
	});

	it('in 2D there is no drape to redraw', () => {
		withCanvas();
		const { map, listeners } = fakeMap(false);
		new PrecipLayer(map as unknown as MlMap, bounds, 4, 4, 0.7).draw('f1.png', null, 200);
		expect(map.triggerRepaint).not.toHaveBeenCalled();
		expect(listeners).toHaveLength(0);
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
