import { describe, expect, it } from 'vitest';
import { nextStorm } from './storm';
import type { PeriodOut } from './types.gen';

const p = (label: string, snow_cm: number, snow_level_min_m: number | null = null) =>
	({ label, snow_cm, snow_level_min_m, key: label }) as unknown as PeriodOut;

describe('nextStorm', () => {
	it('skips a light dusting and finds the first real storm', () => {
		const s = nextStorm([
			p('Today', 2),
			p('Tonight', 0),
			p('Fri', 4, 1200),
			p('Fri night', 9, 900),
			p('Sat', 3, 1000),
			p('Sat night', 0)
		]);
		expect(s?.first.label).toBe('Fri');
		expect(s?.last.label).toBe('Sat');
		expect(s?.peak.label).toBe('Fri night');
		expect(s?.total_cm).toBe(16);
		expect(s?.snow_level_min_m).toBe(900);
	});
	it('returns null when nothing adds up', () => {
		expect(nextStorm([p('Today', 1), p('Tonight', 0), p('Fri', 2)])).toBeNull();
	});
	it('handles a storm running to the end of the forecast', () => {
		expect(nextStorm([p('Thu', 0), p('Thu night', 6)])?.total_cm).toBe(6);
	});
});
