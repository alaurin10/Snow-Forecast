import { describe, expect, it, beforeEach } from 'vitest';
import { favourites, filterRows, groupRows, regionGroup } from './locgroups.svelte';

const row = (id: string, region: string, name = id) => ({ id, name, region });
const of = (r: { id: string; name: string; region: string }) => r;

describe('location groups', () => {
	beforeEach(() => {
		try {
			localStorage.clear();
		} catch {
			// no storage here
		}
		for (const id of [...favourites.ids]) favourites.toggle(id);
	});

	it('groups by state or province', () => {
		expect(regionGroup('Snoqualmie Pass, WA')).toBe('Washington');
		expect(regionGroup('Washington')).toBe('Washington');
		expect(regionGroup('Sea to Sky, BC')).toBe('British Columbia');
		expect(regionGroup('British Columbia')).toBe('British Columbia');
		expect(regionGroup('Mt Hood, OR')).toBe('Oregon');
		expect(regionGroup('WA Cascades')).toBe('Washington');
		expect(regionGroup('BC Interior (Selkirks)')).toBe('British Columbia');
		expect(regionGroup('North Cascades')).toBe('North Cascades');
		expect(regionGroup('Somewhere')).toBe('Somewhere');
		expect(regionGroup('')).toBe('Other');
		expect(regionGroup(null)).toBe('Other');
	});

	it('keeps the order rows come in, favourites first', () => {
		const rows = [
			row('crystal', 'Crystal, WA'),
			row('whistler', 'British Columbia'),
			row('baker', 'Washington'),
			row('hood', 'Mt Hood, OR')
		];
		expect(groupRows(rows, new Set(), of).map((g) => [g.label, g.rows.map((r) => r.id)])).toEqual([
			['Washington', ['crystal', 'baker']],
			['British Columbia', ['whistler']],
			['Oregon', ['hood']]
		]);
		const g = groupRows(rows, new Set(['hood', 'baker']), of);
		expect(g[0]).toEqual({ label: 'Favourites', rows: [rows[2], rows[3]] });
		expect(g.map((x) => x.label)).toEqual(['Favourites', 'Washington', 'British Columbia']);
	});

	it('filters by name or region', () => {
		const rows = [
			row('crystal', 'Crystal, WA', 'Crystal Mountain'),
			row('whistler', 'BC', 'Whistler')
		];
		expect(filterRows(rows, 'crys', of).map((r) => r.id)).toEqual(['crystal']);
		expect(filterRows(rows, 'washington', of).map((r) => r.id)).toEqual(['crystal']);
		expect(filterRows(rows, 'british col', of).map((r) => r.id)).toEqual(['whistler']);
		expect(filterRows(rows, '  ', of)).toEqual(rows);
	});

	it('remembers favourites in this browser', () => {
		favourites.toggle('crystal');
		expect(favourites.has('crystal')).toBe(true);
		expect(JSON.parse(localStorage.getItem('sw.favourites') ?? '[]')).toEqual(['crystal']);
		favourites.toggle('crystal');
		expect(favourites.has('crystal')).toBe(false);
	});
});
