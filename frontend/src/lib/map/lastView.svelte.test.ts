// In jsdom (the .svelte.test project) for its sessionStorage.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { lastView, near, saveView } from './lastView';

afterEach(() => {
	sessionStorage.clear();
	vi.restoreAllMocks();
});

const v = { lng: -121.09, lat: 47.74, zoom: 12.5, bearing: 20, pitch: 45 };

describe('the map’s last view', () => {
	it('is kept and read back', () => {
		expect(lastView()).toBeNull();
		saveView(v);
		expect(lastView()).toEqual(v);
	});
	it('ignores junk and blocked storage', () => {
		sessionStorage.setItem('sw.mapView', '{"lng":"x"}');
		expect(lastView()).toBeNull();
		sessionStorage.setItem('sw.mapView', 'nope');
		expect(lastView()).toBeNull();
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new Error('blocked');
		});
		expect(() => saveView(v)).not.toThrow();
	});
	it('knows whether a point is nearby', () => {
		expect(near(v, { lat: 47.8, lon: -121.0 })).toBe(true);
		expect(near(v, { lat: 48.5, lon: -121.0 })).toBe(false);
	});
});
