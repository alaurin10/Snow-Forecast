import { describe, expect, it } from 'vitest';
import { frameLabel, radarFrames } from './radar';

describe('radarFrames', () => {
	it('builds tile templates in time order', () => {
		const frames = radarFrames({
			host: 'https://tilecache.rainviewer.com',
			radar: {
				past: [
					{ time: 200, path: '/v2/radar/b' },
					{ time: 100, path: '/v2/radar/a' }
				],
				nowcast: []
			}
		});
		expect(frames.map((f) => f.time)).toEqual([100, 200]);
		expect(frames[0].url).toBe(
			'https://tilecache.rainviewer.com/v2/radar/a/256/{z}/{x}/{y}/2/1_1.png'
		);
	});
	it('copes with a broken index', () => {
		expect(radarFrames(null)).toEqual([]);
		expect(radarFrames({ host: 'x' })).toEqual([]);
	});
});

describe('frameLabel', () => {
	it('says how old a frame is', () => {
		const t = 1_800_000_000;
		expect(frameLabel(t, t * 1000)).toMatch(/latest$/);
		expect(frameLabel(t, (t + 1200) * 1000)).toMatch(/20 min ago$/);
	});
});
