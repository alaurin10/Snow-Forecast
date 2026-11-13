import { describe, expect, it } from 'vitest';
import { GLACIER_SAMPLES, glacierGrid, glacierStats } from './glacier';
import { inPolygon } from './here';
import type { LngLat } from './measure';

// A 0.02° × 0.01° glacier at 48.5° N (about 1.5 km by 1.1 km), with a hole in it.
const outer: LngLat[] = [
	[-120.745, 48.5],
	[-120.725, 48.5],
	[-120.725, 48.51],
	[-120.745, 48.51],
	[-120.745, 48.5]
];
const hole: LngLat[] = [
	[-120.737, 48.504],
	[-120.733, 48.504],
	[-120.733, 48.506],
	[-120.737, 48.506],
	[-120.737, 48.504]
];
const ice: GeoJSON.Polygon = { type: 'Polygon', coordinates: [outer, hole] };

describe('glacierGrid', () => {
	it('puts points on the ice (not in its holes) and along its outline', () => {
		const g = glacierGrid(ice)!;
		expect(g.inside).toBeGreaterThan(GLACIER_SAMPLES * 0.8);
		expect(g.inside).toBeLessThanOrEqual(GLACIER_SAMPLES);
		for (const p of g.points.slice(0, g.inside)) expect(inPolygon([outer, hole], ...p)).toBe(true);
		expect(g.points.length - g.inside).toBeGreaterThanOrEqual(4);
		// Square cells, near enough.
		expect(g.dx / g.dy).toBeGreaterThan(0.8);
		expect(g.dx / g.dy).toBeLessThan(1.25);
		expect(g.cells.flat().filter((k) => k >= 0)).toHaveLength(g.inside);
	});

	it('has nothing to sample for a point or a line', () => {
		expect(glacierGrid({ type: 'Point', coordinates: [0, 0] })).toBeNull();
	});
});

describe('glacierStats', () => {
	const g = glacierGrid(ice)!;
	// Highest at the north edge, 600 m lower at the south: it flows south.
	const elev = g.points.map(([, lat]) => 1900 + ((lat - 48.5) / 0.01) * 600);
	const slope = g.points.map((_, i) => (i % 4 === 0 ? 35 : 20));

	it('finds the top, the toe, the way it flows and how steep it is', () => {
		const s = glacierStats(g, elev, slope)!;
		expect(s.top).toBeGreaterThan(2450);
		expect(s.toe).toBeLessThan(1950);
		expect(s.topAt[1]).toBeGreaterThan(s.toeAt[1]);
		expect(s.flows).not.toBeNull();
		expect(Math.abs(s.flows! - 180)).toBeLessThan(5);
		expect(s.slope).toBeCloseTo(23.75, 0);
		expect(s.steep).toBeCloseTo(0.25, 1);
		expect(s.length).toBeGreaterThan(900);
	});

	it('says no direction for ice that falls every way', () => {
		// A dome: highest in the middle.
		const dome = g.points.map(
			([lon, lat]) => 2500 - 4e6 * ((lon + 120.735) ** 2 + (lat - 48.505) ** 2)
		);
		expect(glacierStats(g, dome, slope)!.flows).toBeNull();
	});

	it('skips points the terrain had no answer for', () => {
		const some = elev.map((v, i) => (i % 2 ? NaN : v));
		expect(glacierStats(g, some, slope)!.top).toBeGreaterThan(2400);
		expect(
			glacierStats(
				g,
				elev.map(() => NaN),
				slope
			)
		).toBeNull();
	});
});
