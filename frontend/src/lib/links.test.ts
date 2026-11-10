import { describe, expect, it } from 'vitest';
import { safeHref, safeImage } from './links';

describe('safeHref', () => {
	it('keeps http and https links', () => {
		expect(safeHref('https://avalanche.org/x')).toBe('https://avalanche.org/x');
		expect(safeHref('http://example.com')).toBe('http://example.com/');
	});

	it('drops anything else', () => {
		for (const bad of [
			'javascript:alert(1)',
			'JAVASCRIPT:alert(1)',
			'data:text/html,x',
			'/x',
			'',
			null
		])
			expect(safeHref(bad)).toBeUndefined();
	});

	it('only allows https images', () => {
		expect(safeImage('https://cam.example/a.jpg')).toBe('https://cam.example/a.jpg');
		expect(safeImage('http://cam.example/a.jpg')).toBeUndefined();
	});
});
