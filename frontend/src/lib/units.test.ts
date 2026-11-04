import { describe, expect, it } from 'vitest';
import { cToF, cmToIn, elevation, mToFt, mmToIn, snow, speed, temperature } from './units';

describe('conversions', () => {
	it('converts snow, water, temperature, height and speed', () => {
		expect(cmToIn(2.54)).toBeCloseTo(1);
		expect(mmToIn(25.4)).toBeCloseTo(1);
		expect(cToF(0)).toBe(32);
		expect(cToF(-40)).toBe(-40);
		expect(mToFt(1000)).toBeCloseTo(3280.84);
	});
});

describe('formatting', () => {
	it('formats in both unit systems', () => {
		expect(snow(15.24, 'imperial')).toBe('6.0 in');
		expect(snow(15.24, 'metric')).toBe('15 cm');
		expect(temperature(-1, 'imperial')).toBe('30°F');
		expect(elevation(1800, 'imperial')).toBe('5,900 ft');
		expect(elevation(1800, 'metric')).toBe('1,800 m');
		expect(speed(50, 'imperial')).toBe('31 mph');
	});

	it('shows a dash for missing values', () => {
		expect(snow(null, 'imperial')).toBe('–');
		expect(temperature(null, 'metric')).toBe('–');
	});
});
