// The Observed tab: the station's charts and the measured-vs-forecast bars stay inside
// their plots; nearby stations and field reports list what the server found.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import crystal from '../fixtures/crystal.json';
import whistler from '../fixtures/whistler.json';
import type { NearbyOut, Snapshot, VerificationOut } from '../types.gen';
import { expectMarksInside } from '../charts/__tests__/marks';
import StationPanel from './StationPanel.svelte';
import MeasuredVsForecast from './MeasuredVsForecast.svelte';
import NearbyStations from './NearbyStations.svelte';
import FieldReports from './FieldReports.svelte';
import ObservedTab from './ObservedTab.svelte';

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
		expect(getByText('New snow each day')).toBeTruthy();
		expect(getByText('Last 7 days')).toBeTruthy();
		expect(container.textContent).toMatch(/NRCS SNOTEL/);
		expectMarksInside(container);
	});

	it('counts new snow as each day’s depth gain, never a loss', () => {
		const station = structuredClone(us.snotel!);
		const depths = [10, 25, 20, 20, 32];
		station.daily = depths.map((d, i) => ({
			date: `2026-11-0${i + 1}`,
			depth_cm: d,
			swe_mm: d * 3,
			temp_c: -2,
			precip_mm: 0
		}));
		const { container } = render(StationPanel, {
			station,
			bandLabel: 'Mid',
			bandElev: 1800,
			units: 'metric',
			width: 380
		});
		// 15 cm, then two days of settling, then 12 cm: two bars, 27 cm in all.
		expect(container.querySelectorAll('path.bar').length).toBe(2);
		expect(container.textContent).toMatch(/27 cm in all/);
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
	headline: 'cons_slr',
	rows: [
		{ source: 'cons', n: 8, bias_cm: -2.5, mae_cm: 3.5, hits: 2, misses: 1, false_alarms: 0 },
		{ source: 'cons_slr', n: 8, bias_cm: 2.4, mae_cm: 2.1, hits: 3, misses: 0, false_alarms: 1 },
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

describe('measured against the forecast', () => {
	it('waits for a week of forecasts', () => {
		const { getByText } = render(MeasuredVsForecast, { data: scores(false), units: 'imperial' });
		expect(getByText(/fills in after about a week/)).toBeTruthy();
	});

	it('draws each day’s pair and says how the forecast leans', () => {
		const { container } = render(MeasuredVsForecast, {
			data: scores(true),
			units: 'metric',
			width: 380
		});
		expect(container.querySelectorAll('path.obs').length).toBe(8);
		expect(container.querySelectorAll('path.fc').length).toBe(8);
		expect(container.textContent).toMatch(
			/missed by 2\s+cm a day on average, with 2 cm a day too much/
		);
		expectMarksInside(container);
	});

	it('shades the days the depth can’t measure and checks the gauge too', () => {
		const data = scores(true);
		data.rows.push({
			source: 'cons_settled',
			n: 6,
			bias_cm: -1,
			mae_cm: 2,
			hits: 1,
			misses: 0,
			false_alarms: 0
		});
		data.water_rows = [
			{ source: 'cons', n: 8, bias_mm: 3, mae_mm: 4, hits: 1, misses: 0, false_alarms: 1 }
		];
		data.n_days = 6;
		data.n_water_days = 8;
		data.skipped_bare = 2;
		data.pairs = data.pairs.map((p, i) => ({
			...p,
			skip: i < 2 ? ('bare' as const) : null,
			cons_settled_cm: 7,
			observed_water_mm: 10,
			cons_water_mm: 12
		}));
		const { container } = render(MeasuredVsForecast, { data, units: 'metric', width: 380 });
		expect(container.querySelectorAll('rect.skip').length).toBe(2);
		// New snow: 6 measured days drawn, 8 forecast; precipitation: 8 and 8.
		expect(container.querySelectorAll('path.obs').length).toBe(6 + 8);
		expect(container.querySelectorAll('path.fc').length).toBe(8 + 8);
		const text = container.textContent?.replace(/\s+/g, ' ');
		expect(text).toMatch(/as settled snow \(8:1\)\. Over 6 days it has missed by 2 cm a day/);
		expect(text).toMatch(
			/Over 8 days it has missed by 4\.0 mm a day on average, with 3\.0 mm a day too much/
		);
		expect(text).toMatch(/2 days \(2 with no snowpack on the ground\) can't be measured/);
		expectMarksInside(container);
	});

	it('checks the gauge alone while there is no snowpack', () => {
		const data = {
			...scores(true),
			n_days: 0,
			n_water_days: 8,
			skipped_bare: 8,
			rows: [],
			water_rows: [
				{ source: 'cons', n: 8, bias_mm: 20, mae_mm: 21, hits: 0, misses: 0, false_alarms: 3 }
			]
		};
		data.pairs = data.pairs.map((p) => ({ ...p, skip: 'bare' as const, observed_water_mm: 5 }));
		const { container } = render(MeasuredVsForecast, { data, units: 'imperial', width: 380 });
		const text = container.textContent?.replace(/\s+/g, ' ');
		expect(text).toMatch(/can’t check the forecast yet/);
		expect(text).toMatch(/0\.83 in a day on average, with 0\.79 in a day too much/);
		expect(container.querySelectorAll('rect.skip').length).toBe(0); // no depth chart
	});

	it('says so while loading, after an error, and without a station', () => {
		const a = render(MeasuredVsForecast, { data: null, units: 'metric', load: 'loading' });
		expect(a.container.textContent).toMatch(/Loading/);
		cleanup();
		const b = render(MeasuredVsForecast, { data: null, units: 'metric', load: 'error' });
		expect(b.getByRole('alert')).toBeTruthy();
		cleanup();
		const c = render(MeasuredVsForecast, { data: null, units: 'metric' });
		expect(c.container.textContent).toMatch(/needs a snow station/);
	});
});

const station = (id: string, name: string, elev: number | null, depth: number, km: number) => ({
	distance_km: km,
	station: {
		id,
		name,
		network: 'snotel' as const,
		lat: 47,
		lon: -121,
		elev_m: elev,
		obs_time: '2026-11-04T20:00+00:00',
		depth_cm: depth,
		change24_cm: depth > 50 ? 8 : -2,
		daily: [],
		url: `https://example.org/${id}`
	}
});

const nearby = (over: Partial<NearbyOut> = {}): NearbyOut => ({
	location_id: 'crystal',
	radius_km: 60,
	stations_at: '2026-11-04T20:00:00+00:00',
	stations: [
		station('642:WA:SNTL', 'Morse Lake', 1650, 80, 3),
		station('1:WA:SNTL', 'High Camp', 2000, 120, 12),
		station('2:WA:SNTL', 'Low Flat', 1000, 20, 30),
		station('3:WA:SNTL', 'Unsurveyed', null, 40, 8)
	],
	reports_at: '2026-11-04T20:00:00+00:00',
	reports_days: 14,
	reports: [],
	...over
});

describe('stations nearby', () => {
	it('lists stations highest first with the location’s elevations between them', () => {
		const { container, getByText, getAllByText } = render(NearbyStations, {
			data: nearby(),
			bands: us.bands,
			own: '642:WA:SNTL',
			units: 'metric'
		});
		const names = [...container.querySelectorAll('tbody th')].map((th) =>
			th.textContent?.replace(/\s+/g, ' ').trim()
		);
		// Crystal: summit 2,095 m, mid 1,800 m, base 1,341 m.
		expect(names).toEqual([
			'Summit',
			'High Camp',
			'Mid-mountain',
			'Morse Lake this location’s',
			'Base',
			'Low Flat',
			'Unsurveyed'
		]);
		expect(getByText('120 cm')).toBeTruthy();
		expect(getAllByText('+8 cm').length).toBe(2); // the two deep stations
		expect(getAllByText('-2 cm').length).toBe(2);
		expect(getByText('Morse Lake').getAttribute('href')).toBe('https://example.org/642:WA:SNTL');
	});

	it('says when none is near, and when the list has not arrived', () => {
		const a = render(NearbyStations, {
			data: nearby({ stations: [] }),
			bands: us.bands,
			units: 'imperial'
		});
		expect(a.container.textContent).toMatch(/No snow station is reporting within 37 mi/);
		cleanup();
		const b = render(NearbyStations, {
			data: nearby({ stations: [], stations_at: null }),
			bands: us.bands,
			units: 'imperial'
		});
		expect(b.container.textContent).toMatch(/next hourly check/);
		cleanup();
		const c = render(NearbyStations, {
			data: null,
			load: 'error',
			bands: us.bands,
			units: 'metric'
		});
		expect(c.getByRole('alert')).toBeTruthy();
	});
});

const report = {
	distance_km: 5,
	report: {
		id: 'a1',
		title: 'Whumpfing at treeline',
		time: '2026-11-03T19:00+00:00',
		region: 'Sea to Sky',
		kinds: ['snowpack', 'quick'],
		images: 2,
		url: 'https://avalanche.ca/mountain-information-network/submissions/a1'
	}
};

describe('field reports', () => {
	it('links each report and names what it holds', () => {
		const { getByText, container } = render(FieldReports, {
			data: nearby({ reports: [report] }),
			units: 'metric'
		});
		expect(getByText('Whumpfing at treeline').getAttribute('href')).toBe(report.report.url);
		expect(container.textContent).toMatch(/5 km away · Sea to Sky · 2 photos/);
		expect(getByText('Snowpack')).toBeTruthy();
		expect(container.textContent).toMatch(/not\s+checked/);
	});

	it('never links anything but http(s)', () => {
		const bad = { ...report, report: { ...report.report, url: 'javascript:alert(1)' } };
		const { container } = render(FieldReports, {
			data: nearby({ reports: [bad] }),
			units: 'metric'
		});
		expect(container.querySelectorAll('a').length).toBe(0);
	});
});

describe('observed tab', () => {
	it('shows field reports in Canada even when there are none, elsewhere only when one is near', () => {
		const canada = render(ObservedTab, {
			snap: bc,
			scores: null,
			nearby: nearby(),
			units: 'metric',
			width: 380
		});
		expect(canada.getByRole('heading', { name: 'Field reports nearby' })).toBeTruthy();
		expect(canada.container.textContent).toMatch(/No reports within 60 km in the last 14 days/);
		cleanup();
		const states = render(ObservedTab, {
			snap: us,
			scores: null,
			nearby: nearby(),
			units: 'metric',
			width: 380
		});
		expect(states.queryByRole('heading', { name: 'Field reports nearby' })).toBeNull();
		for (const title of ['Snow station', 'Measured against the forecast', 'Snow stations nearby'])
			expect(states.getByRole('heading', { name: title })).toBeTruthy();
		cleanup();
		const near = render(ObservedTab, {
			snap: us,
			scores: null,
			nearby: nearby({ reports: [report] }),
			units: 'metric',
			width: 380
		});
		expect(near.getByRole('heading', { name: 'Field reports nearby' })).toBeTruthy();
	});
});
