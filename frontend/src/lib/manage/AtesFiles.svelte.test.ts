// The Manage page's ATES files: listed with what they hold, uploaded as the request body.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { tick } from 'svelte';
import AtesFiles from './AtesFiles.svelte';

const json = (status: number, body: unknown) =>
	new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});

async function settle() {
	for (let i = 0; i < 8; i++) {
		await Promise.resolve();
		await tick();
	}
}

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

describe('AtesFiles', () => {
	it('lists the files and uploads a new one', async () => {
		const listing = [
			{
				name: 'rogers.kmz',
				bytes: 52000,
				features: 3,
				ratings: { complex: 2, simple: 1 },
				error: null
			},
			{ name: 'bad.kml', bytes: 10, features: 0, ratings: {}, error: 'not valid KML' }
		];
		const fetch = vi.fn(async (url: string, init?: RequestInit) => {
			if (init?.method === 'PUT') return json(200, listing[0]);
			return json(200, listing);
		});
		vi.stubGlobal('fetch', fetch);
		const { container, getByText } = render(AtesFiles);
		await settle();
		expect(getByText(/3 shapes: 1 simple, 2 complex/)).toBeTruthy();
		expect(getByText('not valid KML')).toBeTruthy();
		const input = container.querySelector<HTMLInputElement>('input[type=file]')!;
		const file = new File(['zip'], 'new area.kmz');
		Object.defineProperty(input, 'files', { value: [file] });
		await fireEvent.change(input);
		await settle();
		const put = fetch.mock.calls.find(([, i]) => i?.method === 'PUT')!;
		expect(put[0]).toBe('/api/admin/overlays/new%20area.kmz');
		expect(put[1]!.body).toBe(file);
	});
});
