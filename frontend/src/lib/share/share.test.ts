import { describe, expect, it } from 'vitest';
import { luminance, SIZES, slug } from './canvas';
import { dayRows } from './daysCard';
import { rangeWords } from './forecastCard';
import type { PeriodOut } from '../types.gen';

const period = (date: string, kind: 'day' | 'night', o: Partial<PeriodOut> = {}) =>
	({
		date,
		kind,
		label: kind === 'day' ? date : `${date} night`,
		snow_cm: 0,
		rain_mm: 0,
		tmax_c: null,
		tmin_c: null,
		wind_max_kmh: null,
		gust_max_kmh: null,
		snow_level_min_m: null,
		ptype: 'snow',
		...o
	}) as unknown as PeriodOut;

describe('share image sizes', () => {
	it('are phone-photo shapes: 3:4 portrait and 4:3 landscape', () => {
		expect(SIZES.portrait.w / SIZES.portrait.h).toBeCloseTo(3 / 4);
		expect(SIZES.landscape.w / SIZES.landscape.h).toBeCloseTo(4 / 3);
	});
});

describe('slug', () => {
	it('makes file-name-safe names', () => {
		expect(slug('Heather–Maple / Rainy Pass Freezing level 10 day')).toBe(
			'heather-maple-rainy-pass-freezing-level-10-day'
		);
		expect(slug('Crème Brûlée')).toBe('creme-brulee');
		expect(slug('///')).toBe('snow-watch');
	});
});

describe('luminance', () => {
	it('tells light theme backgrounds from dark ones', () => {
		expect(luminance('#faf7f4')).toBeGreaterThan(0.9);
		expect(luminance('#0a111d')).toBeLessThan(0.1);
		expect(luminance('not a colour')).toBe(1);
	});
});

describe('dayRows', () => {
	it('pairs each day with its night and sums the snow', () => {
		const rows = dayRows(
			[
				period('2026-11-05', 'night', { snow_cm: 2, tmin_c: -4 }),
				period('2026-11-06', 'day', { snow_cm: 5, tmax_c: 1, wind_max_kmh: 20, gust_max_kmh: 40 }),
				period('2026-11-06', 'night', {
					snow_cm: 3,
					tmin_c: -6,
					snow_level_min_m: 900,
					gust_max_kmh: 55
				}),
				period('2026-11-07', 'day', { snow_cm: 0, rain_mm: 4, ptype: 'rain' })
			],
			10
		);
		expect(rows.map((r) => r.date)).toEqual(['2026-11-05', '2026-11-06', '2026-11-07']);
		// A forecast that starts in the evening: the first day has only its night.
		expect(rows[0].day).toBeNull();
		expect(rows[0].total).toBe(2);
		expect(rows[1].total).toBe(8);
		expect(rows[1].hi).toBe(1);
		expect(rows[1].lo).toBe(-6);
		expect(rows[1].gust).toBe(55);
		expect(rows[1].level).toBe(900);
		expect(rows[2].rainMm).toBe(4);
	});
	it('stops at the number of days asked for', () => {
		const ps = ['01', '02', '03', '04'].flatMap((d) => [
			period(`2026-12-${d}`, 'day'),
			period(`2026-12-${d}`, 'night')
		]);
		expect(dayRows(ps, 3)).toHaveLength(3);
	});
});

describe('rangeWords', () => {
	it('names the range shown', () => {
		expect(rangeWords(1)).toBe('next 24 hours');
		expect(rangeWords(5)).toBe('next 5 days');
	});
});
