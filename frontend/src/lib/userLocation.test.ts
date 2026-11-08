import { describe, expect, it } from 'vitest';
import { circle, compassHeading } from './userLocation';

describe('your location', () => {
	it('draws the accuracy circle at the right size', () => {
		const ring = circle(-121.427, 47.445, 100).coordinates[0];
		expect(ring[0]).toEqual(ring[ring.length - 1]);
		const north = Math.max(...ring.map(([, lat]) => lat));
		// 100 m north is ~0.0009 degrees of latitude.
		expect((north - 47.445) * 111_320).toBeCloseTo(100, 0);
	});

	it('reads the compass on iPhone and Android', () => {
		const ios = {
			webkitCompassHeading: 90,
			alpha: 12,
			absolute: false
		} as unknown as DeviceOrientationEvent;
		expect(compassHeading(ios)).toBe(90);
		const android = { alpha: 270, absolute: true } as unknown as DeviceOrientationEvent;
		expect(compassHeading(android)).toBe(90);
		const relative = { alpha: 270, absolute: false } as unknown as DeviceOrientationEvent;
		expect(compassHeading(relative)).toBeNull();
	});
});
