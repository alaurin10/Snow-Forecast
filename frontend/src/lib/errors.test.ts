import { describe, expect, it } from 'vitest';
import { ApiError } from './api';
import { friendlyError } from './errors';

describe('friendlyError', () => {
	it('words network and server failures for people', () => {
		expect(friendlyError(new TypeError('Failed to fetch'))).toContain('connection');
		expect(friendlyError(new ApiError(502, 'Bad Gateway'))).toContain('server had a problem');
		expect(friendlyError(new ApiError(503, 'offline'))).toContain('offline');
		expect(friendlyError(new ApiError(429, 'too many'))).toContain('Wait a minute');
	});

	it('keeps the server’s own explanation for other errors', () => {
		expect(friendlyError(new ApiError(409, 'a location with id x already exists'))).toBe(
			'a location with id x already exists'
		);
	});
});
