import { describe, expect, it } from 'vitest';
import { daylight, instances } from './layer';
import { layersAt, puffsAt, RADIUS_M, SLOTS, skyAt, slots, type CloudSite } from './puffs';

const T0 = 1_800_000_000;

function site(layers: number[][], hours = 24): CloudSite {
	return {
		id: 'crystal',
		lat: 46.93,
		lon: -121.47,
		clouds: { start: T0, step_h: 1, layers: Array.from({ length: hours }, () => layers) as never }
	};
}

describe('puffs around a location', () => {
	it('lays out the same places every time, ranked evenly', () => {
		const a = slots('crystal', 0);
		expect(slots('crystal', 0)).toBe(a);
		expect(a).toHaveLength(SLOTS);
		const ranks = a.map((s) => s.rank).sort((x, y) => x - y);
		expect(ranks[0]).toBeCloseTo(0.5 / SLOTS);
		expect(ranks[SLOTS - 1]).toBeCloseTo(1 - 0.5 / SLOTS);
		expect(Math.max(...a.map((s) => Math.hypot(s.dx, s.dy)))).toBeLessThan(RADIUS_M * 1.1);
		expect(slots('whistler', 0)[0].dx).not.toBe(a[0].dx);
	});

	it('draws nothing for clear sky, some for partly cloudy and more for a deck', () => {
		expect(puffsAt([site([])], T0)).toHaveLength(0);
		expect(puffsAt([site([[2000, 2600, 5]])], T0)).toHaveLength(0);
		const partly = puffsAt([site([[2000, 2600, 35]])], T0);
		const deck = puffsAt([site([[2000, 2600, 95]])], T0);
		expect(partly.length).toBeGreaterThan(SLOTS * 0.2);
		expect(partly.length).toBeLessThan(SLOTS * 0.5);
		expect(deck.length).toBeGreaterThan(SLOTS * 1.4); // two sets of places
		// A deck's puffs are bigger and darker.
		const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
		expect(mean(deck.map((p) => p.r))).toBeGreaterThan(mean(partly.map((p) => p.r)) * 1.5);
		expect(mean(deck.map((p) => p.dark))).toBeGreaterThan(mean(partly.map((p) => p.dark)));
	});

	it('puts puffs between the base and the top, flat for a thin layer', () => {
		const puffs = puffsAt([site([[1500, 1800, 60]])], T0);
		for (const p of puffs) {
			expect(p.z - p.r * p.squash * 0.6).toBeGreaterThanOrEqual(1499);
			expect(p.squash).toBeLessThan(0.5);
		}
	});

	it('draws a deep layer only near its base', () => {
		const puffs = puffsAt([site([[1000, 9000, 70]])], T0);
		expect(Math.max(...puffs.map((p) => p.z))).toBeLessThan(1000 + 2600);
	});

	it('draws every layer', () => {
		const two = puffsAt(
			[
				site([
					[1200, 1700, 60],
					[3200, 4200, 70]
				])
			],
			T0
		);
		expect(two.some((p) => p.z < 2000)).toBe(true);
		expect(two.some((p) => p.z > 3000)).toBe(true);
	});

	it('takes the nearest hour, and nothing outside the hours it has', () => {
		const s = site([[2000, 2500, 50]], 3);
		expect(layersAt(s, T0 + 1700)).toHaveLength(1);
		expect(layersAt(s, T0 - 3600)).toHaveLength(0);
		expect(layersAt(s, T0 + 3 * 3600)).toHaveLength(0);
	});

	it('words the sky', () => {
		expect(skyAt(site([]), T0)).toEqual({ sky: 'clear', base: null });
		expect(skyAt(site([[1800, 2400, 40]]), T0)).toEqual({ sky: 'partly', base: 1800 });
		expect(
			skyAt(
				site([
					[900, 1400, 60],
					[3000, 4000, 60]
				]),
				T0
			).sky
		).toBe('cloudy');
	});
});

describe('drawing them', () => {
	// Looking straight down the z axis from 1,000 units away: w is the distance.
	const m = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, -1, 0, 0, 0, 1000];

	it('sorts far to near and leaves out what is behind the camera', () => {
		const p = { y: 0, r: 100, squash: 1, dark: 0, alpha: 1, seed: 0, per: 1 };
		const puffs = [
			{ ...p, x: 0, z: 100 },
			{ ...p, x: 0, z: -500 },
			{ ...p, x: 0, z: 2000 } // behind the camera
		];
		const { data, count } = instances(puffs, m, {
			cx: 0,
			cy: 0,
			worldSize: 1,
			exaggeration: 1,
			fade: 0.5
		});
		expect(count).toBe(2);
		expect(data[2]).toBe(-500); // the farthest first
		expect(data[8 + 2]).toBe(100);
		expect(data[6]).toBe(0.5); // faded in by zoom
	});

	it('scales heights with the terrain', () => {
		const puffs = [{ x: 0, y: 0, z: 100, r: 1, squash: 1, dark: 0, alpha: 1, seed: 0, per: 1 }];
		const view = { cx: 0, cy: 0, worldSize: 1, exaggeration: 1.5, fade: 1 };
		expect(instances(puffs, m, view).data[2]).toBe(150);
	});

	it('is dim at night and warm at sunset', () => {
		expect(daylight(30)).toEqual({ light: 1, warm: 0 });
		expect(daylight(-20).light).toBeLessThan(0.5);
		expect(daylight(1).warm).toBeGreaterThan(0.5);
	});
});
