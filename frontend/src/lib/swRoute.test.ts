import { describe, expect, it } from 'vitest';
import { precipFiles, route } from './swRoute';

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

describe('precipFiles', () => {
	it('lists frames, totals and layer pictures', () => {
		const files = precipFiles({
			frames: [{ file: 'r1-a.png', data: 'r1-d.bin' }, { file: 2 }],
			totals: [{ file: 't24-b.png' }],
			layers: { wind: { frames: [{ file: 'w1-c.png' }] }, empty: {} }
		});
		expect([...files].sort()).toEqual(['r1-a.png', 'r1-d.bin', 't24-b.png', 'w1-c.png']);
		expect(precipFiles(null).size).toBe(0);
	});
});
