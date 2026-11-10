// The API client against a fake fetch (jsdom, for AbortController and Response).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getHealth, getLocations, waitForJob } from './api';

const json = (status: number, body: unknown) =>
	new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});

afterEach(() => {
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe('api client', () => {
	it('raises ApiError with the server’s detail', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => json(409, { detail: 'a location with id x already exists' }))
		);
		await expect(getLocations()).rejects.toEqual(
			new ApiError(409, 'a location with id x already exists')
		);
	});

	it('falls back to the status text when the body is not JSON', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('<html>', { status: 502, statusText: 'Bad Gateway' }))
		);
		const err = (await getLocations().catch((e) => e)) as ApiError;
		expect(err.status).toBe(502);
		expect(err.message).toBe('Bad Gateway');
	});

	it('treats a 503 from /api/health as an answer, not an error', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => json(503, { status: 'stale', age_s: 50000, last_run: null }))
		);
		expect((await getHealth()).status).toBe('stale');
	});

	it('stops polling a job when the page is left', async () => {
		vi.useFakeTimers();
		const fetch = vi.fn(async () => json(200, { id: 1, status: 'running' }));
		vi.stubGlobal('fetch', fetch);
		const leaving = new AbortController();
		const done = waitForJob(1, undefined, leaving.signal);
		await vi.advanceTimersByTimeAsync(4100);
		leaving.abort();
		await vi.advanceTimersByTimeAsync(10_000);
		const job = await done;
		expect(job.status).toBe('running');
		expect(fetch.mock.calls.length).toBeLessThanOrEqual(4);
	});
});
