// The map's weather layers: from the server's index to what the controls show.
import { describe, expect, it } from 'vitest';
import { toTimeline, type PrecipIndex } from '../radar';
import type { PointOut, RoseOut } from '../types.gen';
import { snowLineColors } from './layers/snowline';
import {
	asFrame,
	depthTick,
	layerLabel,
	layerName,
	layerSource,
	levelTick,
	weatherView,
	windTick
} from './weather';
import { pointSource, windSource } from './windsource';

const H = 3600;
const T = 1_800_000_000;

const index: PrecipIndex = {
	generated: '2026-11-12T00:00:00Z',
	bounds: [
		[31, -134],
		[57, -102]
	],
	width: 1700,
	height: 1970,
	frames: [
		{ t: T - 600, past: true, file: 'r1.png', south: '', kind: 'radar', span_h: 0 },
		{ t: T + H, past: false, file: 'f1.png', south: 'hrrr', kind: 'forecast', span_h: 1 }
	],
	totals: [
		{ hours: 24, window: 24, start: T, end: T + 24 * H, file: 't24.png' },
		{ hours: 72, window: 72, start: T, end: T + 72 * H, file: 't72.png' }
	],
	layers: {
		snowlevel: {
			frames: [
				{ t: T + 6 * H, file: 'sl2.png', kind: 'forecast', src: { north: 'hrdps', south: 'nbm' } },
				{ t: T + 3 * H, file: 'sl1.png', kind: 'forecast', src: { north: 'hrdps', south: 'nbm' } }
			]
		},
		gust: { frames: [{ t: T + 3 * H, file: 'g1.png', kind: 'forecast', src: {} }] },
		ridge: { frames: [{ t: T + 3 * H, file: 'w1.png', kind: 'forecast', src: { north: 'rdps' } }] },
		clouds: {
			frames: [
				{ t: T - 1800, file: 'c2.webp', kind: 'observed', src: { north: 'goes' } },
				{ t: T - 3600, file: 'c1.webp', kind: 'observed', src: { north: 'goes' } }
			]
		},
		depth: {
			frames: [
				{
					t: T - 6 * H,
					file: 'd1.png',
					kind: 'observed',
					src: { north: 'caldas', south: 'snodas' },
					runs: { snodas: T - 20 * H, caldas: T - 6 * H }
				}
			]
		},
		snowfall: {
			frames: [
				{ t: T - 2 * H, file: 'o72.png', kind: 'observed', hours: 72, src: { south: 'nohrsc' } },
				{ t: T - 2 * H, file: 'o24.png', kind: 'observed', hours: 24, src: { south: 'nohrsc' } }
			]
		},
		broken: { frames: [{ file: 'no-time.png' }] }
	}
};

describe('weather layers', () => {
	const tl = toTimeline(index);

	it('reads the other layers from the index, in order', () => {
		expect(tl.layers.snowlevel.map((f) => f.file)).toEqual(['sl1.png', 'sl2.png']);
		expect(tl.layers.snowfall.map((f) => f.hours)).toEqual([24, 72]);
		expect(tl.layers.broken).toEqual([]);
		expect(tl.layers.depth[0].runs.snodas).toBe(T - 20 * H);
		// An index from before the layers existed.
		expect(toTimeline({ ...index, layers: undefined }).layers).toEqual({});
	});

	it('shows the radar timeline as before', () => {
		const v = weatherView(tl, 'radar', 'gust');
		expect(v.mode).toBe('loop');
		expect(v.frames.map((f) => f.file)).toEqual(['r1.png', 'f1.png']);
		expect(v.now).toBe(0);
	});

	it('loops through snow level, wind and clouds', () => {
		const sl = weatherView(tl, 'snowlevel', 'gust');
		expect(sl.mode).toBe('loop');
		expect(sl.now).toBe(-1); // all forecast: no "now" on the slider
		expect(sl.frames[0]).toMatchObject({ kind: 'forecast', span_h: 0, past: false });
		expect(weatherView(tl, 'wind', 'gust').frames[0].file).toBe('g1.png');
		expect(weatherView(tl, 'wind', 'ridge').frames[0].file).toBe('w1.png');
		const cl = weatherView(tl, 'clouds', 'gust');
		expect(cl.frames.map((f) => f.file)).toEqual(['c1.webp', 'c2.webp']);
		expect(cl.now).toBe(1); // clouds end now
		expect(layerName('wind', 'ridge')).toBe('ridge');
		expect(layerName('radar', 'gust')).toBeNull();
	});

	it('picks totals, snow on the ground and observed snowfall by window', () => {
		const tot = weatherView(tl, 'totals', 'gust');
		expect(tot.mode).toBe('pick');
		expect(tot.picks.map((p) => [p.id, p.label, p.file])).toEqual([
			[24, '24 h', 't24.png'],
			[72, '3 days', 't72.png']
		]);
		const depth = weatherView(tl, 'depth', 'gust').picks;
		expect(depth).toHaveLength(1);
		expect(depth[0].span).toMatch(/^US .* · Canada /);
		expect(depth[0].sources).toContain('SNODAS');
		const fell = weatherView(tl, 'snowfall', 'gust').picks;
		expect(fell.map((p) => [p.id, p.name])).toEqual([
			[24, 'Last 24 hours'],
			[72, 'Last 72 hours']
		]);
		expect(fell[0].span).toContain('→');
	});

	it('shows nothing when off or before the index loads', () => {
		expect(weatherView(tl, 'off', 'gust').mode).toBe('none');
		expect(weatherView(null, 'snowlevel', 'gust').frames).toEqual([]);
	});

	it('labels forecast and satellite frames', () => {
		const now = T * 1000;
		const f = asFrame(tl.layers.snowlevel[0]);
		expect(layerLabel(f, now).rel).toBe('forecast · in 3 h');
		expect(layerLabel(asFrame(tl.layers.snowlevel[1]), now - 3 * 24 * H * 1000).rel).toBe(
			'forecast · in 3 days'
		);
		const c = asFrame(tl.layers.clouds[0]);
		expect(layerLabel(c, now).rel).toBe('satellite · 1 h ago');
		expect(layerLabel(asFrame(tl.layers.clouds[1]), now).rel).toBe('satellite · 30 min ago');
	});

	it('says where each layer comes from', () => {
		const f = asFrame(tl.layers.snowlevel[0]);
		expect(layerSource('snowlevel', 'gust', f)).toContain(
			"Canadian HRDPS in Canada, NOAA's National Blend of Models in the US"
		);
		expect(layerSource('wind', 'ridge', asFrame(tl.layers.ridge[0]))).toContain('700 hPa');
		expect(layerSource('clouds', 'gust', undefined)).toContain('GOES-West');
	});

	it('writes key ticks in either units', () => {
		expect(levelTick(0, 'metric')).toBe('0');
		expect(levelTick(250, 'metric')).toBe('');
		expect(levelTick(2000, 'metric')).toBe('2k');
		expect(levelTick(1000, 'imperial')).toBe('3.3k');
		expect(levelTick(3000, 'imperial')).toBe('9.8k');
		expect(windTick(100, 'imperial')).toBe('62');
		expect(windTick(100, 'metric')).toBe('100');
		expect(depthTick(30.48, 'imperial')).toBe('12');
	});
});

describe('the rain/snow line on the terrain', () => {
	it('is clear below the mix band, pink across it, white above', () => {
		const e = snowLineColors(1500) as unknown as (string | number)[];
		expect(e.slice(3)).toEqual([
			1349.5,
			'rgba(0, 0, 0, 0)',
			1350,
			'rgba(244, 166, 198, 0.75)',
			1649.5,
			'rgba(244, 166, 198, 0.75)',
			1650,
			'rgba(240, 247, 255, 0.9)'
		]);
		// Snow to the valleys: the band starts at the ground, stops still rising.
		const low = snowLineColors(0) as unknown as number[];
		expect(low[3]).toBe(0.5);
		expect(low[9]).toBeGreaterThan(low[7]);
	});
});

describe('wind away from saved locations', () => {
	const rose = (window: string, snow_cm: number): RoseOut => ({
		window,
		sectors: [0, 0, 0, 0, 0, 0, 1, 0],
		snow_cm,
		mean_kmh: 50,
		wind_from: 'W',
		loading: ['E'],
		label: 'W wind, loading E aspects'
	});
	const point: PointOut = {
		lat: 52,
		lon: -125,
		inside: true,
		generated: '2026-11-12T00:00:00Z',
		totals: [],
		rates: [],
		snow_level: [],
		gust: [],
		ridge: [],
		depth: null,
		observed: [],
		roses: [rose('next24', 12), rose('next72', 30)],
		min_snow_cm: 2,
		min_wind_kmh: 15
	};

	it("uses the map's forecast when no location is in range", () => {
		const w = windSource(null, 52, -125, 'next24', point);
		expect(w?.model).toBe(true);
		expect(w?.rose?.snow_cm).toBe(12);
		expect(w!.scale).toBeGreaterThan(0);
		// No rose for the past 48 hours from the forecast.
		const past = windSource(null, 52, -125, 'past48', point);
		expect(past?.rose).toBeNull();
		expect(past?.scale).toBe(0);
	});

	it('only near the spot it was asked for, and inside the box', () => {
		expect(pointSource(point, 52.5, -125, 'next24')).toBeNull(); // ~55 km away
		expect(pointSource({ ...point, inside: false }, 52, -125, 'next24')).toBeNull();
		expect(windSource(null, 52, -125, 'next24')).toBeNull();
	});
});
