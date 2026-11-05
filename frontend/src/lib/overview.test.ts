import { describe, expect, it } from 'vitest';
import { arrange } from './overview';
import { bucket, labelled } from './calendar';
import type { OverviewRow } from './types.gen';

const row = (id: string, kind: string, next5: number | null, name = id): OverviewRow =>
	({
		id,
		name,
		kind,
		region: '',
		country: 'US',
		next5_cm: next5,
		d6_10_cm: 0,
		last24_cm: 0
	}) as OverviewRow;

describe('overview arrange', () => {
	const rows = [
		row('a', 'resort', 5),
		row('b', 'backcountry', 20),
		row('c', 'resort', null),
		row('d', 'resort', 12)
	];
	it('sorts by snow, missing data last', () => {
		expect(arrange(rows, 'next5', 'all').map((r) => r.id)).toEqual(['b', 'd', 'a', 'c']);
	});
	it('filters by kind', () => {
		expect(arrange(rows, 'next5', 'backcountry').map((r) => r.id)).toEqual(['b']);
		expect(arrange(rows, 'name', 'resort').map((r) => r.id)).toEqual(['a', 'c', 'd']);
	});
});

describe('calendar ramp', () => {
	it('buckets at 1, 3, 6 and 12 inches', () => {
		expect([null, 0, 0.2, 1, 2.54, 7.62, 15.24, 30.48, 80].map(bucket)).toEqual([
			0, 0, 0, 1, 2, 3, 4, 5, 5
		]);
		expect(labelled(2.5)).toBe(false);
		expect(labelled(2.54)).toBe(true);
	});
});
