// @vitest-environment jsdom
// (GPX files are read with the browser's DOMParser.)
import { describe, expect, it } from 'vitest';
import {
	densify,
	distanceText,
	haversine,
	heightText,
	joinLines,
	lineBounds,
	lineLength,
	lineStats,
	parseGpx,
	profileZoom,
	sampleLine,
	segments,
	segmentsGeojson,
	slopeColor,
	FLAT_COLOR,
	MAX_SAMPLES,
	type LngLat,
	type Sample
} from './measure';
import { SLOPE_CLASSES } from './terrain/analysis';

/** A straight line of samples every `step` m, with elevation from `f(d)`. */
function samples(n: number, step: number, f: (d: number) => number, slope = 10): Sample[] {
	return Array.from({ length: n }, (_, i) => ({
		lon: -122 + i * 0.0001,
		lat: 50,
		d: i * step,
		elev: f(i * step),
		slope
	}));
}

describe('distances', () => {
	it('measures along the ground', () => {
		// One degree of latitude is about 111.2 km.
		expect(haversine([0, 0], [0, 1])).toBeCloseTo(111195, -1);
		expect(
			lineLength([
				[0, 0],
				[0, 0.5],
				[0, 1]
			])
		).toBeCloseTo(111195, -1);
		expect(lineLength([[0, 0]])).toBe(0);
	});

	it('samples a short line every 10 m, keeping corners', () => {
		const pts: LngLat[] = [
			[-122, 50],
			[-122, 50.001],
			[-121.999, 50.001]
		];
		const { points, d } = densify(pts);
		expect(points[0]).toEqual(pts[0]);
		expect(points.at(-1)).toEqual(pts[2]);
		expect(points).toContainEqual(pts[1]);
		expect(d.at(-1)).toBeCloseTo(lineLength(pts), 3);
		for (let i = 1; i < d.length; i++) expect(d[i] - d[i - 1]).toBeLessThanOrEqual(10.0001);
		expect(points.length).toBe(d.length);
	});

	it('samples a long track evenly, at most MAX_SAMPLES points', () => {
		const pts: LngLat[] = Array.from({ length: 3000 }, (_, i) => [-122 + i * 0.0002, 50]);
		const { points, d } = densify(pts);
		expect(points.length).toBeLessThanOrEqual(MAX_SAMPLES + 1);
		expect(points.length).toBeGreaterThan(MAX_SAMPLES - 5);
		expect(d.at(-1)).toBeCloseTo(lineLength(pts), 0);
		expect(densify([])).toEqual({ points: [], d: [] });
	});

	it('picks finer elevation tiles for closer samples', () => {
		expect(profileZoom(5, 50)).toBe(14);
		expect(profileZoom(10, 50)).toBe(13);
		expect(profileZoom(20, 50)).toBe(12);
		expect(profileZoom(5000, 50)).toBe(10);
	});
});

describe('lineStats', () => {
	it('climbs a steady slope', () => {
		// 500 m rising 100 m: 11.3°.
		const st = lineStats(samples(51, 10, (d) => 1000 + d / 5))!;
		expect(st.distance).toBe(500);
		expect(st.climb).toBeCloseTo(100, 0);
		expect(st.descent).toBe(0);
		expect(st.minElev).toBe(1000);
		expect(st.maxElev).toBe(1100);
		expect(st.avgGrade).toBeCloseTo(11.31, 1);
		expect(st.steepGrade).toBeCloseTo(11.31, 1);
	});

	it('ignores noise smaller than the data can tell', () => {
		const st = lineStats(samples(100, 10, (d) => 1000 + (Math.round(d / 10) % 2) * 1.5))!;
		expect(st.climb).toBe(0);
		expect(st.descent).toBe(0);
	});

	it('finds the steepest 50 m stretch and the steepest ground', () => {
		// Flat, then a 60 m pitch dropping 60 m (45°), then flat.
		const f = (d: number) => (d < 200 ? 2000 : d < 260 ? 2000 - (d - 200) : 1940);
		const s = samples(60, 10, f);
		s[25].slope = 41;
		const st = lineStats(s)!;
		expect(st.descent).toBeCloseTo(60, 0);
		expect(st.steepGrade).toBeCloseTo(45, 0);
		expect(st.steepGround).toBe(41);
		expect(st.steepAt).toBe(25);
	});

	it('uses the whole length of a line shorter than 50 m', () => {
		const st = lineStats(samples(3, 10, (d) => d))!;
		expect(st.steepGrade).toBeCloseTo(45, 5);
		expect(lineStats(samples(1, 10, () => 0))).toBeNull();
	});
});

describe('segments', () => {
	it('colours stretches by the steeper end', () => {
		const s = samples(6, 10, () => 0);
		[10, 10, 32, 32, 12, 12].forEach((v, i) => (s[i].slope = v));
		const segs = segments(s);
		expect(segs).toEqual([
			{ from: 0, to: 1, color: FLAT_COLOR },
			{ from: 1, to: 4, color: SLOPE_CLASSES[1].color },
			{ from: 4, to: 5, color: FLAT_COLOR }
		]);
		const fc = segmentsGeojson(s);
		expect(fc.features).toHaveLength(3);
		expect((fc.features[1].geometry as GeoJSON.LineString).coordinates).toHaveLength(4);
		expect(slopeColor(52)).toBe(SLOPE_CLASSES[5].color);
	});
});

describe('words', () => {
	it('says distances and heights in the viewer’s units', () => {
		expect(distanceText(432, 'metric')).toBe('430 m');
		expect(distanceText(4321, 'metric')).toBe('4.32 km');
		expect(distanceText(43210, 'metric')).toBe('43.2 km');
		expect(distanceText(100, 'imperial')).toBe('330 ft');
		expect(distanceText(4321, 'imperial')).toBe('2.68 mi');
		expect(heightText(1234.4, 'metric')).toBe('1,234 m');
		expect(heightText(1000, 'imperial')).toBe('3,280 ft');
	});
});

describe('joinLines', () => {
	it('joins pieces end to end, turning them as needed', () => {
		const a: LngLat[] = [
			[0, 0],
			[0, 1]
		];
		const b: LngLat[] = [
			[0, 2],
			[0, 1]
		];
		const c: LngLat[] = [
			[0, -1],
			[0, 0]
		];
		expect(joinLines([a, b, c])).toEqual([
			[0, -1],
			[0, 0],
			[0, 1],
			[0, 2]
		]);
		// A gap: the nearest piece follows.
		expect(
			joinLines([
				[
					[0, 0],
					[0, 1]
				],
				[
					[0, 1.1],
					[0, 2]
				]
			])
		).toHaveLength(4);
		expect(joinLines([])).toEqual([]);
	});
});

describe('parseGpx', () => {
	const gpx = (body: string) =>
		`<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">${body}</gpx>`;

	it('reads every track segment, with the track’s name', () => {
		const t = parseGpx(
			gpx(
				`<metadata><name>File</name></metadata><trk><name>Wedge couloir</name>` +
					`<trkseg><trkpt lat="50.1" lon="-122.8"><ele>1000</ele></trkpt><trkpt lat="50.2" lon="-122.7"/></trkseg>` +
					`<trkseg><trkpt lat="50.3" lon="-122.6"/><trkpt lat="bad" lon="-1"/></trkseg></trk>`
			)
		);
		expect(t.name).toBe('Wedge couloir');
		expect(t.points).toEqual([
			[-122.8, 50.1],
			[-122.7, 50.2],
			[-122.6, 50.3]
		]);
		expect(lineBounds(t.points)).toEqual([-122.8, 50.1, -122.6, 50.3]);
	});

	it('falls back to a route, then gives up', () => {
		const r = parseGpx(
			gpx(`<rte><rtept lat="50" lon="-122"/><rtept lat="50.1" lon="-122.1"/></rte>`)
		);
		expect(r.points).toHaveLength(2);
		expect(r.name).toBe('');
		expect(() => parseGpx(gpx(`<wpt lat="50" lon="-122"/>`))).toThrow(/No track/);
		expect(() => parseGpx('not xml <')).toThrow(/isn’t a GPX/);
	});

	it('thins a very long track', () => {
		const pts = Array.from(
			{ length: 12001 },
			(_, i) => `<trkpt lat="50" lon="${-122 + i * 1e-5}"/>`
		);
		const t = parseGpx(gpx(`<trk><trkseg>${pts.join('')}</trkseg></trk>`));
		expect(t.points.length).toBeLessThanOrEqual(5001);
		expect(t.points.at(-1)![0]).toBeCloseTo(-122 + 12000e-5, 8);
	});
});

describe('sampleLine', () => {
	it('asks the worker for the terrain under every sample', async () => {
		const pts: LngLat[] = [
			[-122, 50],
			[-122, 50.002]
		];
		let asked = 0;
		const s = await sampleLine(pts, async (points, z) => {
			asked = z;
			return { elev: points.map((_, i) => 1000 + i), slope: points.map(() => 30) };
		});
		expect(asked).toBe(13);
		expect(s.length).toBeGreaterThan(20);
		expect(s[1].elev).toBe(1001);
		expect(s.at(-1)!.d).toBeCloseTo(lineLength(pts), 3);
		expect(await sampleLine([[-122, 50]], async () => ({ elev: [], slope: [] }))).toEqual([]);
	});
});
