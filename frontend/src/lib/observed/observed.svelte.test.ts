// The Observed tab: the hero's sentence and numbers, the station's charts and the
// measured-vs-forecast bars stay inside their plots; snow by elevation and field reports
// show what the server found.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import crystal from '../fixtures/crystal.json';
import whistler from '../fixtures/whistler.json';
import type { NearbyOut, Snapshot, Snotel, VerificationOut } from '../types.gen';
import { expectMarksInside } from '../charts/__tests__/marks';
import { stationRead } from './read';
import StationHero from './StationHero.svelte';
import SnowpackDetail from './SnowpackDetail.svelte';
import ForecastVerdict from './ForecastVerdict.svelte';
import MeasuredVsForecast from './MeasuredVsForecast.svelte';
import NearbyStations from './NearbyStations.svelte';
import FieldReports from './FieldReports.svelte';
import ObservedTab from './ObservedTab.svelte';

afterEach(cleanup);

const us = crystal as unknown as Snapshot;
const bc = whistler as unknown as Snapshot;

const hero = (station: Snotel, units: 'metric' | 'imperial' = 'metric') =>
	render(StationHero, {
		station,
		read: stationRead(station, units),
		bandLabel: 'Mid-mountain',
		bandElev: 1800,
		today: station.daily.at(-1)?.date,
		units
	});

describe('station hero', () => {
	it('sums the station up in a sentence, three numbers and seven days', () => {
		const { container, getByRole } = hero(us.snotel!, 'imperial');
		expect(getByRole('heading', { level: 2 }).textContent).toMatch(/\.$/);
		expect(container.textContent).toMatch(/NRCS SNOTEL/);
		expect(container.textContent).toMatch(/Morse Lake/);
		expect(container.textContent).toMatch(/below Mid-mountain/);
		expect(container.querySelectorAll('.week li').length).toBe(7);
		expect(container.querySelector('.week li:last-child .wd')?.textContent).toBe('Today');
		expect(container.querySelector('svg.spark')).toBeTruthy();
	});

	it('tints a snowy day like the calendar and shows each day’s high and low', () => {
		const station = structuredClone(us.snotel!);
		station.daily = [10, 10, 10, 10, 10, 10, 30, 30].map((d, i) => ({
			date: `2026-11-0${i + 1}`,
			depth_cm: d,
			swe_mm: d * 3,
			temp_c: -2,
			precip_mm: 0,
			tmin_c: -9,
			tmax_c: i === 7 ? 3 : -1
		}));
		station.depth_cm = 30;
		const { container } = hero(station);
		const cells = [...container.querySelectorAll('.week li')];
		expect(cells[4].className).toMatch(/c4/); // 20 cm on Nov 6: the 6–12 in step
		expect(cells[4].querySelector('.amt')?.textContent).toBe('20');
		expect(cells[6].querySelector('.temps')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
			'3° -9°'
		);
		expect(container.textContent).toMatch(/Above freezing on 1 of the last 7 days/);
	});

	it('shows a BC snow pillow', () => {
		const { container } = hero(bc.snotel!);
		expect(container.textContent).toMatch(/BC River Forecast Centre/);
		expect(container.textContent).toMatch(/Callaghan Creek/);
	});
});

describe('the last 30 days', () => {
	it('charts depth, new snow and temperature on one time axis, and switches to snow water', async () => {
		const station = structuredClone(us.snotel!);
		station.daily = station.daily.map((d) => ({ ...d, tmin_c: -6, tmax_c: 1 }));
		const { container, getByText, getByRole } = render(SnowpackDetail, {
			read: stationRead(station, 'imperial'),
			units: 'imperial',
			width: 380
		});
		expect(getByText('Snow depth')).toBeTruthy();
		expect(getByText('New snow each day')).toBeTruthy();
		expect(getByText('Low and high temperature')).toBeTruthy();
		expect(container.querySelectorAll('rect.day').length).toBe(30);
		expectMarksInside(container);
		await fireEvent.click(getByRole('button', { name: 'Snow water' }));
		expect(getByText('Snow water', { selector: '.title' })).toBeTruthy();
		expect(container.textContent).not.toMatch(/Snow depth/);
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
		station.depth_cm = 30; // settled a little since this morning
		const { container } = render(SnowpackDetail, {
			read: stationRead(station, 'metric'),
			units: 'metric',
			width: 380
		});
		// 15 cm, then two days of settling, then 12 cm: two bars, 27 cm in all.
		expect(container.querySelectorAll('path.bar').length).toBe(2);
		expect(container.textContent).toMatch(/27 cm in all/);
		// No temperatures reported: no temperature chart.
		expect(container.textContent).not.toMatch(/Low and high temperature/);
		expectMarksInside(container);
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

describe('did the forecast get it right?', () => {
	it('puts the two totals side by side and says which way it leans', () => {
		const { container, getByText } = render(ForecastVerdict, {
			data: scores(true),
			units: 'metric'
		});
		const vals = [...container.querySelectorAll('.val')].map((v) => v.textContent);
		// 8 days: forecast 8 cm (temperature-based) each, measured 12, 4, 4, 12, 4, 4, 12, 4.
		expect(vals).toEqual(['64 cm', '56 cm']);
		expect(getByText('Ran high')).toBeTruthy();
		expect(container.textContent).toMatch(/by about 2 cm a day; a typical day was off by 2 cm/);
	});

	it('waits for a week, and says so while loading, after an error and without a station', () => {
		const a = render(ForecastVerdict, { data: scores(false), units: 'metric' });
		expect(a.container.textContent).toMatch(/fills in after about a week/);
		cleanup();
		const b = render(ForecastVerdict, { data: null, units: 'metric', load: 'loading' });
		expect(b.container.textContent).toMatch(/Loading/);
		cleanup();
		const c = render(ForecastVerdict, { data: null, units: 'metric', load: 'error' });
		expect(c.getByRole('alert')).toBeTruthy();
		cleanup();
		const d = render(ForecastVerdict, { data: null, units: 'metric' });
		expect(d.container.textContent).toMatch(/needs a snow station/);
	});
});

const stat = (container: HTMLElement, label: string) =>
	[...container.querySelectorAll('.stats > div')]
		.find((d) => d.querySelector('.eyebrow')?.textContent === label)
		?.querySelector('.stat')
		?.textContent?.replace(/\s+/g, ' ');

describe('forecast check, day by day', () => {
	it('waits for a week of forecasts', () => {
		const { getByText } = render(MeasuredVsForecast, { data: scores(false), units: 'imperial' });
		expect(getByText(/fills in after about a week/)).toBeTruthy();
	});

	it('draws each day’s pair and sums it up in three numbers', () => {
		const { container } = render(MeasuredVsForecast, {
			data: scores(true),
			units: 'metric',
			width: 380
		});
		expect(container.querySelectorAll('path.obs').length).toBe(8);
		expect(container.querySelectorAll('path.fc').length).toBe(8);
		expect(stat(container, 'Typical miss')).toBe('2cm/day');
		expect(stat(container, 'Lean')).toBe('+2cm/day');
		expect(stat(container, 'Days scored')).toBe('8');
		expectMarksInside(container);
	});

	it('shades the days the depth can’t measure and checks the gauge on the other view', async () => {
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
		const { container, getByRole } = render(MeasuredVsForecast, {
			data,
			units: 'metric',
			width: 380
		});
		expect(container.querySelectorAll('rect.skip').length).toBe(2);
		// New snow: 6 measured days drawn, 8 forecast.
		expect(container.querySelectorAll('path.obs').length).toBe(6);
		expect(container.querySelectorAll('path.fc').length).toBe(8);
		let text = container.textContent?.replace(/\s+/g, ' ');
		expect(text).toMatch(/as settled snow \(8:1\)/);
		expect(stat(container, 'Lean')).toBe('−1cm/day');
		expect(stat(container, 'Days scored')).toBe('6');
		expect(text).toMatch(/2 days \(2 with no snowpack on the ground\) can't be measured/);
		expectMarksInside(container);
		await fireEvent.click(getByRole('button', { name: 'Precipitation' }));
		expect(container.querySelectorAll('path.obs').length).toBe(8);
		expect(stat(container, 'Typical miss')).toBe('4.0mm/day');
		expect(stat(container, 'Lean')).toBe('+3.0mm/day');
		text = container.textContent?.replace(/\s+/g, ' ');
		expect(text).toMatch(/Rain and melted snow in the station’s gauge/);
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
		const { container, queryByRole } = render(MeasuredVsForecast, {
			data,
			units: 'imperial',
			width: 380
		});
		expect(queryByRole('button', { name: 'New snow' })).toBeNull();
		expect(stat(container, 'Typical miss')).toBe('0.83in/day');
		expect(stat(container, 'Lean')).toBe('+0.79in/day');
		expect(container.querySelectorAll('rect.skip').length).toBe(0); // no depth chart
	});

	it('leads with the forecast at the station once it has a week of days', () => {
		const withStation = (n: number) => {
			const data = scores(true);
			data.rows.push(
				{
					source: 'cons_settled',
					n: 8,
					bias_cm: 5,
					mae_cm: 6,
					hits: 0,
					misses: 0,
					false_alarms: 0
				},
				{ source: 'stn_settled', n, bias_cm: 0, mae_cm: 1, hits: 0, misses: 0, false_alarms: 0 }
			);
			data.water_rows = [
				{ source: 'cons', n: 8, bias_mm: 6, mae_mm: 7, hits: 0, misses: 0, false_alarms: 0 },
				{ source: 'stn_cons', n, bias_mm: 0.2, mae_mm: 2, hits: 0, misses: 0, false_alarms: 0 }
			];
			data.pairs = data.pairs.map((p) => ({
				...p,
				cons_settled_cm: 20,
				stn_settled_cm: 5,
				observed_water_mm: 10,
				cons_water_mm: 30,
				stn_water_mm: 12
			}));
			return data;
		};
		const tallest = (container: HTMLElement) =>
			Math.max(...[...container.querySelectorAll('.tick')].map((t) => Number(t.textContent) || 0));
		// Six days at the station: not yet; the mid band's 20 cm sets the scale.
		const a = render(MeasuredVsForecast, { data: withStation(6), units: 'metric', width: 380 });
		let text = a.container.textContent?.replace(/\s+/g, ' ');
		expect(text).toMatch(/forecast for mid-mountain, as settled snow \(8:1\)/);
		expect(stat(a.container, 'Typical miss')).toBe('6cm/day');
		expect(tallest(a.container)).toBeGreaterThanOrEqual(20);
		cleanup();
		// A week: the forecast for the station's own elevation.
		const b = render(MeasuredVsForecast, { data: withStation(7), units: 'metric', width: 380 });
		text = b.container.textContent?.replace(/\s+/g, ' ');
		expect(text).toMatch(
			/forecast for the station’s own elevation \(1,650 m\), as settled snow \(8:1\)/
		);
		expect(stat(b.container, 'Typical miss')).toBe('1cm/day');
		expect(stat(b.container, 'Lean')).toBe('None');
		expect(tallest(b.container)).toBeLessThan(20);
		expectMarksInside(b.container);
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

describe('snow by elevation', () => {
	it('plots each station by its height and depth, with the location’s elevations across', () => {
		const { container, getByText } = render(NearbyStations, {
			data: nearby(),
			bands: us.bands,
			own: '642:WA:SNTL',
			units: 'metric',
			width: 380
		});
		// Three stations with a height; the unsurveyed one is only in the table.
		expect(container.querySelectorAll('circle.dot').length).toBe(3);
		expect(container.querySelectorAll('circle.dot.own').length).toBe(1);
		expect(container.querySelectorAll('line.band').length).toBe(3);
		expect(container.textContent).toMatch(/Morse Lake: 80 cm at 1,650 m/);
		expectMarksInside(container);
		// Every station in the table, highest first.
		const names = [...container.querySelectorAll('tbody th')].map((th) =>
			th.textContent?.replace(/\s+/g, ' ').trim()
		);
		expect(names).toEqual(['High Camp', 'Morse Lake this location’s', 'Low Flat', 'Unsurveyed']);
		expect(getByText('All 4 stations')).toBeTruthy();
		expect(container.querySelector('details.list')?.hasAttribute('open')).toBe(false);
		expect(getByText('Morse Lake', { selector: 'a' }).getAttribute('href')).toBe(
			'https://example.org/642:WA:SNTL'
		);
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
	it('leads with the simple answers, then the detail', () => {
		const { container, getByRole } = render(ObservedTab, {
			snap: us,
			scores: scores(true),
			nearby: nearby(),
			units: 'metric',
			width: 380
		});
		const headings = [...container.querySelectorAll('h2')].map((h) => h.textContent?.trim());
		expect(headings.slice(1)).toEqual([
			'Did the forecast get it right?',
			'In detail',
			'The last 30 days',
			'Forecast check, day by day',
			'Snow by elevation'
		]);
		expect(getByRole('heading', { name: /^.+\.$/ })).toBeTruthy(); // the hero's sentence
	});

	it('opens on the stations nearby when the location has no station', () => {
		const { container, getByRole, queryByRole } = render(ObservedTab, {
			snap: { ...us, snotel: null },
			scores: null,
			nearby: nearby(),
			units: 'metric',
			width: 380
		});
		expect(container.textContent).toMatch(/No snow station is set/);
		expect(getByRole('heading', { name: 'Snow by elevation' })).toBeTruthy();
		expect(queryByRole('heading', { name: 'Did the forecast get it right?' })).toBeNull();
	});

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
