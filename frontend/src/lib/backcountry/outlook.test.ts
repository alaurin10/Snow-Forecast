import { describe, expect, it } from 'vitest';
import type { AvalancheView, OutlookDay } from '../types.gen';
import { cell, drivers, outlookSummary, publishedDanger, stressWord } from './outlook';

const day = (date: string, over: Partial<OutlookDay> = {}): OutlookDay => ({
	date,
	new_cm: 0,
	storm_cm: 0,
	wind_kmh: 10,
	wind_from: null,
	loading: [],
	rain_mm: 0,
	rain_to_m: null,
	fl_max_m: 1500,
	thaw_h: 0,
	temp_rise_c: 0,
	refreeze: [],
	sky: null,
	levels: { snow: 0, wind: 0, rain: 0, warm: 0 },
	stress: 0,
	trend: 'steady',
	...over
});

const storm = (date: string) =>
	day(date, {
		new_cm: 30,
		storm_cm: 42,
		wind_kmh: 55,
		wind_from: 'S',
		loading: ['N'],
		levels: { snow: 2, wind: 2, rain: 0, warm: 0 },
		stress: 3,
		trend: 'rising'
	});

describe('stressWord', () => {
	it('has four words, none of them the danger scale’s', () => {
		const words = [0, 1, 2, 3].map(stressWord);
		expect(words).toEqual(['Little', 'Some', 'Strong', 'Very strong']);
		for (const w of words) expect(w).not.toMatch(/^(Low|Moderate|Considerable|High|Extreme)$/);
		expect(stressWord(9)).toBe('Very strong');
	});
});

describe('cell', () => {
	it('words new snow with the 72 h total when that is more', () => {
		expect(cell(storm('2026-11-06'), 'snow', 'imperial')).toEqual({
			value: '11.8 in',
			detail: '16.5 in in 72 h',
			level: 2
		});
		expect(cell(day('x', { new_cm: 5, storm_cm: 5 }), 'snow', 'metric').detail).toBe('');
	});
	it('words the wind and where it loads', () => {
		expect(cell(storm('x'), 'wind', 'imperial')).toMatchObject({
			value: 'S 34 mph',
			detail: 'loading N'
		});
		expect(cell(day('x', { wind_from: 'W', wind_kmh: 50 }), 'wind', 'metric').detail).toBe(
			'little snow to move'
		);
		expect(cell(day('x'), 'wind', 'metric')).toMatchObject({ value: '10 km/h', detail: 'light' });
	});
	it('says when there is no snow for rain to fall on', () => {
		expect(cell(day('x', { rain_mm: null }), 'rain', 'metric')).toMatchObject({
			value: '–',
			detail: 'no snow cover'
		});
		expect(cell(day('x', { rain_mm: 0 }), 'rain', 'metric').value).toBe('None');
		expect(cell(day('x', { rain_mm: 12, rain_to_m: 1800 }), 'rain', 'metric')).toMatchObject({
			value: '12.0 mm',
			detail: 'up to 1,800 m'
		});
	});
	it('shows the freezing level, and what the warmth amounts to', () => {
		expect(cell(day('x'), 'warm', 'metric')).toMatchObject({
			value: '1,500 m',
			detail: 'frozen up top'
		});
		expect(cell(day('x', { thaw_h: 9 }), 'warm', 'metric').detail).toBe(
			'9 h above freezing up top'
		);
		expect(cell(day('x', { temp_rise_c: 10 }), 'warm', 'imperial').detail).toBe(
			'18°F warmer in 24 h'
		);
	});
});

describe('drivers', () => {
	it('lists what pushes, strongest first', () => {
		const d = day('x', {
			new_cm: 12,
			storm_cm: 12,
			rain_mm: 25,
			rain_to_m: 2000,
			levels: { snow: 1, wind: 0, rain: 3, warm: 0 }
		});
		expect(drivers(d, 'metric')).toEqual(['25.0 mm of rain up to 2,000 m', '12 cm of new snow']);
	});
	it('names the storm total the day after', () => {
		const d = day('x', { new_cm: 0, storm_cm: 60, levels: { snow: 2, wind: 0, rain: 0, warm: 0 } });
		expect(drivers(d, 'metric')).toEqual(['60 cm in 72 h']);
	});
	it('mentions a night with no refreeze', () => {
		const d = day('x', {
			thaw_h: 12,
			refreeze: [{ date: 'w', band: 'summit', status: 'None', low_c: 2, clear_frac: 0 }],
			levels: { snow: 0, wind: 0, rain: 0, warm: 3 }
		});
		expect(drivers(d, 'metric')[0]).toBe('12 h above freezing at the summit after no refreeze');
	});
	it('is empty on a quiet day', () => {
		expect(drivers(day('x'), 'metric')).toEqual([]);
	});
});

describe('outlookSummary', () => {
	const T = '2026-11-04'; // a Wednesday
	it('says so when nothing is happening', () => {
		expect(outlookSummary([day(T), day('2026-11-05')], T, 'metric')).toBe(
			'Quiet weather for the snowpack through Thu: no real new snow, drifting, rain or warming.'
		);
	});
	it('names the one day that stands out, and when it eases', () => {
		const text = outlookSummary(
			[day(T), storm('2026-11-05'), day('2026-11-06', { stress: 2 }), day('2026-11-07')],
			T,
			'imperial'
		);
		expect(text).toBe(
			'Very strong weather stress Thu: 11.8 in of new snow and S wind to 34 mph loading N slopes. Easing by Sat.'
		);
	});
	it('joins runs of days', () => {
		const text = outlookSummary(
			[
				day(T),
				storm('2026-11-06'),
				storm('2026-11-07'),
				storm('2026-11-08'),
				day('2026-11-09'),
				storm('2026-11-10')
			],
			T,
			'metric'
		);
		expect(text).toMatch(
			/^Very strong weather stress Fri to Sun and Tue\. Fri brings 30 cm of new snow/
		);
		expect(text).not.toMatch(/Easing/);
	});
	it('says today', () => {
		expect(outlookSummary([storm(T), day('2026-11-05')], T, 'metric')).toMatch(
			/^Very strong weather stress today: .* Easing by Thu\.$/
		);
	});
	it('has nothing to say without days', () => {
		expect(outlookSummary([], T, 'metric')).toBe('');
	});
});

describe('publishedDanger', () => {
	const view = (status: AvalancheView['status']): AvalancheView => ({
		location_id: 'x',
		status,
		today_max: null,
		doc: {
			provider: 'nac',
			center: 'c',
			center_id: 'C',
			zone: 'z',
			link: null,
			issued_at: null,
			expires_at: null,
			days: [
				{ date: '2026-11-04', alpine: 3, treeline: 2, below: null },
				{ date: '2026-11-05', alpine: null, treeline: null, below: null }
			],
			problems: [],
			summary: null,
			off_season: false
		}
	});
	it('is the day’s highest rating, only while the bulletin is current', () => {
		expect(publishedDanger(view('current'), '2026-11-04')).toBe(3);
		expect(publishedDanger(view('expired'), '2026-11-04')).toBeNull();
		expect(publishedDanger(view('no_rating'), '2026-11-04')).toBeNull();
		expect(publishedDanger(null, '2026-11-04')).toBeNull();
	});
	it('is nothing for a day the bulletin does not rate', () => {
		expect(publishedDanger(view('current'), '2026-11-05')).toBeNull();
		expect(publishedDanger(view('current'), '2026-11-06')).toBeNull();
	});
});
