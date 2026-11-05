import { describe, expect, it } from 'vitest';
import { flagText, flagTitle, isNew } from './flags';
import type { Flag } from './types.gen';

const f = (over: Partial<Flag>): Flag => ({ type: 'powder_day', severity: 'notice', ...over });

describe('flag wording', () => {
	it('titles name the day', () => {
		expect(flagTitle(f({ date: '2026-12-05' }))).toBe('Powder Sat');
		expect(flagTitle(f({ type: 'snow_level_crossing', detail: 'below_base' }))).toBe(
			'Snow to the base'
		);
		expect(flagTitle(f({ type: 'avalanche_danger', value: 4 }))).toBe('Avalanche 4 · High');
	});

	it('uses the viewer units', () => {
		const storm = f({ type: 'storm_incoming', date: '2026-12-04', value: 30.48, value2: 55 });
		expect(flagText(storm, 'imperial')).toBe(
			'12.0 in in 48 h from Fri; 55% of ensemble members agree on a storm.'
		);
		expect(flagText(storm, 'metric')).toMatch(/^30(\.5)? cm in 48 h from Fri/);
		const wind = f({ type: 'wind_hold', date: '2026-12-04', value: 80 });
		expect(flagText(wind, 'imperial')).toMatch(/gusts to 50 mph/);
		expect(flagText(wind, 'metric')).toMatch(/gusts to 80 km\/h/);
	});

	it('every known type has a sentence', () => {
		for (const type of [
			'powder_day',
			'storm_incoming',
			'model_outlier',
			'low_confidence',
			'rain_on_snow',
			'snow_level_crossing',
			'wind_hold',
			'best_day',
			'wind_loading',
			'rapid_warming',
			'refreeze',
			'nws_alert',
			'avalanche_danger'
		])
			expect(flagText(f({ type, value: 10, value2: 5, date: '2026-12-01' }), 'imperial')).not.toBe(
				''
			);
	});

	it('marks flags raised in the current run as new', () => {
		expect(isNew(f({ first_run: 7 }), 7)).toBe(true);
		expect(isNew(f({ first_run: 6 }), 7)).toBe(false);
		expect(isNew(f({ first_run: 7 }), null)).toBe(false);
	});
});
