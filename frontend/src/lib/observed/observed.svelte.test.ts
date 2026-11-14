// The Observed tab: station charts and the scorecard stay inside their plots.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import crystal from '../fixtures/crystal.json';
import whistler from '../fixtures/whistler.json';
import type { Snapshot, VerificationOut } from '../types.gen';
import { expectMarksInside } from '../charts/__tests__/marks';
import StationPanel from './StationPanel.svelte';
import Scorecard from './Scorecard.svelte';

afterEach(cleanup);

const us = crystal as unknown as Snapshot;
const bc = whistler as unknown as Snapshot;

describe('station panel', () => {
	it('charts SNOTEL depth and water', () => {
		const { container, getByText } = render(StationPanel, {
			station: us.snotel ?? null,
			bandLabel: 'Mid',
			bandElev: us.bands[1].elev_m,
			units: 'imperial',
			width: 380
		});
		expect(getByText('Snow depth, 30 days')).toBeTruthy();
		expect(container.textContent).toMatch(/NRCS SNOTEL/);
		expectMarksInside(container);
	});

	it('shows a BC snow pillow', () => {
		const { container } = render(StationPanel, {
			station: bc.snotel ?? null,
			bandLabel: 'Mid',
			bandElev: bc.bands[1].elev_m,
			units: 'metric'
		});
		expect(container.textContent).toMatch(/BC River Forecast Centre/);
		expect(container.textContent).toMatch(/Callaghan Creek/);
	});

	it('says when there is no station', () => {
		const { getByText } = render(StationPanel, {
			station: null,
			bandLabel: 'Mid',
			bandElev: 1500,
			units: 'imperial'
		});
		expect(getByText(/No snow station is set/)).toBeTruthy();
	});
});

const scores = (ready: boolean): VerificationOut => ({
	location_id: 'crystal',
	station: '642:WA:SNTL',
	station_name: 'Morse Lake',
	station_elev_m: 1650,
	band_elev_m: 1800,
	since: '2026-12-01',
	n_days: ready ? 8 : 3,
	ready,
	needs_days: ready ? 0 : 4,
	rows: [
		{ source: 'cons', n: 8, bias_cm: -2.5, mae_cm: 3.5, hits: 2, misses: 1, false_alarms: 0 },
		{ source: 'cons_slr', n: 8, bias_cm: 0.4, mae_cm: 2.1, hits: 3, misses: 0, false_alarms: 1 },
		{ source: 'gfs_seamless', n: 8, bias_cm: 4, mae_cm: 5, hits: 1, misses: 2, false_alarms: 2 }
	],
	pairs: Array.from({ length: 8 }, (_, i) => ({
		date: `2026-12-0${i + 1}`,
		observed_cm: i % 3 ? 4 : 12,
		from_swe: false,
		cons_cm: i % 2 ? 6 : 9,
		cons_slr_cm: 8
	}))
});

describe('scorecard', () => {
	it('waits for a week of forecasts', () => {
		const { getByText } = render(Scorecard, { data: scores(false), units: 'imperial' });
		expect(getByText(/fills in after about a week/)).toBeTruthy();
	});

	it('shows sources and which depth method is closer', () => {
		const { container, getByText } = render(Scorecard, {
			data: scores(true),
			units: 'imperial',
			width: 380
		});
		expect(getByText('Consensus (temperature-based depth)')).toBeTruthy();
		expect(container.textContent).toMatch(/temperature-based depth is closer/);
		expectMarksInside(container);
	});

	it('labels the source the app’s totals use', () => {
		const { getByText, container } = render(Scorecard, {
			data: { ...scores(true), headline: 'cons_slr' },
			units: 'imperial',
			width: 380
		});
		const row = getByText('Consensus (temperature-based depth) · the app’s totals');
		expect(row.closest('tr')?.classList.contains('hl')).toBe(true);
		expect(
			getByText('Consensus (model snowfall, 7:1)').closest('tr')?.classList.contains('hl')
		).toBe(false);
		expect(container.textContent).toMatch(/totals use the\s+temperature-based depth/);
	});
});
