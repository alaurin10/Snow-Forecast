import { describe, expect, it } from 'vitest';
import { availableRanges, buildSteps, niceAxis } from './forecast';
import type { HourlyOut } from '../types.gen';

// 48 hours from Thu 1 PM; snow on Friday, rain for the first two hours.
function hourly(): HourlyOut {
	const n = 48;
	const t = Array.from({ length: n }, (_, i) => {
		const d = new Date(Date.UTC(2026, 10, 5, 13 + i));
		const pad = (x: number) => String(x).padStart(2, '0');
		return `2026-11-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:00-08:00`;
	});
	const hr = (i: number) => (13 + i) % 24;
	const fill = <T>(f: (i: number) => T) => Array.from({ length: n }, (_, i) => f(i));
	const friday = (i: number) => t[i].startsWith('2026-11-06');
	return {
		t,
		snow_cm: fill((i) => (friday(i) ? 1 : 0)),
		rain_mm: fill((i) => (i < 2 ? 2 : 0)),
		ptype: fill((i) => (i < 2 ? 'rain' : friday(i) ? 'snow' : 'none')),
		temp_c: fill((i) => -5 + (hr(i) > 6 && hr(i) < 18 ? 4 : 0)),
		wind_kmh: fill(() => 20),
		gust_kmh: fill((i) => 30 + i),
		wdir: fill(() => 225),
		cloud: fill(() => 80),
		fl_m: fill(() => 1500),
		is_day: fill((i) => (hr(i) >= 6 && hr(i) < 18 ? 1 : 0)),
		cloud_high: [],
		cloud_low: [],
		cloud_mid: [],
		fl_hi: [],
		fl_lo: [],
		pop: [],
		snow_level_m: [],
		swe_mm: [],
		temp_hi: [],
		temp_lo: [],
		visibility_m: [],
		water_mm: [],
		wcode: [],
		wind_hi: []
	};
}

describe('availableRanges', () => {
	it('offers only ranges the data covers', () => {
		expect(availableRanges(240)).toEqual([1, 3, 5, 10]);
		expect(availableRanges(48)).toEqual([1]);
	});
});

describe('buildSteps', () => {
	it('uses hourly steps for one day', () => {
		const s = buildSteps(hourly(), 1);
		expect(s).toHaveLength(24);
		expect(s[0].kind).toBe('rain');
		// 2 mm of rain is 0.2 cm of water, shown as 2 cm of snow at 10:1.
		expect(s[0].rain).toBeCloseTo(0.2);
		expect(s[0].precip).toBeCloseTo(2);
	});
	it('starts 3-hour steps on a boundary', () => {
		const s = buildSteps(hourly(), 3);
		expect(s[0].t.slice(11, 13)).toBe('15');
		expect(s).toHaveLength(15);
		expect(s[0].hours).toBe(3);
	});
	it('marks a 6+ in day as heavy snow', () => {
		const s = buildSteps(hourly(), 1);
		const fri = s.filter((x) => x.t.startsWith('2026-11-06'));
		expect(fri.every((x) => x.kind === 'heavy')).toBe(true);
		expect(s[s.length - 1].cum).toBeCloseTo(13);
	});
	it('splits 10 days into day and night halves with highs and lows', () => {
		const s = buildSteps(hourly(), 10);
		expect(s.map((x) => x.t.slice(11, 13))).toEqual(['18', '06', '18']);
		expect(s.map((x) => x.tempKind)).toEqual(['low', 'high', 'low']);
		expect(s[1].temp).toBe(-1);
		expect(s[0].temp).toBe(-5);
	});
});

describe('model range and precipitation chance', () => {
	it('carries the temperature spread and the highest chance in each step', () => {
		const h = hourly();
		h.temp_lo = h.temp_c.map((v) => (v ?? 0) - 2);
		h.temp_hi = h.temp_c.map((v) => (v ?? 0) + 3);
		h.pop = h.t.map((_, i) => i);
		const s = buildSteps(h, 10);
		expect(s[1].tempKind).toBe('high');
		expect([s[1].tempLo, s[1].tempHi]).toEqual([-3, 2]);
		expect(s[0].pop).toBe(16);
	});
	it('averages cloud cover at each height', () => {
		const h = hourly();
		h.cloud_low = h.t.map(() => 90);
		h.cloud_mid = h.t.map((_, i) => (i % 2 ? 40 : 60));
		h.cloud_high = h.t.map(() => 10);
		const [s] = buildSteps(h, 1);
		expect([s.cloudLow, s.cloudMid, s.cloudHigh]).toEqual([90, 60, 10]);
		expect(buildSteps(h, 3)[0].cloudMid).toBeCloseTo(53.33, 1);
	});
});

describe('precipitation type', () => {
	it('gives each step one type and keeps orange for snow', () => {
		const h = hourly();
		// Friday: 1 cm of snow an hour; add 0.5 mm of rain an hour on Friday morning only.
		h.rain_mm = h.t.map((t) => (t.startsWith('2026-11-06T0') ? 0.5 : 0));
		const s = buildSteps(h, 1);
		const fri = s.filter((x) => x.t.startsWith('2026-11-06'));
		// 1 cm snow + 0.05 cm water (0.5 cm as snow) per hour: a third is rain, so mixed.
		expect(fri.filter((x) => x.t.slice(11, 12) === '0').every((x) => x.kind === 'mix')).toBe(true);
		expect(fri.filter((x) => x.t.slice(11, 12) === '1').every((x) => x.kind === 'heavy')).toBe(
			true
		);
	});
});

describe('niceAxis', () => {
	it('rounds to tidy ticks', () => {
		expect(niceAxis(0, 2.3)).toEqual({ min: 0, max: 2.5, ticks: [0, 0.5, 1, 1.5, 2, 2.5] });
		const a = niceAxis(14, 37);
		expect(a.min).toBeLessThanOrEqual(14);
		expect(a.max).toBeGreaterThanOrEqual(37);
	});
});
