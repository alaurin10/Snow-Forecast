import { describe, expect, it } from 'vitest';
import { pullCloses } from './swipeclose';

describe('pullCloses', () => {
	it('puts the sheet away after a long enough pull', () => {
		expect(pullCloses(80, 1000, 600)).toBe(true);
		expect(pullCloses(40, 1000, 600)).toBe(false);
	});
	it('needs less on a short sheet', () => {
		expect(pullCloses(40, 1000, 100)).toBe(true);
	});
	it('closes on a quick flick, not a twitch', () => {
		expect(pullCloses(30, 40, 600)).toBe(true);
		expect(pullCloses(10, 5, 600)).toBe(false);
	});
	it('never closes on an upward pull', () => {
		expect(pullCloses(-200, 50, 600)).toBe(false);
	});
});
