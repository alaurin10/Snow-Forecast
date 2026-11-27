import { describe, expect, it } from 'vitest';
import type { Snapshot } from './types.gen';
import { spotTitle } from './spotname';
import { distance } from './units';

const snap = (peak: unknown, name = '1.2 km NE of Mount Stuart') =>
	({ location: { name }, spot: { peak } }) as unknown as Snapshot;

describe('a spot’s name', () => {
	it('is the peak it’s on, or where it is from the nearest, in the viewer’s units', () => {
		expect(spotTitle(snap({ name: 'Mount Stuart', km: 0.2, bearing: null }), 'imperial')).toBe(
			'Mount Stuart'
		);
		const near = snap({ name: 'Mount Stuart', km: 1.23, bearing: 'NE' });
		expect(spotTitle(near, 'metric')).toBe('1.2 km NE of Mount Stuart');
		expect(spotTitle(near, 'imperial')).toBe('0.8 mi NE of Mount Stuart');
		// No peak near: the server's own name.
		expect(spotTitle(snap(null, '6 km NE of Crystal Mountain'), 'imperial')).toBe(
			'6 km NE of Crystal Mountain'
		);
	});
	it('words short distances plainly', () => {
		expect(distance(0.62, 'metric')).toBe('600 m');
		expect(distance(0.02, 'metric')).toBe('100 m');
		expect(distance(14.4, 'metric')).toBe('14 km');
		expect(distance(0.05, 'imperial')).toBe('0.1 mi');
		expect(distance(30, 'imperial')).toBe('19 mi');
	});
});
