// Preferences survive reloads, and blocked storage never breaks the app.
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
	localStorage.clear();
	vi.restoreAllMocks();
	vi.resetModules();
});

describe('prefs', () => {
	it('reads saved choices and ignores unknown values', async () => {
		localStorage.setItem('sw.units', 'metric');
		localStorage.setItem('sw.theme', 'neon');
		const { prefs } = await import('./prefs.svelte');
		expect(prefs.units).toBe('metric');
		expect(prefs.theme).toBe('auto');
	});

	it('saves a change', async () => {
		const { prefs } = await import('./prefs.svelte');
		prefs.setBand('summit');
		expect(localStorage.getItem('sw.band')).toBe('summit');
	});

	it('carries the old map settings over', async () => {
		localStorage.setItem('sw.mapPrecip', 'on');
		localStorage.setItem('sw.mapMode', 'totals');
		localStorage.setItem('sw.mapPistes', 'off');
		const { prefs } = await import('./prefs.svelte');
		expect(prefs.mapWeather).toBe('totals');
		expect(prefs.mapFeatures.has('runs')).toBe(false);
		expect(prefs.mapFeatures.has('peaks')).toBe(true);
	});

	it('reads precipitation switched off as no weather layer', async () => {
		localStorage.setItem('sw.mapPrecip', 'off');
		localStorage.setItem('sw.mapMode', 'totals');
		const { prefs } = await import('./prefs.svelte');
		expect(prefs.mapWeather).toBe('off');
	});

	it('saves map features as a list', async () => {
		const { prefs } = await import('./prefs.svelte');
		prefs.setMapFeature('contours', false);
		expect(localStorage.getItem('sw.mapFeatures')).toBe('runs,peaks,places,glaciers');
		expect(prefs.mapFeatures.has('contours')).toBe(false);
	});

	it('opens the map flat every visit, whatever was chosen before', async () => {
		localStorage.setItem('sw.mapTerrain', 'on');
		let { prefs } = await import('./prefs.svelte');
		expect(prefs.mapTerrain).toBe('off');
		prefs.setMapTerrain(true);
		expect(prefs.mapTerrain).toBe('on');
		vi.resetModules();
		({ prefs } = await import('./prefs.svelte'));
		expect(prefs.mapTerrain).toBe('off');
	});

	it('switches features added later on once, then remembers the choice', async () => {
		localStorage.setItem('sw.mapFeatures', 'runs,zones');
		let { prefs } = await import('./prefs.svelte');
		expect([...prefs.mapFeatures]).toEqual(['runs', 'zones', 'places', 'glaciers']);
		prefs.setMapFeature('glaciers', false);
		vi.resetModules();
		({ prefs } = await import('./prefs.svelte'));
		expect(prefs.mapFeatures.has('glaciers')).toBe(false);
		expect(prefs.mapFeatures.has('places')).toBe(true);
	});

	it('keeps working when storage is blocked', async () => {
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new Error('blocked');
		});
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new Error('blocked');
		});
		const { prefs } = await import('./prefs.svelte');
		expect(prefs.units).toBe('imperial');
		expect(() => prefs.setUnits('metric')).not.toThrow();
		expect(prefs.units).toBe('metric');
	});
});
