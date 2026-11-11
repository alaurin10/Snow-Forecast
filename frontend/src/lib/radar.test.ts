import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	frameLabel,
	frameSource,
	loadTimeline,
	RAMPS,
	rampTop,
	toTimeline,
	totalLabel,
	totalName,
	totalSources,
	type Frame,
	type PrecipIndex
} from './radar';

const f = (t: number, past: boolean, south: Frame['south'] = ''): Frame => ({
	t,
	past,
	file: `${past ? 'r' : 'f'}${t}-000000000000.png`,
	south,
	kind: past ? 'radar' : 'forecast',
	span_h: past ? 0 : 1,
	src: past ? { north: 'radar-eccc', south: 'radar-eccc' } : { north: 'hrdps', south: south }
});
/** A 3- or 6-hour frame beyond two days. */
const ext = (t: number, span: number, north = 'gdps', south = 'nbm'): Frame => ({
	...f(t, false, south),
	span_h: span,
	src: { north, south }
});
const nc = (t: number): Frame => ({
	t,
	past: false,
	file: `n${t}-000000000000.png`,
	south: '',
	kind: 'nowcast',
	span_h: 0,
	src: { north: 'nowcast-eccc', south: 'nowcast-eccc' }
});

describe('toTimeline', () => {
	const ix: PrecipIndex = {
		version: 2,
		generated: '2026-11-07T00:00:00Z',
		bounds: [
			[31, -134],
			[57, -102]
		],
		width: 1700,
		height: 1970,
		frames: [f(3600, false), nc(1920), f(600, true), nc(2640), f(1200, true)],
		attribution: ['Radar: Environment and Climate Change Canada (North American composite)']
	};
	it('orders radar, then nowcast, then forecast, with "now" at the last radar frame', () => {
		const tl = toTimeline(ix);
		expect(tl.frames.map((x) => x.kind)).toEqual([
			'radar',
			'radar',
			'nowcast',
			'nowcast',
			'forecast'
		]);
		expect(tl.now).toBe(1);
		expect(tl.nowcastEnd).toBe(3);
		expect(tl.width).toBe(1700);
		expect(tl.attribution).toHaveLength(1);
		expect(tl.extendedFrom).toBe(-1);
	});
	it('finds where the 3- and 6-hour frames start', () => {
		const tl = toTimeline({ ...ix, frames: [...ix.frames, ext(99 * 3600, 6), ext(80 * 3600, 3)] });
		expect(tl.frames.map((x) => x.span_h).slice(-3)).toEqual([1, 3, 6]);
		expect(tl.extendedFrom).toBe(5);
	});
	it('reads totals with and without a window', () => {
		const tl = toTimeline({
			...ix,
			totals: [
				{ hours: 236, window: 240, start: 0, end: 1, file: 't236.png' },
				{ hours: 12, start: 0, end: 1, file: 't12.png' }
			]
		});
		expect(tl.totals.map((t) => t.window)).toEqual([12, 240]);
	});
	it('has no "now" without radar', () => {
		const tl = toTimeline({ ...ix, frames: [f(3600, false)] });
		expect(tl.now).toBe(-1);
		expect(tl.nowcastEnd).toBe(-1);
	});
	it('reads an index written before version 2', () => {
		const tl = toTimeline({
			generated: '',
			bounds: ix.bounds,
			width: 1400,
			height: 1200,
			frames: [
				{ t: 3600, past: false, file: 'f3600-000000000000.png', south: 'hrrr' },
				{ t: 600, past: true, file: 'r600-000000000000.png', south: '' }
			]
		});
		expect(tl.frames.map((x) => [x.kind, x.span_h])).toEqual([
			['radar', 0],
			['forecast', 1]
		]);
		expect(tl.frames[0].src).toEqual({});
		expect(tl.now).toBe(0);
		expect(tl.attribution).toEqual([]);
	});
});

describe('frameLabel', () => {
	it('says how old a radar frame is', () => {
		const t = 1_800_000_000;
		expect(frameLabel(f(t, true), t * 1000).rel).toBe('radar · now');
		expect(frameLabel(f(t, true), (t + 1200) * 1000).rel).toBe('radar · 20 min ago');
		expect(frameLabel(f(t, true), (t + 6000) * 1000).rel).toBe('radar · 1 h 40 min ago');
	});
	it('says how far ahead a nowcast is', () => {
		const t = 1_800_000_000;
		expect(frameLabel(nc(t), (t - 24 * 60) * 1000).rel).toBe('nowcast · in 24 min');
		expect(frameLabel(nc(t), t * 1000).rel).toBe('nowcast · now');
		expect(frameLabel(nc(t), 0).when).toMatch(/\d:\d\d [AP]M/);
	});
	it('names a forecast hour and how far ahead it is', () => {
		const end = new Date(2026, 10, 7, 6).getTime() / 1000; // Sat 6 AM local
		const lab = frameLabel(f(end, false), (end - 5 * 3600) * 1000);
		expect(lab.when).toBe('Sat 5–6 AM');
		expect(lab.rel).toBe('forecast · in 4 h');
		expect(frameLabel(f(end, false), (end - 1800) * 1000).rel).toBe('forecast · this hour');
		const noon = new Date(2026, 10, 7, 12).getTime() / 1000;
		expect(frameLabel(f(noon, false), 0).when).toBe('Sat 11 AM–12 PM');
	});
	it('labels a 6-hour frame as an average, days ahead', () => {
		const end = new Date(2026, 10, 13, 10).getTime() / 1000; // Fri 10 AM local
		const lab = frameLabel(ext(end, 6), (end - 6 * 3600 - 72 * 3600) * 1000);
		expect(lab.when).toBe('Fri 4–10 AM');
		expect(lab.rel).toBe('6-hour avg · in 3 days');
	});
});

describe('frameSource', () => {
	it('names where each frame came from', () => {
		expect(frameSource(f(1, true))).toMatch(/Environment Canada/);
		expect(frameSource({ ...f(1, true), src: { north: 'rainviewer' } })).toMatch(/RainViewer/);
		expect(frameSource(nc(1))).toMatch(/^Nowcast/);
		expect(frameSource(f(1, false, 'hrrr'))).toMatch(
			/HRDPS model where it reaches .*, NOAA HRRR beyond, blended where they meet/
		);
		expect(frameSource(f(1, false, 'nbm'))).toMatch(/National Blend/);
		expect(frameSource(f(1, false, ''))).toBe('Forecast: Canadian HRDPS model where it reaches.');
		expect(
			frameSource({ ...f(1, false, 'hrrr'), src: { north: 'hrdps', south: 'hrrr', fill: 'rdps' } })
		).toMatch(/NOAA HRRR and Canadian RDPS beyond/);
		expect(frameSource(ext(1, 6))).toMatch(
			/6-hour average: Canadian GDPS model in Canada, .* in the US, blended across the border/
		);
		expect(frameSource(ext(1, 3, 'rdps', 'rdps'))).toBe(
			'Forecast, 3-hour average: Canadian RDPS model.'
		);
	});
});

describe('legend', () => {
	it('labels the top of each ramp in the chosen units', () => {
		expect(rampTop(RAMPS.snow, 'metric')).toBe('3+ cm/h');
		expect(rampTop(RAMPS.snow, 'imperial')).toBe('1.2+ in/h');
		expect(rampTop(RAMPS.rain, 'metric')).toBe('10+ mm/h');
		expect(rampTop(RAMPS.rain, 'imperial')).toBe('0.4+ in/h');
	});
});

describe('snow totals', () => {
	it('names each window', () => {
		expect(totalLabel({ window: 12 })).toBe('12 h');
		expect(totalLabel({ window: 48 })).toBe('48 h');
		expect(totalLabel({ window: 72 })).toBe('3 days');
		expect(totalLabel({ window: 240 })).toBe('10 days');
		expect(totalName({ window: 24 })).toBe('Next 24 hours');
		expect(totalName({ window: 168 })).toBe('Next 7 days');
	});
	it('names the models and their runs', () => {
		const run = new Date(2026, 10, 10, 4).getTime() / 1000; // Tue 4 AM local
		const t = { hours: 24, window: 24, start: 0, end: 1, file: 'x' };
		expect(totalSources({ ...t, runs: { hrdps: run, rdps: run, nbm: run } })).toBe(
			'Canada: HRDPS (Tue 4 AM), RDPS (Tue 4 AM). US: NOAA National Blend (Tue 4 AM).'
		);
		expect(totalSources({ ...t, source: 'hrdps' })).toBe('Canada: HRDPS.');
	});
});

describe('loadTimeline errors', () => {
	afterEach(() => vi.unstubAllGlobals());
	const answer = (status: number, body: unknown) =>
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response(JSON.stringify(body), { status }))
		);

	it('says the frames are still being drawn', async () => {
		answer(503, { detail: 'precipitation frames not ready yet' });
		await expect(loadTimeline()).rejects.toMatchObject({ kind: 'building' });
	});
	it('tells being offline apart', async () => {
		answer(503, { detail: 'offline' });
		await expect(loadTimeline()).rejects.toMatchObject({ kind: 'offline' });
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => Promise.reject(new TypeError('network')))
		);
		await expect(loadTimeline()).rejects.toMatchObject({ kind: 'offline' });
	});
	it('names a server error', async () => {
		answer(500, {});
		await expect(loadTimeline()).rejects.toMatchObject({ kind: 'server' });
	});
	it('treats an empty list as not drawn yet', async () => {
		answer(200, {
			bounds: [
				[0, 0],
				[1, 1]
			],
			width: 1,
			height: 1,
			frames: []
		});
		await expect(loadTimeline()).rejects.toMatchObject({ kind: 'building' });
	});
});
