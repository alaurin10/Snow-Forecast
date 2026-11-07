import { describe, expect, it } from 'vitest';
import {
	forecastLabel,
	forecastTimes,
	frameLabel,
	parseTimeDimension,
	radarFrames,
	RAMPS,
	rampTop,
	sldBody
} from './radar';

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
		expect(frameLabel(t, t * 1000).rel).toBe('latest');
		expect(frameLabel(t, (t + 1200) * 1000).rel).toBe('20 min ago');
		expect(frameLabel(t, (t + 6000) * 1000).rel).toBe('1 h 40 min ago');
	});
});

describe('parseTimeDimension', () => {
	it('expands a start/end/period range', () => {
		const ts = parseTimeDimension('2026-11-06T19:00:00Z/2026-11-06T22:00:00Z/PT1H');
		expect(ts).toHaveLength(4);
		expect(ts[1] - ts[0]).toBe(3600);
		expect(new Date(ts[0] * 1000).toISOString()).toBe('2026-11-06T19:00:00.000Z');
	});
	it('reads comma lists and skips junk', () => {
		const ts = parseTimeDimension('2026-11-06T19:00:00Z, nonsense, 2026-11-06T18:00:00Z');
		expect(ts).toHaveLength(2);
		expect(ts[0]).toBeLessThan(ts[1]);
	});
});

describe('forecastTimes', () => {
	const caps = `<Layer><Name>HRDPS.CONTINENTAL.DIAG_SN_PT1H</Name>
		<Dimension name="time" units="ISO8601" default="x">2026-11-06T19:00:00Z/2026-11-08T18:00:00Z/PT1H</Dimension></Layer>`;
	it('keeps the hour under way and everything after it', () => {
		const now = Date.parse('2026-11-07T01:20:00Z');
		const ts = forecastTimes(caps, now);
		expect(new Date(ts[0] * 1000).toISOString()).toBe('2026-11-07T02:00:00.000Z');
		expect(new Date(ts[ts.length - 1] * 1000).toISOString()).toBe('2026-11-08T18:00:00.000Z');
	});
	it('returns nothing without a time dimension', () => {
		expect(forecastTimes('<Layer/>')).toEqual([]);
	});
});

describe('forecastLabel', () => {
	it('names the hour and how far ahead it is', () => {
		const end = new Date(2026, 10, 7, 6).getTime() / 1000; // Sat 6 AM local
		const lab = forecastLabel(end, (end - 5 * 3600) * 1000);
		expect(lab.when).toBe('Sat 5–6 AM');
		expect(lab.rel).toBe('in 4 h');
		expect(forecastLabel(end, (end - 1800) * 1000).rel).toBe('this hour');
	});
	it('spans noon', () => {
		const end = new Date(2026, 10, 7, 12).getTime() / 1000;
		expect(forecastLabel(end, 0).when).toBe('Sat 11 AM–12 PM');
	});
});

describe('forecast styles', () => {
	it('sends each ramp as a WMS colour map, capped at the top', () => {
		const snow = RAMPS.find((r) => r.kind === 'snow')!;
		const sld = sldBody(snow);
		expect(sld).toContain(`<Name>${snow.layer}</Name>`);
		expect(sld.match(/<ColorMapEntry/g)).toHaveLength(snow.steps.length + 1);
		expect(sld).toContain('quantity="9999"');
	});
	it('labels the top of each ramp in the chosen units', () => {
		const snow = RAMPS.find((r) => r.kind === 'snow')!;
		const rain = RAMPS.find((r) => r.kind === 'rain')!;
		expect(rampTop(snow, 'metric')).toBe('3+ cm/h');
		expect(rampTop(snow, 'imperial')).toBe('1.2+ in/h');
		expect(rampTop(rain, 'metric')).toBe('10+ mm/h');
		expect(rampTop(rain, 'imperial')).toBe('0.4+ in/h');
	});
});
