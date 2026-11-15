import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Map as MlMap } from 'maplibre-gl';
import { FrameStore, PrecipLayer } from './precipOverlay';

/** Just enough of a MapLibre map for the precipitation layer. */
function fakeMap(terrain: boolean) {
	const source = { play: vi.fn(), pause: vi.fn() };
	const releaseAllRTT = vi.fn();
	const map = {
		addSource: vi.fn(),
		addLayer: vi.fn(),
		getSource: () => source,
		triggerRepaint: vi.fn(),
		terrain: terrain ? { tileManager: { releaseAllRTT } } : null
	};
	return { map, source, releaseAllRTT };
}

describe('PrecipLayer', () => {
	afterEach(() => vi.unstubAllGlobals());
	const ctx = { clearRect: vi.fn(), drawImage: vi.fn() };
	// These tests run without a DOM: the layer only needs a canvas with a 2D context.
	const withCanvas = () =>
		vi.stubGlobal('document', { createElement: () => ({ getContext: () => ctx }) });
	const bounds: [[number, number], [number, number]] = [
		[31, -134],
		[57, -102]
	];

	it('uploads each frame, and redraws the 3D drape so the new frame shows over terrain', () => {
		withCanvas();
		const { map, source, releaseAllRTT } = fakeMap(true);
		const layer = new PrecipLayer(map as unknown as MlMap, bounds, 4, 4, 0.7);
		layer.draw('f1.png', null);
		layer.draw('f2.png', null);
		expect(source.pause).toHaveBeenCalledTimes(2);
		expect(releaseAllRTT).toHaveBeenCalledTimes(2);
		expect(map.triggerRepaint).toHaveBeenCalledTimes(2);
		expect(layer.showing).toBe('f2.png');
	});

	it('in 2D there is no drape to redraw', () => {
		withCanvas();
		const { map, source } = fakeMap(false);
		new PrecipLayer(map as unknown as MlMap, bounds, 4, 4, 0.7).draw('f1.png', null);
		expect(source.pause).toHaveBeenCalledTimes(1);
		expect(map.triggerRepaint).not.toHaveBeenCalled();
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
