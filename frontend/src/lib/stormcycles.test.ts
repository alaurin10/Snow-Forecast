import { describe, expect, it } from 'vitest';
import { locationStorms, stormCycles } from './stormcycles';
import type { OverviewPeriod, OverviewRow } from './types.gen';

const per = (date: string, kind: string, snow_cm: number, ptype = 'snow'): OverviewPeriod => ({
	key: `${date}-${kind}`,
	label: kind,
	kind,
	date,
	snow_cm,
	ptype
});
const row = (id: string, periods: OverviewPeriod[]) =>
	({ id, name: id.toUpperCase(), periods }) as unknown as OverviewRow;

describe('locationStorms', () => {
	it('finds runs that add up and notes rain in them', () => {
		const s = locationStorms('a', 'A', [
			per('2026-11-05', 'night', 3),
			per('2026-11-06', 'day', 4, 'mix'),
			per('2026-11-06', 'night', 0),
			per('2026-11-07', 'day', 2),
			per('2026-11-07', 'night', 0),
			per('2026-11-09', 'day', 6)
		]);
		expect(s.map((x) => [x.start, x.end, x.total_cm, x.wet])).toEqual([
			['2026-11-05', '2026-11-06', 7, true],
			['2026-11-09', '2026-11-09', 6, false]
		]);
	});
});

describe('stormCycles', () => {
	it('merges overlapping storms and ranks the locations', () => {
		const c = stormCycles([
			row('a', [per('2026-11-06', 'day', 6), per('2026-11-06', 'night', 4)]),
			row('b', [per('2026-11-06', 'night', 0), per('2026-11-07', 'day', 0)]),
			row('c', [per('2026-11-06', 'night', 9), per('2026-11-07', 'day', 9)]),
			row('d', [per('2026-11-12', 'day', 8)])
		]);
		expect(c).toHaveLength(2);
		expect(c[0].start).toBe('2026-11-06');
		expect(c[0].end).toBe('2026-11-07');
		expect(c[0].locations.map((l) => l.id)).toEqual(['c', 'a']);
		expect(c[0].max_cm).toBe(18);
		expect(c[1].locations.map((l) => l.id)).toEqual(['d']);
	});
});
