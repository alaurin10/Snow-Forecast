// The Confidence tab's pieces, rendered from real snapshots (Whistler: snowy; Crystal: dry).
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import whistler from '../fixtures/whistler.json';
import crystal from '../fixtures/crystal.json';
import type { Snapshot, TrendOut, VerificationOut } from '../types.gen';
import { expectMarksInside } from '../charts/__tests__/marks';
import { dayReads, windowRead } from '../confidence';
import ConfidenceTab from './ConfidenceTab.svelte';
import ConfidenceMeter from './ConfidenceMeter.svelte';
import WindowRange from './WindowRange.svelte';
import ChanceLadder from './ChanceLadder.svelte';
import ModelTable from './ModelTable.svelte';
import TrackRecord from './TrackRecord.svelte';

const snowy = whistler as unknown as Snapshot;
const dry = crystal as unknown as Snapshot;

afterEach(cleanup);

describe('confidence meter', () => {
	it('lights one bar per level and says the word', () => {
		for (const [level, bars, word] of [
			['high', 3, 'High'],
			['medium', 2, 'Medium'],
			['low', 1, 'Low'],
			[null, 0, 'Unknown']
		] as const) {
			const { container } = render(ConfidenceMeter, { level });
			expect(container.querySelectorAll('.bars i.on').length).toBe(bars);
			expect(container.textContent).toMatch(new RegExp(`${word}\\s+confidence`));
			cleanup();
		}
	});
});

describe('window range', () => {
	it('keeps the band, the tick and every model dot on the line', () => {
		for (const width of [320, 520]) {
			const read = windowRead(snowy.bands[1], 'next5');
			const { container } = render(WindowRange, { read, max: read.hi!, units: 'imperial', width });
			expect(container.querySelectorAll('circle.dot').length).toBe(read.models.length);
			expect(container.querySelectorAll('rect.band').length).toBe(1);
			expectMarksInside(container);
			cleanup();
		}
	});
	it('names every number for a screen reader', () => {
		const read = windowRead(snowy.bands[1], 'next5');
		const { getByRole } = render(WindowRange, { read, max: 80, units: 'metric', width: 400 });
		const label = getByRole('img').getAttribute('aria-label') ?? '';
		expect(label).toMatch(/^Next 5 days: \d+ cm, likely \d+ cm to \d+ cm\. /);
		expect(label).toMatch(/GFS \d+ cm/);
	});
});

describe('chance ladder', () => {
	it('gives the share of members at or above each amount', () => {
		const { container } = render(ChanceLadder, {
			next5: [0, 10, 20, 40],
			d6_10: [],
			units: 'metric'
		});
		const rows = [...container.querySelectorAll('tbody tr')].map((tr) =>
			tr.textContent?.replace(/\s+/g, ' ').trim()
		);
		expect(rows).toEqual([
			'2 cm 75%–',
			'5 cm 75%–',
			'15 cm 50%–',
			'30 cm 25%–',
			'45 cm 0%–',
			'60 cm 0%–'
		]);
	});
	it('uses round inches, and says when there is no ensemble', () => {
		const a = render(ChanceLadder, { next5: [30.48], d6_10: [2.54], units: 'imperial' });
		expect(a.container.querySelector('tbody tr:nth-child(4)')?.textContent).toMatch(
			/12 in\s*100%\s*0%/
		);
		cleanup();
		const b = render(ChanceLadder, { next5: [], d6_10: [], units: 'imperial' });
		expect(b.container.textContent).toMatch(/No ensemble data/);
	});
});

describe('model table', () => {
	it('has a row per model, the range above and the median below', () => {
		const days = dayReads(snowy.daily);
		const { container, getByText } = render(ModelTable, {
			days,
			models: snowy.models,
			units: 'imperial'
		});
		expect(container.querySelectorAll('thead th').length).toBe(12); // label, ten days, total
		expect(getByText('Ensembles 10–90%')).toBeTruthy();
		expect(getByText('Models’ median')).toBeTruthy();
		expect(getByText('GFS')).toBeTruthy();
		// A model that stops before day ten has no total.
		const icon = getByText('ICON').closest('tr')!;
		expect(icon.querySelector('td.tot')?.textContent).toBe('–');
		const gfs = getByText('GFS').closest('tr')!;
		expect(gfs.querySelector('td.tot')?.textContent).toMatch(/^\d+\.\d$/);
		expect(gfs.querySelectorAll('.heat').length).toBe(10);
	});
});

const scores: VerificationOut = {
	location_id: 'whistler',
	station: 'x',
	station_name: 'Callaghan Creek',
	station_elev_m: 1040,
	band_elev_m: 1850,
	since: '2026-10-05',
	n_days: 30,
	ready: true,
	needs_days: 0,
	headline: 'cons_slr',
	rows: [
		{ source: 'cons', n: 30, bias_cm: -2.5, mae_cm: 3.5, hits: 2, misses: 1, false_alarms: 0 },
		{ source: 'cons_slr', n: 30, bias_cm: 1.2, mae_cm: 2.1, hits: 3, misses: 0, false_alarms: 1 },
		{
			source: 'ecmwf_ifs025',
			n: 30,
			bias_cm: -0.01,
			mae_cm: 1.6,
			hits: 3,
			misses: 0,
			false_alarms: 0
		},
		{ source: 'gfs_seamless', n: 3, bias_cm: 0, mae_cm: 0.1, hits: 0, misses: 0, false_alarms: 0 }
	],
	pairs: []
};

describe('track record', () => {
	it('sums up the app’s own forecast and names the closest source', () => {
		const { container, getByText } = render(TrackRecord, { data: scores, units: 'metric' });
		expect(container.querySelector('.lede')?.textContent).toBe(
			'Day to day, the app’s forecast misses by 2 cm on average and runs 1 cm high. ECMWF has been closest (2 cm).'
		);
		// GFS has too few days to be called closest, whatever its score.
		expect(container.querySelectorAll('.bar i.best').length).toBe(1);
		expect(getByText('ECMWF').closest('tr')?.querySelector('.best')).toBeTruthy();
		const row = getByText('Consensus (temperature-based depth) · the app’s totals');
		expect(row.closest('tr')?.classList.contains('hl')).toBe(true);
		expect(container.textContent).toMatch(/temperature-based depth is closer/);
	});
	it('never shows a signed zero', () => {
		const { getByText } = render(TrackRecord, { data: scores, units: 'imperial' });
		const cells = [...getByText('ECMWF').closest('tr')!.querySelectorAll('td')];
		expect(cells[1].textContent).toBe('0.0');
	});
	it('waits for a week of forecasts, and says when it cannot load', () => {
		const a = render(TrackRecord, {
			data: { ...scores, ready: false, n_days: 3, needs_days: 4, rows: [] },
			units: 'imperial'
		});
		expect(a.getByText(/fills in after about a week/)).toBeTruthy();
		cleanup();
		const b = render(TrackRecord, { data: null, units: 'imperial', load: 'error' });
		expect(b.getByRole('alert')).toBeTruthy();
	});
});

const trend: TrendOut = {
	location_id: 'whistler',
	runs: [
		{
			run_id: 1,
			issued_at: '2026-11-03T03:30:00+00:00',
			next5_cm: 30,
			daily: { '2026-11-04': 10, '2026-11-05': 20 }
		},
		{
			run_id: 2,
			issued_at: '2026-11-04T21:30:00+00:00',
			next5_cm: 45,
			daily: { '2026-11-04': 15, '2026-11-05': 30 }
		}
	]
};

describe('confidence tab', () => {
	it('renders every section from a snowy snapshot and keeps its charts in bounds', () => {
		const { container, getByRole } = render(ConfidenceTab, {
			snap: snowy,
			band: snowy.bands[1],
			trend,
			scores,
			units: 'imperial',
			width: 380
		});
		for (const title of [
			'How sure is this forecast?',
			'The models, day by day',
			'Chance of at least…',
			'How the forecast has changed',
			'Track record here'
		])
			expect(getByRole('heading', { name: title })).toBeTruthy();
		expect(container.textContent).toMatch(/Medium\s+confidence/);
		expect(container.textContent).toMatch(/Low\s+confidence/);
		expect(container.textContent).toMatch(/Up 5\.9 in since 1 run ago/);
		expectMarksInside(container);
	});

	it('switches the model chart between each day and the running total', async () => {
		const { getByRole, container } = render(ConfidenceTab, {
			snap: snowy,
			band: snowy.bands[1],
			trend: null,
			scores: null,
			units: 'imperial',
			width: 380
		});
		expect(container.textContent).toMatch(/Each day, model by model/);
		await fireEvent.click(getByRole('button', { name: 'Running total' }));
		expect(container.textContent).toMatch(/Do the models agree\?/);
		expect(getByRole('button', { name: 'Running total' }).getAttribute('aria-pressed')).toBe(
			'true'
		);
		expectMarksInside(container);
	});

	it('is sure about a dry forecast, and follows the chosen elevation', () => {
		const { container } = render(ConfidenceTab, {
			snap: dry,
			band: dry.bands[2],
			trend: null,
			scores: null,
			units: 'imperial',
			width: 380
		});
		expect(container.textContent).toMatch(/High\s+confidence/);
		expect(container.textContent).toMatch(/Little or no snow, and the models agree on that/);
		expect(container.textContent).toMatch(new RegExp(`At ${dry.bands[2].label} `));
		expect(container.textContent).toMatch(/estimated from the mid-mountain ensemble/);
	});
});
