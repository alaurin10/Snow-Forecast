import { describe, expect, it } from 'vitest';
import type { PointRate } from '../types.gen';
import { intensity, radarNow } from './radarnow';

const r = (t: number, kind: string, type: PointRate['type'], low = 0.5, filled = false) =>
	({ t, kind, span_h: 0, type, low: type ? low : null, high: null, filled }) as PointRate;
const clock = (t: number) => `t${t}`;

describe('radar at a tapped spot', () => {
	it('says what the latest scan shows and when the nowcast changes it', () => {
		const rates = [r(100, 'radar', null), r(200, 'radar', 'snow', 1.5), r(300, 'nowcast', 'snow')];
		expect(radarNow(rates, clock)).toEqual({ now: 'Moderate snow', change: '', filled: false });
		const ending = [...rates, r(400, 'nowcast', null), r(500, 'forecast', 'snow')];
		expect(radarNow(ending, clock)?.change).toBe('Ending about t400');
		const starting = [r(200, 'radar', null), r(300, 'nowcast', null), r(400, 'nowcast', 'rain')];
		expect(radarNow(starting, clock)).toEqual({
			now: 'Dry',
			change: 'Starting about t400',
			filled: false
		});
	});

	it('says when the forecast is filling in where no radar sees', () => {
		expect(radarNow([r(200, 'radar', 'snow', 0.2, true)], clock)?.filled).toBe(true);
	});

	it('has nothing to say without a scan', () => {
		expect(radarNow([r(500, 'forecast', 'snow')], clock)).toBeNull();
		expect(intensity(0.1)).toBe('Light');
		expect(intensity(5)).toBe('Heavy');
	});
});
