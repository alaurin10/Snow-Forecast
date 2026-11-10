import { describe, expect, it } from 'vitest';
import { APP_VERSION, outOfDate, shortCommit } from './version';

describe('version', () => {
	it('is the package version, built in', () => {
		expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+/);
	});

	it('notices when the server runs another version', () => {
		expect(outOfDate(APP_VERSION)).toBe(false);
		expect(outOfDate('99.0.0')).toBe(true);
		expect(outOfDate(null)).toBe(false);
	});

	it('shortens commits', () => {
		expect(shortCommit('b89cd7731b53ba51aa00c73bdd9a1868b6dd5def')).toBe('b89cd77');
		expect(shortCommit('')).toBeNull();
	});
});
