import { describe, expect, it } from 'vitest';
import {
	buildTimeline,
	capabilityTimes,
	frameLabel,
	futureTimes,
	hrrrRecolor,
	parseTimeDimension,
	radarFrames,
	radarRecolor,
	rainRate,
	snowRate,
	RAMPS,
	rampTop,
	sldBody,
	untypedColor,
	untypedTop,
	wpcLayerFor,
	wpcTime
} from './radar';

const iso = (t: number) => new Date(t * 1000).toISOString();
const at = (s: string) => Date.parse(s) / 1000;

describe('parseTimeDimension', () => {
	it('expands a start/end/period range', () => {
		const ts = parseTimeDimension('2026-11-06T19:00:00Z/2026-11-06T22:00:00Z/PT1H');
		expect(ts).toHaveLength(4);
		expect(ts[1] - ts[0]).toBe(3600);
		expect(iso(ts[0])).toBe('2026-11-06T19:00:00.000Z');
	});
	it('reads minute periods, comma lists, and skips junk', () => {
		expect(parseTimeDimension('2026-11-06T21:42:00Z/2026-11-06T22:00:00Z/PT6M')).toHaveLength(4);
		const ts = parseTimeDimension('2026-11-06T19:00:00Z, nonsense, 2026-11-06T18:00:00Z');
		expect(ts).toHaveLength(2);
		expect(ts[0]).toBeLessThan(ts[1]);
	});
	it('finds the time dimension in a capabilities document', () => {
		const caps = `<Layer><Dimension name="time" units="ISO8601" default="x">2026-11-06T19:00:00Z/2026-11-06T20:00:00Z/PT1H</Dimension></Layer>`;
		expect(capabilityTimes(caps)).toHaveLength(2);
		expect(capabilityTimes('<Layer/>')).toEqual([]);
	});
});

describe('timeline', () => {
	const now = Date.parse('2026-11-07T01:20:00Z');
	it('starts the forecast at the hour under way', () => {
		const model = parseTimeDimension('2026-11-06T19:00:00Z/2026-11-08T18:00:00Z/PT1H');
		const ts = futureTimes(model, now);
		expect(iso(ts[0])).toBe('2026-11-07T02:00:00.000Z');
	});
	it('marks "now" as the last radar frame', () => {
		const tl = buildTimeline([1, 2, 3], [4, 5]);
		expect(tl.now).toBe(2);
		expect(tl.frames.map((f) => f.past)).toEqual([true, true, true, false, false]);
		expect(buildTimeline([], [4]).now).toBe(-1);
	});
});

describe('frameLabel', () => {
	it('says how old a radar frame is', () => {
		const t = 1_800_000_000;
		expect(frameLabel({ t, past: true }, t * 1000).rel).toBe('radar · now');
		expect(frameLabel({ t, past: true }, (t + 1200) * 1000).rel).toBe('radar · 20 min ago');
		expect(frameLabel({ t, past: true }, (t + 6000) * 1000).rel).toBe('radar · 1 h 40 min ago');
	});
	it('names a forecast hour and how far ahead it is', () => {
		const end = new Date(2026, 10, 7, 6).getTime() / 1000; // Sat 6 AM local
		const lab = frameLabel({ t: end, past: false }, (end - 5 * 3600) * 1000);
		expect(lab.when).toBe('Sat 5–6 AM');
		expect(lab.rel).toBe('forecast · in 4 h');
		expect(frameLabel({ t: end, past: false }, (end - 1800) * 1000).rel).toBe(
			'forecast · this hour'
		);
		const noon = new Date(2026, 10, 7, 12).getTime() / 1000;
		expect(frameLabel({ t: noon, past: false }, 0).when).toBe('Sat 11 AM–12 PM');
	});
});

describe('styles and legend', () => {
	it('sends a ramp as a WMS colour map, capped at the top', () => {
		const sld = sldBody('X', RAMPS.snow.steps);
		expect(sld).toContain('<Name>X</Name>');
		expect(sld.match(/<ColorMapEntry/g)).toHaveLength(RAMPS.snow.steps.length + 1);
		expect(sld).toContain('quantity="9999"');
	});
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

describe('hrrrRecolor', () => {
	const rain = RAMPS.rain.steps.map((s) => s.color);
	const snow = RAMPS.snow.steps.map((s) => s.color);
	const mix = RAMPS.mix.steps.map((s) => s.color);
	const hex = (h: string) =>
		hrrrRecolor(parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5), 16));
	it('maps IEM greens and yellows to the rain ramp, light to heavy', () => {
		expect(hex('#d6efd0')).toBe(rain[0]);
		expect(hex('#73c476')).toBe(rain[1]);
		expect(hex('#00441b')).toBe(rain[2]);
		expect(hex('#ffe81a')).toBe(rain[3]);
		expect(hex('#ffa000')).toBe(rain[5]);
	});
	it('maps blues to snow and purples or reds to mix', () => {
		expect(hex('#81c0d5')).toBe(snow[0]);
		expect(hex('#003f7f')).toBe(snow[4]);
		expect(hex('#dedded')).toBe(mix[0]);
		expect(hex('#7669af')).toBe(mix[1]);
		expect(hex('#fc8767')).toBe(mix[1]);
	});
	it('drops greys', () => {
		expect(hex('#808080')).toBeNull();
	});
});

describe('WPC 6-hour blocks', () => {
	const base = at('2026-11-06T18:00:00Z');
	it('reads its UTC timestamps', () => {
		expect(wpcTime('2026-11-06 18:00:00')).toBe(base);
	});
	it('picks the block holding each hour', () => {
		expect(wpcLayerFor(at('2026-11-06T19:00:00Z'), base)).toBe(13);
		expect(wpcLayerFor(at('2026-11-07T00:00:00Z'), base)).toBe(13);
		expect(wpcLayerFor(at('2026-11-07T01:00:00Z'), base)).toBe(14);
		expect(wpcLayerFor(at('2026-11-06T18:00:00Z'), base)).toBeNull();
		expect(wpcLayerFor(at('2026-11-10T01:00:00Z'), base)).toBeNull();
	});
});

describe('radar', () => {
	it('builds tile templates in time order', () => {
		const frames = radarFrames({
			host: 'https://tilecache.rainviewer.com',
			radar: {
				past: [
					{ time: 200, path: '/v2/radar/b' },
					{ time: 100, path: '/v2/radar/a' }
				]
			}
		});
		expect(frames.map((f) => f.time)).toEqual([100, 200]);
		expect(frames[0].url).toBe(
			'https://tilecache.rainviewer.com/v2/radar/a/256/{z}/{x}/{y}/2/1_1.png'
		);
		expect(radarFrames(null)).toEqual([]);
	});
	it('turns reflectivity into rates', () => {
		expect(rainRate(30)).toBeCloseTo(2.7, 1);
		expect(snowRate(30)).toBeCloseTo(2.36, 1);
	});
	it("repaints RainViewer's rain and snow colours in ours", () => {
		const rain = RAMPS.rain.steps.map((s) => s.color);
		const snow = RAMPS.snow.steps.map((s) => s.color);
		expect(radarRecolor(0x88, 0xdd, 0xee)).toBe(rain[0]); // 15 dBZ rain
		expect(radarRecolor(0x00, 0x77, 0xaa)).toBe(rain[2]); // 25 dBZ: ~1.3 mm/h
		expect(radarRecolor(0xff, 0x44, 0x00)).toBe(rain[5]); // 45 dBZ
		expect(radarRecolor(0x85, 0xc5, 0xff)).toBe(snow[1]); // 19 dBZ snow: ~0.6 cm/h
		expect(radarRecolor(0x00, 0x3f, 0xff)).toBe(snow[4]); // 55 dBZ snow
		expect(radarRecolor(0xc7, 0xff, 0xff)).toBeNull(); // 0 dBZ snow: too light to show
	});
});
