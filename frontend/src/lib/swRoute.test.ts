import { describe, expect, it } from 'vitest';
import { precipFiles, route, spotsToDrop } from './swRoute';

const O = 'https://snow.example';
const at = (path: string, opts: Partial<Parameters<typeof route>[2]> = {}) =>
	route(new URL(path, O), O, { navigate: false, shell: false, saved: true, ...opts });

describe('route', () => {
	it('sends map tiles and elevation past the service worker when no area is saved', () => {
		for (const u of [
			'/api/tiles/otm/10/1/2.png',
			'/api/glyphs/Open%20Sans/0-255.pbf',
			'https://tiles.mapterhorn.com/12/1/2.webp',
			'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/9/1/2.png'
		]) {
			expect(at(u, { saved: false })).toBe('network');
			expect(at(u, { saved: true })).toBe('saved');
			// Not known yet: the safe way, through the saved maps.
			expect(at(u, { saved: null })).toBe('saved');
		}
	});
	it('keeps API answers for offline use, but not private ones or taps', () => {
		expect(at('/api/precip')).toBe('api');
		expect(at('/api/precip/r1-0123456789ab.png')).toBe('api');
		expect(at('/api/sat/tiles/v/rgb/10/1/2.webp')).toBe('api');
		expect(at('/api/me')).toBe('network');
		expect(at('/api/admin/locations')).toBe('network');
		expect(at('/api/map/point?lat=1&lon=2')).toBe('network');
		expect(at('/api/osm/ski.geojson')).toBe('network-then-saved');
	});
	it('pages and app files', () => {
		expect(at('/map', { navigate: true })).toBe('page');
		expect(at('/_app/immutable/x.js', { shell: true })).toBe('shell');
		expect(at('/other.js')).toBe('network');
		expect(at('https://elsewhere.example/a.png')).toBe('network');
	});
});

describe('spots', () => {
	it('are network-first and only the newest ten of each are kept', () => {
		expect(at('/api/spot?lat=47.000&lon=-121.000')).toBe('spot');
		expect(at('/api/spot/nearby?lat=47.000&lon=-121.000')).toBe('spot');
		const entries = [
			...Array.from({ length: 12 }, (_, i) => ({ url: `${O}/api/spot?lat=${i}&lon=0`, at: i })),
			{ url: `${O}/api/spot/nearby?lat=0&lon=0`, at: 0 },
			{ url: `${O}/api/precip`, at: 0 }
		];
		expect(spotsToDrop(entries).sort()).toEqual([
			`${O}/api/spot?lat=0&lon=0`,
			`${O}/api/spot?lat=1&lon=0`
		]);
	});
});

describe('precipFiles', () => {
	it("lists frames, totals, layer pictures and the snow total's steps", () => {
		const files = precipFiles({
			frames: [{ file: 'r1-a.png', data: 'r1-d.bin' }, { file: 2 }],
			totals: [{ file: 't24-b.png' }],
			layers: { wind: { frames: [{ file: 'w1-c.png' }] }, empty: {} },
			steps: { steps: [{ data: 's6-e.bin' }] }
		});
		expect([...files].sort()).toEqual([
			'r1-a.png',
			'r1-d.bin',
			's6-e.bin',
			't24-b.png',
			'w1-c.png'
		]);
		expect(precipFiles(null).size).toBe(0);
	});
});
