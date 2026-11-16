import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Map as MlMap } from 'maplibre-gl';
import { FrameStore, PrecipLayer } from './precipOverlay';

/** Just enough of a MapLibre map for the precipitation layer: a view over the West box's
 *  middle, 800 px across. */
function fakeMap(terrain: boolean) {
	type Src = {
		play: ReturnType<typeof vi.fn>;
		pause: ReturnType<typeof vi.fn>;
		setCoordinates: ReturnType<typeof vi.fn>;
	};
	const sources: Record<string, Src> = {};
	const layers = new Set<string>();
	const paint: Record<string, Record<string, unknown>> = {};
	const on: Record<string, (() => void)[]> = {};
	const releaseAllRTT = vi.fn();
	let view = { w: -122, e: -114, n: 47, s: 41 };
	const map = {
		addSource: vi.fn(
			(id: string) => (sources[id] = { play: vi.fn(), pause: vi.fn(), setCoordinates: vi.fn() })
		),
		addLayer: vi.fn((l: { id: string; paint: Record<string, unknown> }) => {
			layers.add(l.id);
			paint[l.id] = { ...l.paint };
		}),
		getLayer: (id: string) => layers.has(id),
		getSource: (id: string) => sources[id],
		removeLayer: (id: string) => layers.delete(id),
		removeSource: (id: string) => delete sources[id],
		setPaintProperty: vi.fn((id: string, k: string, v: unknown) => (paint[id][k] = v)),
		on: vi.fn((ev: string, f: () => void) => (on[ev] ??= []).push(f)),
		off: vi.fn((ev: string, f: () => void) => on[ev]?.splice(on[ev].indexOf(f), 1)),
		getBounds: () => ({
			getWest: () => view.w,
			getEast: () => view.e,
			getNorth: () => view.n,
			getSouth: () => view.s
		}),
		getCanvas: () => ({ width: 800 }),
		triggerRepaint: vi.fn(),
		terrain: terrain ? { tileManager: { releaseAllRTT } } : null
	};
	const moveTo = (v: typeof view) => {
		view = v;
		for (const f of on.moveend ?? []) f();
	};
	return { map, sources, paint, on, releaseAllRTT, moveTo };
}

describe('PrecipLayer', () => {
	afterEach(() => vi.unstubAllGlobals());
	const ctx = { clearRect: vi.fn(), drawImage: vi.fn(), imageSmoothingQuality: 'low' };
	// These tests run without a DOM: the layer only needs canvases with a 2D context (and
	// no WebGL, as in old browsers: fine frames are then drawn as pictures).
	const canvases: { width: number; height: number }[] = [];
	const withCanvas = () => {
		canvases.length = 0;
		vi.stubGlobal('document', {
			createElement: () => {
				const c = {
					width: 300,
					height: 150,
					getContext: (type: string) => (type === '2d' ? ctx : null)
				};
				canvases.push(c);
				return c;
			}
		});
	};
	// The West box, 1600 × 1000 frame pixels.
	const bounds: [[number, number], [number, number]] = [
		[31, -134],
		[57, -102]
	];
	const bmp = { width: 1600, height: 1000 } as ImageBitmap;
	const [A, B] = PrecipLayer.IDS;
	const make = (map: unknown) => new PrecipLayer(map as MlMap, bounds, 1600, 1000, 0.7);

	it('draws each frame into the layer not showing, then fades it in over the other', () => {
		withCanvas();
		const { map, sources, paint } = fakeMap(false);
		const layer = make(map);
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

	it("draws only the view and a margin, at the screen's resolution, where it lies", () => {
		withCanvas();
		const { map, sources } = fakeMap(false);
		ctx.drawImage.mockClear();
		make(map).draw('f1.png', bmp, 0, null, 'fine'); // no WebGL here: drawn as a picture
		// The view is 8° of the box's 32° across, from 12° in: frame pixels 600–1000, 500–1100
		// with the margin,
		// drawn 2 picture pixels to each (800 screen pixels over 400).
		const [, sx, , sw, , , , dw] = ctx.drawImage.mock.calls[0];
		expect([sx, sw, dw]).toEqual([500, 600, 1200]);
		const [nw, ne] = sources[B].setCoordinates.mock.calls[0][0];
		expect(nw[0]).toBeCloseTo(-124);
		expect(ne[0]).toBeCloseTo(-112);
		expect(nw[1]).toBeCloseTo(ne[1]);
	});

	it('draws the picture again for a new view once the map stops', () => {
		withCanvas();
		const { map, sources, paint, moveTo } = fakeMap(false);
		const layer = make(map);
		layer.draw('f1.png', bmp, 200);
		moveTo({ w: -130, e: -126, n: 55, s: 52 });
		// The layer on screen, in place: no fade.
		expect(sources[B].pause).toHaveBeenCalledTimes(2);
		expect(sources[B].setCoordinates.mock.calls[1][0][0][0]).toBeCloseTo(-131);
		expect(paint[B]['raster-opacity']).toBe(0.7);
		// Out of the box altogether: nothing drawn, nothing broken.
		moveTo({ w: 10, e: 20, n: 10, s: 0 });
		expect(canvases.some((c) => c.width === 1 && c.height === 1)).toBe(true);
		layer.remove();
		moveTo({ w: -122, e: -114, n: 47, s: 41 });
		expect(sources[B]).toBeUndefined();
	});

	it('in 3D, redraws the drape through the fade, then stops', () => {
		withCanvas();
		const { map, on, releaseAllRTT } = fakeMap(true);
		let now = 1000;
		vi.stubGlobal('performance', { now: () => now });
		make(map).draw('f1.png', bmp, 200);
		expect(releaseAllRTT).toHaveBeenCalledTimes(1);
		expect(on.render).toHaveLength(1);
		on.render[0]();
		expect(releaseAllRTT).toHaveBeenCalledTimes(2);
		now += 300;
		on.render[0]();
		expect(on.render).toHaveLength(0);
		expect(map.triggerRepaint).toHaveBeenCalledTimes(2);
	});

	it('in 2D there is no drape to redraw', () => {
		withCanvas();
		const { map, on } = fakeMap(false);
		make(map).draw('f1.png', null, 200);
		expect(map.triggerRepaint).not.toHaveBeenCalled();
		expect(on.render ?? []).toHaveLength(0);
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
