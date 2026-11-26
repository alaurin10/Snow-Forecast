// The map's field report card: what the observer wrote and their photos, which open the
// full-screen viewer (attached to <body>, out of the map's panel).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import ReportCard from './ReportCard.svelte';
import type { ObsProps } from '../types.gen';

const nav = vi.hoisted(() => ({ state: {} as { photo?: boolean } }));
vi.mock('$app/navigation', () => ({
	pushState: (_url: string, state: { photo?: boolean }) => (nav.state = state)
}));
vi.mock('$app/state', () => ({
	page: {
		get state() {
			return nav.state;
		}
	}
}));

const MEDIA = 'https://avalanche-org-media.s3.us-west-2.amazonaws.com/';
const report = (extra: Partial<ObsProps> = {}): ObsProps => ({
	id: 'nwac-1',
	title: 'South Side',
	time: '2026-11-19T20:00+00:00',
	day: '2026-11-19',
	region: 'Mt Hood',
	kinds: ['snowpack', 'weather'],
	images: 6,
	url: 'https://nwac.us/observations/#/view/observations/1',
	source: 'nwac',
	center: 'NWAC',
	observer: 'forecaster',
	summary: 'Firm crusts below 7,000 ft; soft snow on shaded aspects above.',
	signs: [{ kind: 'cracking', extent: 'isolated' }],
	photos: Array.from({ length: 6 }, (_, i) => ({
		url: `${MEDIA}p${i}-large.jpg`,
		thumb: `${MEDIA}p${i}-medium.jpg`,
		caption: i === 1 ? 'Crust at 6,500 ft' : ''
	})),
	...extra
});

afterEach(() => {
	cleanup();
	nav.state = {};
});

describe('map report card', () => {
	it('shows what the observer wrote and their photos', () => {
		const { getByText, getByRole, container } = render(ReportCard, { report: report() });
		expect(getByText(/Firm crusts below 7,000 ft/)).toBeTruthy();
		expect(getByRole('list', { name: 'Signs of instability reported' }).textContent).toContain(
			'Shooting cracks · isolated'
		);
		expect(container.querySelectorAll('.thumbs a')).toHaveLength(4);
		expect(getByText('+3')).toBeTruthy();
		expect(getByRole('link', { name: 'Read it on nwac.us →' })).toBeTruthy();
		// The photo count isn't repeated in words when the photos are right there.
		expect(container.textContent).not.toContain('6 photos.');
	});

	it('opens the photos full screen, on top of the page', () => {
		const { container } = render(ReportCard, { report: report(), units: 'metric' });
		const second = container.querySelectorAll('.thumbs a')[1] as HTMLAnchorElement;
		const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
		second.dispatchEvent(click);
		flushSync();
		expect(click.defaultPrevented).toBe(true);
		const dialog = document.querySelector('[role="dialog"][aria-label="Field photos"]');
		expect(dialog).not.toBeNull();
		// Attached to <body>, outside the card, so the map's panel can't trap it.
		expect(container.contains(dialog)).toBe(false);
		expect(dialog?.textContent).toContain('2 of 6');
		expect(dialog?.textContent).toContain('Crust at 6,500 ft');
		expect(dialog?.textContent).toContain('NWAC forecaster · Thu Nov 19 · Mt Hood');
		expect(dialog?.textContent).not.toContain('NaN');
	});

	it('keeps to the basics for a report without words or photos', () => {
		const { container, getByText } = render(ReportCard, {
			report: report({ summary: null, signs: [], photos: [], images: 2, source: 'min' })
		});
		expect(container.querySelector('.thumbs')).toBeNull();
		expect(container.querySelector('.words')).toBeNull();
		expect(getByText(/2 photos\./)).toBeTruthy();
	});
});
