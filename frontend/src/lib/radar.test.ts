import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	frameLabel,
	loadTimeline,
	RAMPS,
	rampTop,
	toTimeline,
	untypedColor,
	untypedTop,
	type Frame,
	type PrecipIndex
} from './radar';

const f = (t: number, past: boolean, south: Frame['south'] = ''): Frame => ({
	t,
	past,
	file: `${past ? 'r' : 'f'}${t}-000000000000.png`,
	south
});

describe('toTimeline', () => {
	const ix: PrecipIndex = {
		generated: '2026-11-07T00:00:00Z',
		bounds: [
			[43, -131],
			[55, -110]
		],
		width: 1400,
		height: 1232,
		frames: [f(3600, false), f(600, true), f(1200, true)]
	};
	it('puts frames in time order and marks the last radar frame as now', () => {
		const tl = toTimeline(ix);
		expect(tl.frames.map((x) => x.t)).toEqual([600, 1200, 3600]);
		expect(tl.now).toBe(1);
		expect(tl.width).toBe(1400);
	});
	it('has no "now" without radar', () => {
		expect(toTimeline({ ...ix, frames: [f(3600, false)] }).now).toBe(-1);
	});
});

describe('frameLabel', () => {
	it('says how old a radar frame is', () => {
		const t = 1_800_000_000;
		expect(frameLabel(f(t, true), t * 1000).rel).toBe('radar · now');
		expect(frameLabel(f(t, true), (t + 1200) * 1000).rel).toBe('radar · 20 min ago');
		expect(frameLabel(f(t, true), (t + 6000) * 1000).rel).toBe('radar · 1 h 40 min ago');
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
});

describe('legend', () => {
	it('labels the top of each ramp in the chosen units', () => {
		expect(rampTop(RAMPS.snow, 'metric')).toBe('3+ cm/h');
		expect(rampTop(RAMPS.snow, 'imperial')).toBe('1.2+ in/h');
		expect(rampTop(RAMPS.rain, 'metric')).toBe('10+ mm/h');
		expect(rampTop(RAMPS.rain, 'imperial')).toBe('0.4+ in/h');
		expect(untypedTop('imperial')).toBe('1+ in / 6 h');
		expect(untypedTop('metric')).toBe('25.4+ mm / 6 h');
	});
	it('shades 6-hour totals by amount', () => {
		expect(untypedColor(0.05)).toBeNull();
		expect(untypedColor(0.1)).toBe('#e6d3b3');
		expect(untypedColor(3)).toBe('#8f612c');
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
