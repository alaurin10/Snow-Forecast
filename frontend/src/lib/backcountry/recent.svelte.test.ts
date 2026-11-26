// The Backcountry tab's recent observations: near the location first, the rest of its
// zone folded; what each observer reported; photos open the full-screen viewer.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import RecentObservations from './RecentObservations.svelte';
import type { NearbyOut, NearbyReport } from '../types.gen';

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
const LONG = 'Thin cover below 5,000 feet but better up high. '.repeat(8).trim();

function obs(id: string, group: 'near' | 'zone', photos = 0, extra = {}): NearbyReport {
	return {
		distance_km: group === 'near' ? 3 : 24,
		group,
		report: {
			id,
			title: id,
			time: '2026-11-24T20:00+00:00',
			day: '2026-11-24',
			region: 'West Slopes South',
			kinds: ['snowpack'],
			images: photos,
			url: `https://nwac.us/observations/#/view/observations/${id}`,
			source: 'nwac',
			center: 'NWAC',
			observer: 'public',
			photos: Array.from({ length: photos }, (_, i) => ({
				url: `${MEDIA}${id}-${i}-large.jpg`,
				thumb: `${MEDIA}${id}-${i}-medium.jpg`,
				caption: ''
			})),
			...extra
		}
	};
}

const data = (area: NearbyReport[]): NearbyOut => ({
	location_id: 'crystal',
	radius_km: 60,
	stations_at: null,
	stations: [],
	reports_at: '2026-11-25T18:00:00+00:00',
	reports_days: 14,
	reports: [],
	photo_reports: [],
	area_reports: area,
	near_km: 20,
	zone_name: 'West Slopes South'
});

const NWAC = { name: 'NWAC', url: 'https://nwac.us/observations#/view/observations', shown: true };

afterEach(() => {
	cleanup();
	nav.state = {};
});

describe('recent observations', () => {
	it('lists what people reported near the location, then the rest of the zone folded', async () => {
		const { container, getByText, getByRole, queryByText } = render(RecentObservations, {
			data: data([
				obs('Silver Basin', 'near', 6, {
					summary: LONG + '\n\nSecond paragraph.',
					signs: [{ kind: 'avalanches_observed' }, { kind: 'cracking', extent: 'specific' }],
					instability_note: 'Shooting cracks on test slopes.'
				}),
				obs('Pan Point', 'zone')
			]),
			units: 'imperial',
			tz: 'America/Los_Angeles',
			name: 'Crystal Mountain',
			center: NWAC
		});
		expect(getByRole('heading', { name: 'Recent observations' })).toBeTruthy();
		expect(getByRole('heading', { name: 'Near Crystal Mountain' })).toBeTruthy();
		expect(getByText('Tue Nov 24 · NWAC · public · 2 mi away · West Slopes South')).toBeTruthy();
		const signs = getByRole('list', { name: 'Signs of instability reported' });
		expect([...signs.querySelectorAll('li')].map((li) => li.textContent)).toEqual([
			'Avalanches seen',
			'Shooting cracks · specific'
		]);
		// The summary's first lines, then More for the rest (and the notes).
		const text = container.querySelector('.text') as HTMLElement;
		expect(text.classList.contains('shut')).toBe(true);
		expect(text.textContent).toContain('Instability: Shooting cracks on test slopes.');
		await fireEvent.click(getByRole('button', { name: 'More' }));
		expect(text.classList.contains('shut')).toBe(false);
		expect(getByRole('button', { name: 'Less' }).getAttribute('aria-expanded')).toBe('true');
		// Four small photos, the last one saying how many there are.
		expect(container.querySelectorAll('.thumbs a')).toHaveLength(4);
		expect(getByText('+3')).toBeTruthy();
		// Pan Point is in the zone, farther away: folded.
		const more = container.querySelector('details.zone') as HTMLDetailsElement;
		expect(more.open).toBe(false);
		expect(more.textContent).toContain('More in West Slopes South');
		expect(more.textContent).toContain('Pan Point');
		expect(getByRole('link', { name: 'All NWAC observations ↗' })).toBeTruthy();
		expect(queryByText(/No observations within/)).toBeNull();
	});

	it('opens the photos full screen, the photos alone', () => {
		const { container, getByRole } = render(RecentObservations, {
			data: data([
				obs('Austin Pass', 'near', 2, {
					summary: 'Wet then dry avalanche problems.',
					signs: [{ kind: 'collapsing', extent: 'widespread' }]
				})
			]),
			units: 'metric',
			name: 'Mt. Baker'
		});
		const second = container.querySelectorAll('.thumbs a')[1] as HTMLAnchorElement;
		const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
		second.dispatchEvent(click);
		flushSync();
		expect(click.defaultPrevented).toBe(true);
		const dialog = getByRole('dialog', { name: 'Field photos' });
		expect(dialog.textContent).toContain('2 of 2');
		expect(dialog.textContent).toContain('Austin Pass');
		// What the observer wrote stays on the tab; the viewer keeps to the photos.
		expect(dialog.textContent).not.toContain('Wet then dry avalanche problems.');
		expect(dialog.textContent).not.toContain('Collapsing');
		expect(dialog.querySelector('img')?.getAttribute('src')).toBe(
			`${MEDIA}Austin%20Pass-1-large.jpg`
		);
	});

	it('says when nothing is near, and opens the zone', () => {
		const { container, getByText } = render(RecentObservations, {
			data: data([obs('Pan Point', 'zone')]),
			units: 'imperial',
			name: 'Crystal Mountain'
		});
		expect(getByText(/No observations within 12 mi of Crystal Mountain/)).toBeTruthy();
		expect((container.querySelector('details.zone') as HTMLDetailsElement).open).toBe(true);
	});

	it('shows nothing where there are no reports and no center to read', () => {
		const { container } = render(RecentObservations, {
			data: data([]),
			units: 'imperial'
		});
		expect(container.querySelector('.recent')).toBeNull();
	});

	it('colours the signs as NWAC does: red for avalanches, orange for cracking', () => {
		const { getByRole } = render(RecentObservations, {
			data: data([
				obs('Austin Pass', 'near', 0, {
					signs: [{ kind: 'avalanches_triggered' }, { kind: 'collapsing', extent: 'isolated' }]
				})
			]),
			units: 'imperial'
		});
		const [avy, crack] = getByRole('list', { name: 'Signs of instability reported' }).children;
		expect(avy.className).toContain('avy');
		expect(crack.className).toContain('crack');
	});

	it('still lists the photo reports from data cached before the full list existed', () => {
		const stale = data([]);
		delete stale.area_reports;
		stale.photo_reports = [obs('Silver Basin', 'near', 2)];
		const { getByText } = render(RecentObservations, {
			data: stale,
			units: 'imperial',
			name: 'Crystal Mountain'
		});
		expect(getByText('Silver Basin')).toBeTruthy();
	});
});
