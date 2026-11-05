// The review form: when Save is allowed, and what it hands back.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import LocationForm from './LocationForm.svelte';
import type { Location } from '../types.gen';

const loc = (elevs: [number, number, number], id = 'snow-lake'): Location => ({
	id,
	name: 'Snow Lake',
	kind: 'backcountry',
	region: 'Snoqualmie Pass, WA',
	country: 'US',
	tz: 'America/Los_Angeles',
	bands: (['base', 'mid', 'summit'] as const).map((band, i) => ({
		band,
		label: band,
		// Map pins carry many decimals; the form must accept them.
		lat: 47.44531234 + i / 100,
		lon: -121.42361987,
		elev_m: elevs[i]
	})),
	active: true
});

const submit = (c: HTMLElement) => c.querySelector('button[type=submit]') as HTMLButtonElement;

afterEach(cleanup);

describe('LocationForm', () => {
	it('saves a valid location unchanged', async () => {
		const onsave = vi.fn();
		const { container } = render(LocationForm, {
			initial: loc([950, 1200, 1500]),
			isNew: true,
			onsave,
			oncancel: () => {}
		});
		const form = container.querySelector('form') as HTMLFormElement;
		expect(submit(container).disabled).toBe(false);
		// Decimal places finer than any step must not make the form invalid.
		expect(form.checkValidity()).toBe(true);
		await fireEvent.submit(form);
		expect(onsave).toHaveBeenCalledOnce();
		expect(onsave.mock.calls[0][0].bands.map((b: { elev_m: number }) => b.elev_m)).toEqual([
			950, 1200, 1500
		]);
	});

	it('blocks saving when elevations do not rise', () => {
		const { container, getByText } = render(LocationForm, {
			initial: loc([1500, 1200, 950]),
			isNew: true,
			onsave: () => {},
			oncancel: () => {}
		});
		expect(submit(container).disabled).toBe(true);
		expect(getByText('Elevations must rise from base to summit.')).toBeTruthy();
	});

	it('blocks saving with a bad ID, and fixing it re-enables Save', async () => {
		const { container } = render(LocationForm, {
			initial: loc([950, 1200, 1500], 'Snow Lake!'),
			isNew: true,
			onsave: () => {},
			oncancel: () => {}
		});
		expect(submit(container).disabled).toBe(true);
		const idInput = container.querySelectorAll('input')[1] as HTMLInputElement;
		await fireEvent.input(idInput, { target: { value: 'snow-lake' } });
		flushSync();
		expect(submit(container).disabled).toBe(false);
	});
});

describe('LocationForm webcams', () => {
	it('adds a webcam, rejects a bad link and saves a good one', async () => {
		const onsave = vi.fn();
		const { container, getByText } = render(LocationForm, {
			initial: loc([950, 1200, 1500]),
			isNew: true,
			onsave,
			oncancel: () => {}
		});
		await fireEvent.click(getByText('+ Add a webcam'));
		flushSync();
		const cam = container.querySelector('.cam') as HTMLElement;
		const [name, page] = cam.querySelectorAll('input');
		await fireEvent.input(name, { target: { value: 'Summit' } });
		await fireEvent.input(page, { target: { value: 'javascript:alert(1)' } });
		flushSync();
		expect(submit(container).disabled).toBe(true);
		await fireEvent.input(page, { target: { value: 'https://example.com/cam' } });
		flushSync();
		expect(submit(container).disabled).toBe(false);
		await fireEvent.submit(container.querySelector('form') as HTMLFormElement);
		expect(onsave.mock.calls[0][0].webcams).toEqual([
			{ name: 'Summit', url: 'https://example.com/cam', image_url: null }
		]);
	});
});
