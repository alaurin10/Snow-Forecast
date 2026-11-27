// In jsdom (the .svelte.test project) for its localStorage.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { forgetSpots, MAX_RECENT, recentSpots, rememberSpot, spotSearch } from './recentSpots';

const spot = (i: number) => ({ lat: 47 + i / 100, lon: -121, name: `Spot ${i}`, elev_m: 1500 });

describe('recent spots', () => {
	beforeEach(() => localStorage.clear());

	it('keeps the newest ten, newest first, each once', () => {
		for (let i = 0; i < 12; i++) rememberSpot(spot(i), i);
		rememberSpot({ ...spot(5), lat: 47.0502 }, 99); // the same ~100 m as spot 5
		const list = recentSpots();
		expect(list).toHaveLength(MAX_RECENT);
		expect(list[0]).toMatchObject({ name: 'Spot 5', at: 99 });
		expect(list.filter((s) => s.name === 'Spot 5')).toHaveLength(1);
		expect(list.map((s) => s.name)).not.toContain('Spot 0');
	});

	it('survives bad or blocked storage', () => {
		localStorage.setItem('sw.recentSpots', '{not json');
		expect(recentSpots()).toEqual([]);
		localStorage.setItem('sw.recentSpots', JSON.stringify([{ lat: 'x' }, spot(1)]));
		expect(recentSpots()).toHaveLength(1);
		const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new Error('blocked');
		});
		expect(rememberSpot(spot(2))[0].name).toBe('Spot 2');
		set.mockRestore();
		forgetSpots();
		expect(recentSpots()).toEqual([]);
	});

	it('links to the spot page at ~100 m', () => {
		expect(spotSearch(46.93549, -121.47451)).toBe('?lat=46.935&lon=-121.475');
	});
});
