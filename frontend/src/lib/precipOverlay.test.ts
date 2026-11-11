import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Map as MlMap } from 'maplibre-gl';
import { PrecipLayer } from './precipOverlay';

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
