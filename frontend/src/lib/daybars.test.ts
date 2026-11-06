import { describe, expect, it } from 'vitest';
import { dailyTotals, dayPairs, precipKind } from './daybars';
import type { OverviewPeriod } from './types.gen';

const p = (date: string, kind: string, snow_cm: number, ptype = 'snow'): OverviewPeriod => ({
	key: `${date}-${kind}`,
	label: kind,
	kind,
	date,
	snow_cm,
	ptype
});

describe('precipKind', () => {
	it('keeps rain and mix whatever the amount', () => {
		expect(precipKind('rain', 3, true)).toBe('rain');
		expect(precipKind('mix', 0, false)).toBe('mix');
	});
	it('turns snow heavy on a 6+ in day', () => {
		expect(precipKind('snow', 2, false)).toBe('snow');
		expect(precipKind('snow', 2, true)).toBe('heavy');
	});
	it('treats an untyped amount as snow and nothing as none', () => {
		expect(precipKind('none', 1, false)).toBe('snow');
		expect(precipKind('none', 0, false)).toBe('none');
	});
});

describe('dayPairs', () => {
	it('pairs day and night per date and flags weekends', () => {
		// 2026-11-06 is a Friday, 2026-11-07 a Saturday.
		const days = dayPairs([
			p('2026-11-06', 'night', 4),
			p('2026-11-07', 'day', 9),
			p('2026-11-07', 'night', 8),
			p('2026-11-08', 'day', 0, 'rain')
		]);
		expect(days.map((d) => d.short)).toEqual(['F', 'Sa', 'Su']);
		expect(days[0].day).toBeNull();
		expect(days[0].night).toEqual({ cm: 4, kind: 'snow' });
		expect(days[1].weekend).toBe(true);
		expect(days[1].total).toBe(17);
		expect(days[1].day?.kind).toBe('heavy');
		expect(days[2].day?.kind).toBe('rain');
	});
	it('stops at the limit', () => {
		const ps = Array.from({ length: 14 }, (_, i) =>
			p(`2026-11-${String(i + 1).padStart(2, '0')}`, 'day', 1)
		);
		expect(dayPairs(ps, 10)).toHaveLength(10);
	});
});

describe('dailyTotals', () => {
	it('adds day and night and colours each day by its main type', () => {
		const days = dailyTotals([
			{ ...p('2026-11-05', 'day', 1), label: 'Today' },
			p('2026-11-05', 'night', 2),
			p('2026-11-06', 'day', 9),
			p('2026-11-06', 'night', 8),
			p('2026-11-07', 'day', 0.5, 'rain'),
			p('2026-11-07', 'night', 0, 'none')
		]);
		expect(days.map((d) => d.label)).toEqual(['Today', 'Fri', 'Sat']);
		expect(days.map((d) => d.cm)).toEqual([3, 17, 0.5]);
		expect(days.map((d) => d.kind)).toEqual(['snow', 'heavy', 'rain']);
	});
	it('marks a dry day as none', () => {
		expect(dailyTotals([p('2026-11-08', 'day', 0, 'none')])[0].kind).toBe('none');
	});
});
