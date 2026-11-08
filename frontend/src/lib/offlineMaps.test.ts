import { describe, expect, it } from 'vitest';
import { areaUrls, estimateBytes, latToY, lonToX, sharedUrls, tileRange } from './offlineMaps';

describe('offline map areas', () => {
	it('finds the same tile as the map for Alpental', () => {
		expect(lonToX(-121.427, 14)).toBe(2665);
		expect(latToY(47.445, 14)).toBe(5732);
	});

	it('covers about 16 km across at every zoom', () => {
		const r = tileRange(47.445, -121.427, 8, 15);
		// A zoom-15 tile is ~0.8 km across here: ~20 tiles each way.
		expect(r.x1 - r.x0 + 1).toBeGreaterThanOrEqual(18);
		expect(r.x1 - r.x0 + 1).toBeLessThanOrEqual(22);
		expect(r.y1 - r.y0 + 1).toBeGreaterThanOrEqual(18);
		expect(r.y1 - r.y0 + 1).toBeLessThanOrEqual(22);
	});

	it('asks for the topo map to zoom 15 and terrain through the mini PC and AWS', () => {
		const { topo, dem } = areaUrls(47.445, -121.427, 'https://snow.example');
		expect(topo.every((u) => u.startsWith('https://snow.example/api/tiles/otm/'))).toBe(true);
		expect(topo.some((u) => u.includes('/otm/15/'))).toBe(true);
		expect(topo.some((u) => u.includes('/otm/16/'))).toBe(false);
		expect(dem.every((u) => u.startsWith('https://s3.amazonaws.com/elevation-tiles-prod/'))).toBe(
			true
		);
		expect(dem.some((u) => u.includes('/terrarium/15/'))).toBe(true);
		// Never Esri: its terms don't allow storing tiles for offline use.
		expect([...topo, ...dem].some((u) => /esri|sat/.test(u))).toBe(false);
		expect(new Set(topo).size).toBe(topo.length);
		// Light on OpenTopoMap's volunteer servers: a few hundred tiles an area.
		expect(topo.length).toBeLessThan(700);
	});

	it('keeps an area to tens of megabytes', () => {
		const mb = estimateBytes(47.445, -121.427) / 1e6;
		expect(mb).toBeGreaterThan(10);
		expect(mb).toBeLessThan(60);
	});

	it('saves the ski runs and the label fonts the map uses', () => {
		const u = sharedUrls('');
		expect(u).toContain('/api/osm/ski.geojson');
		expect(u).toContain('/api/glyphs/Open%20Sans%20Semibold/0-255.pbf');
		expect(u).toContain('/api/glyphs/Noto%20Sans%20Regular/8192-8447.pbf');
	});
});
