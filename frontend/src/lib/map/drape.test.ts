import { describe, expect, it, vi } from 'vitest';
import type { Map as MlMap } from 'maplibre-gl';
import { setDrapeQuality } from './drape';

/** The parts of a MapLibre map with 3D terrain on that setDrapeQuality touches. */
function fakeMap(tileSize = 1024) {
	const releaseAllRTT = vi.fn();
	const rtt = { rttSize: tileSize * 2 };
	const map = {
		terrain: { tileManager: { tileSize, releaseAllRTT } },
		painter: { renderToTexture: rtt }
	};
	return { map: map as unknown as MlMap, rtt, releaseAllRTT };
}

describe('setDrapeQuality', () => {
	it('draws the drape at one texel per terrain tile pixel by default', () => {
		const { map, rtt, releaseAllRTT } = fakeMap();
		expect(setDrapeQuality(map)).toBe(true);
		expect(rtt.rttSize).toBe(1024);
		expect(releaseAllRTT).toHaveBeenCalledOnce();
	});

	it('leaves a drape already at that size alone', () => {
		const { map, rtt, releaseAllRTT } = fakeMap(512);
		rtt.rttSize = 512;
		expect(setDrapeQuality(map, 1)).toBe(true);
		expect(releaseAllRTT).not.toHaveBeenCalled();
	});

	it('does nothing without 3D terrain, or if MapLibre has changed', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		expect(setDrapeQuality({ terrain: null, painter: {} } as unknown as MlMap)).toBe(false);
		const { map } = fakeMap();
		(map as unknown as { painter: object }).painter = { renderToTexture: { size: 2048 } };
		expect(setDrapeQuality(map)).toBe(false);
		warn.mockRestore();
	});
});
