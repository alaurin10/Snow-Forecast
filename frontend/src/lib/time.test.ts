import { describe, expect, it } from 'vitest';
import { ago, dayHour, instant, weekday } from './time';

describe('time helpers', () => {
	const now = Date.parse('2026-11-09T12:00:00Z');

	it('says how long ago, never negative', () => {
		expect(ago('2026-11-09T11:55:00Z', now)).toBe('5 min ago');
		expect(ago('2026-11-09T09:00:00Z', now)).toBe('3 h ago');
		expect(ago('2026-11-06T12:00:00Z', now)).toBe('3 days ago');
		expect(ago('2026-11-09T12:10:00Z', now)).toBe('0 min ago'); // clock skew
		expect(ago(null, now)).toBe('never');
	});

	it('names the zone of an instant', () => {
		expect(instant('2026-11-09T22:00:00Z', 'America/Los_Angeles')).toBe('Nov 9, 2:00 PM PST');
		expect(instant(null)).toBe('–');
	});

	it('reads wall-clock labels straight from local ISO strings', () => {
		expect(weekday('2026-11-09')).toBe('Mon');
		expect(dayHour('2026-11-09T14:00-08:00')).toBe('Mon 2 PM');
	});
});
