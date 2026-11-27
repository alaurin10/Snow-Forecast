// The API client against a fake fetch (jsdom, for AbortController and Response).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getHealth, getLocations, getSpot, startSpot, waitForJob } from './api';

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

describe('spots started early', () => {
	it('the button waits for the one the map started, instead of asking again', async () => {
		const fetch = vi.fn(async (url: string) => json(200, { location: { id: 'spot-a' }, url }));
		vi.stubGlobal('fetch', fetch);
		startSpot(47.0001, -121.0001);
		const snap = await getSpot(47.0, -121.0);
		expect(snap).toMatchObject({ location: { id: 'spot-a' } });
		expect(fetch).toHaveBeenCalledTimes(1);
		expect(String(fetch.mock.calls[0][0])).toBe('/api/spot?lat=47.000&lon=-121.000&early=1');
		startSpot(47.0, -121.0); // already have it: nothing asked
		expect(fetch).toHaveBeenCalledTimes(1);
	});

	it('asks properly when the server skipped the early one', async () => {
		const fetch = vi.fn(async (url: string) =>
			url.includes('early=1')
				? new Response(null, { status: 204 })
				: json(200, { location: { id: 'spot-b' } })
		);
		vi.stubGlobal('fetch', fetch);
		startSpot(48.0, -121.0);
		const snap = await getSpot(48.0, -121.0);
		expect(snap).toMatchObject({ location: { id: 'spot-b' } });
		expect(fetch.mock.calls.map((c) => String(c[0]))).toEqual([
			'/api/spot?lat=48.000&lon=-121.000&early=1',
			'/api/spot?lat=48.000&lon=-121.000'
		]);
	});
});
