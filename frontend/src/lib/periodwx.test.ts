import { describe, expect, it } from 'vitest';
import { periodWeather, wxIcon } from './periodwx';
import type { HourlyOut, PeriodOut } from './types.gen';

const per = (o: Partial<PeriodOut>) =>
	({
		kind: 'day',
		ptype: 'none',
		snow_cm: 0,
		rain_mm: 0,
		start: '2026-11-06T06:00-08:00',
		hours: 12,
		...o
	}) as unknown as PeriodOut;

describe('periodWeather', () => {
	it('takes the strongest code and the mid-period wind direction', () => {
		const t = Array.from(
			{ length: 24 },
			(_, i) => `2026-11-06T${String(i).padStart(2, '0')}:00-08:00`
		);
		const h = {
			t,
			wcode: t.map((_, i) => (i === 10 ? 73 : 3)),
			wdir: t.map((_, i) => i * 10)
		} as unknown as HourlyOut;
		expect(periodWeather(h, per({}))).toEqual({ wcode: 73, wdir: 120 });
	});
});

describe('wxIcon', () => {
	it('follows the precipitation type when it is wet', () => {
		expect(wxIcon(per({ ptype: 'snow', snow_cm: 4 }), 3)).toBe('snow');
		expect(wxIcon(per({ ptype: 'rain', rain_mm: 3 }), 61)).toBe('rain');
		expect(wxIcon(per({ ptype: 'mix', snow_cm: 1 }), 61)).toBe('mix');
	});
	it('uses the sky when dry, with a moon at night', () => {
		expect(wxIcon(per({}), 0)).toBe('clear-day');
		expect(wxIcon(per({ kind: 'night' }), 1)).toBe('clear-night');
		expect(wxIcon(per({ kind: 'night' }), 2)).toBe('partly-night');
		expect(wxIcon(per({}), 3)).toBe('cloud');
		expect(wxIcon(per({}), 45)).toBe('fog');
		expect(wxIcon(per({}), 95)).toBe('thunder');
	});
});
