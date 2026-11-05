import { describe, expect, it } from 'vitest';
import { newSnow, sortPlan } from './plan';
import type { PlanRow } from './types.gen';

const row = (
	id: string,
	score: number | null,
	overnight: number | null,
	day: number | null,
	kind = 'resort'
): PlanRow =>
	({
		id,
		name: id,
		kind,
		region: '',
		danger: { level: null, status: 'none' },
		day:
			overnight === null && day === null && score === null
				? null
				: { date: '2026-12-01', label: 'Mon', overnight_cm: overnight, day_cm: day, score }
	}) as PlanRow;

describe('plan sort', () => {
	const rows = [
		row('b', 3, 2, 1),
		row('a', 5, 20, 5),
		row('tour', null, 30, 10, 'backcountry'),
		row('none', null, null, null),
		row('c', 3, 8, 0)
	];
	it('sorts by rating, then snow; rows without data last', () => {
		expect(sortPlan(rows, 'rating').map((r) => r.id)).toEqual(['a', 'c', 'b', 'tour', 'none']);
	});
	it('sorts by new snow', () => {
		expect(sortPlan(rows, 'snow').map((r) => r.id)).toEqual(['tour', 'a', 'c', 'b', 'none']);
	});
	it('sorts by name', () => {
		expect(sortPlan(rows, 'name').map((r) => r.id)).toEqual(['a', 'b', 'c', 'tour', 'none']);
	});
	it('adds the night before to the day', () => {
		expect(newSnow(rows[1])).toBe(25);
		expect(newSnow(rows[3])).toBeNull();
	});
});
