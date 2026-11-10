// The Backcountry tab's pieces, rendered from a real backcountry snapshot (Rainy Pass).
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import rainy from '../fixtures/rainy.json';
import type { AvalancheView, Snapshot } from '../types.gen';
import { expectMarksInside } from '../charts/__tests__/marks';
import LoadingRose from './LoadingRose.svelte';
import DangerPyramid from './DangerPyramid.svelte';
import BackcountryTab from './BackcountryTab.svelte';

const tour = rainy as unknown as Snapshot;

afterEach(cleanup);

const view = (status: AvalancheView['status'], levels = true): AvalancheView => ({
	location_id: 'rainy',
	status,
	today_max: status === 'current' ? 3 : null,
	doc: {
		provider: 'nac',
		center: 'Northwest Avalanche Center',
		center_id: 'NWAC',
		zone: 'East Slopes North',
		link: 'https://nwac.us/forecasts/avalanche/east-slopes-north',
		issued_at: '2026-12-01T02:00+00:00',
		expires_at: '2026-12-02T02:00+00:00',
		days: levels
			? [
					{ date: '2026-12-01', alpine: 3, treeline: 2, below: 1 },
					{ date: '2026-12-02', alpine: 2, treeline: 2, below: 1 }
				]
			: [],
		problems: levels
			? [
					{
						name: 'Wind Slab',
						likelihood: 'likely',
						size: '1–2',
						aspects: ['N', 'NE', 'E'],
						elevations: ['alpine']
					}
				]
			: [],
		summary: 'Avoid wind-drifted slopes near ridgelines.',
		off_season: false
	}
});

describe('loading rose', () => {
	it('keeps wedges inside the chart and names the loaded aspects', () => {
		const next = tour.backcountry!.rose[1];
		const { container, getByText } = render(LoadingRose, {
			rose: next,
			title: 'Next 48 h',
			units: 'imperial'
		});
		expect(container.querySelectorAll('path.mark').length).toBeGreaterThan(0);
		expectMarksInside(container);
		expect(getByText(next.label)).toBeTruthy();
	});

	it('draws nothing without snow', () => {
		const calm = { ...tour.backcountry!.rose[0], sectors: Array(8).fill(0) };
		const { container } = render(LoadingRose, { rose: calm, title: 'x', units: 'metric' });
		expect(container.querySelectorAll('path.mark').length).toBe(0);
	});
});

describe('danger pyramid', () => {
	it('shows the published ratings with the number and the word', () => {
		const { container, getByText } = render(DangerPyramid, {
			view: view('current'),
			tz: 'America/Los_Angeles',
			today: '2026-12-01'
		});
		const bars = [...container.querySelectorAll('.bar')].map((b) => b.textContent?.trim());
		expect(bars).toEqual([
			'3 · Considerable',
			'2 · Moderate',
			'1 · Low',
			'2 · Moderate',
			'2 · Moderate',
			'1 · Low'
		]);
		expect(getByText('Today')).toBeTruthy();
		expect(getByText('Wind Slab')).toBeTruthy();
		expect(getByText(/Full forecast at NWAC/)).toBeTruthy();
	});

	it('never shows an expired rating', () => {
		const { container, getAllByText } = render(DangerPyramid, {
			view: view('expired', false),
			tz: 'America/Los_Angeles',
			today: '2026-12-02'
		});
		expect(getAllByText('Expired').length).toBeGreaterThan(0);
		expect(container.textContent).not.toMatch(/Considerable|Moderate/);
	});

	it('says when there is no rating or no zone', () => {
		const a = render(DangerPyramid, {
			view: view('no_rating', false),
			tz: 'UTC',
			today: '2026-11-05'
		});
		expect(a.getAllByText('No rating').length).toBeGreaterThan(0);
		cleanup();
		const b = render(DangerPyramid, { view: null, tz: 'UTC', today: '2026-11-05' });
		expect(b.getByText(/No avalanche forecast zone/)).toBeTruthy();
	});

	it('has a one-line form for the Forecast tab', () => {
		const { container } = render(DangerPyramid, {
			view: view('current'),
			tz: 'America/Los_Angeles',
			today: '2026-12-01',
			compact: true
		});
		expect(container.querySelectorAll('.strip .danger').length).toBe(3);
	});
});

describe('backcountry tab', () => {
	it('renders every section from a real snapshot', () => {
		const { getByRole, container } = render(BackcountryTab, {
			snap: tour,
			avy: null,
			units: 'imperial'
		});
		for (const title of [
			'Avalanche danger',
			'Wind at ridge height',
			'Storm snow and warming',
			'Overnight refreeze',
			'Sky above treeline',
			'Daylight'
		])
			expect(getByRole('heading', { name: title })).toBeTruthy();
		expect(container.textContent).toMatch(/doesn't judge whether a tour is safe/);
		expect(container.querySelectorAll('.rose').length).toBe(2);
	});
});

describe('danger pyramid while loading or after an error', () => {
	it('never reads as "no zone" before the forecast has arrived', () => {
		for (const compact of [false, true]) {
			const loading = render(DangerPyramid, {
				view: null,
				tz: 'America/Los_Angeles',
				today: '2026-11-09',
				compact,
				load: 'loading'
			});
			expect(loading.container.textContent).toMatch(/Loading/);
			expect(loading.container.textContent).not.toMatch(/No zone|No avalanche forecast zone/);
			loading.unmount();
			const failed = render(DangerPyramid, {
				view: null,
				tz: 'America/Los_Angeles',
				today: '2026-11-09',
				compact,
				load: 'error'
			});
			expect(failed.container.textContent).toMatch(/Couldn’t load/);
			expect(failed.container.textContent).not.toMatch(/No zone|No avalanche forecast zone/);
			failed.unmount();
		}
	});
});
