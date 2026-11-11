// Choosing the wind for the map's wind-effect layer.
import { describe, expect, it } from 'vitest';
import type { MapWindOut, RoseOut } from '../types.gen';
import { distanceKm, windSource } from './windsource';

const rose = (window: string, snow_cm: number, mean_kmh: number | null): RoseOut => ({
	window,
	sectors: [0, 0, 0, 0, 0, 1, 0, 0],
	snow_cm,
	mean_kmh,
	wind_from: 'SW',
	loading: ['NE'],
	label: 'SW wind, loading NE aspects'
});

const data: MapWindOut = {
	min_snow_cm: 2,
	min_wind_kmh: 15,
	locations: [
		{
			id: 'whistler',
			name: 'Whistler',
			lat: 50.06,
			lon: -122.95,
			generated_at: '2026-11-11T12:00:00Z',
			roses: [rose('past48', 1, 40), rose('next24', 12, 45), rose('next72', 30, 60)]
		},
		{
			id: 'old',
			name: 'Not updated yet',
			lat: 49.0,
			lon: -120.0,
			generated_at: '2026-11-10T12:00:00Z',
			roses: [rose('past72', 10, 30), rose('next48', 10, 30)]
		}
	]
};

describe('wind for the map', () => {
	it('measures distance over the ground', () => {
		// Whistler to Vancouver is about 95 km.
		const km = distanceKm(50.06, -122.95, 49.28, -123.12);
		expect(km).toBeGreaterThan(85);
		expect(km).toBeLessThan(90);
	});

	it('takes the nearest location within range, and none beyond it', () => {
		const near = windSource(data, 50.1, -122.9, 'next24')!;
		expect(near.location.id).toBe('whistler');
		expect(near.km).toBeLessThan(10);
		expect(near.rose?.window).toBe('next24');
		expect(windSource(data, 47.4, -121.4, 'next24')).toBeNull();
		expect(windSource(null, 50.1, -122.9, 'next24')).toBeNull();
	});

	it('scales with how much snow the wind could move', () => {
		const calm = windSource(data, 50.1, -122.9, 'past48')!;
		expect(calm.scale).toBe(0); // 1 cm: nothing to move
		const some = windSource(data, 50.1, -122.9, 'next24')!;
		const lots = windSource(data, 50.1, -122.9, 'next72')!;
		expect(some.scale).toBeGreaterThan(0.5);
		expect(lots.scale).toBe(1);
	});

	it('has no rose for a forecast made before the map asked for these windows', () => {
		const old = windSource(data, 49.01, -120.01, 'next24')!;
		expect(old.location.id).toBe('old');
		expect(old.rose).toBeNull();
		expect(old.scale).toBe(0);
	});
});
