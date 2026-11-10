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
