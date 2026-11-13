import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import MapPanel from './MapPanel.svelte';
import Inspector from './Inspector.svelte';
import FeatureCard from './FeatureCard.svelte';
import type { PointOut } from '../types.gen';

afterEach(cleanup);

const body = createRawSnippet(() => ({ render: () => '<p>Body</p>' }));

describe('MapPanel', () => {
	it('names what it shows, switches chips in place and closes', async () => {
		const onchip = vi.fn();
		const onclose = vi.fn();
		const { getByRole, getAllByRole } = render(MapPanel, {
			kind: 'Glacier',
			title: 'Snow Glacier',
			chips: ['Glacier', 'Zone', 'This spot'],
			active: 0,
			onchip,
			onclose,
			children: body
		});
		const panel = getByRole('dialog', { name: 'Snow Glacier' });
		expect(panel.textContent).toContain('Body');
		const chips = getAllByRole('button', { pressed: false });
		expect(chips.map((c) => c.textContent)).toEqual(['Zone', 'This spot']);
		expect(getByRole('button', { name: 'Glacier', pressed: true })).toBeTruthy();
		await fireEvent.click(getByRole('button', { name: 'This spot' }));
		expect(onchip).toHaveBeenCalledWith(2);
		await fireEvent.click(getByRole('button', { name: 'Close' }));
		expect(onclose).toHaveBeenCalled();
	});

	it('has no chip row for a single target', () => {
		const { queryByRole } = render(MapPanel, {
			kind: 'Snow station',
			title: 'Olallie Meadows',
			chips: ['Station'],
			onclose: vi.fn(),
			children: body
		});
		expect(queryByRole('group', { name: 'Here' })).toBeNull();
	});
});

describe('Inspector', () => {
	const facts = {
		elevation: 1800,
		slope: 34,
		aspect: 40,
		sea: false,
		srcZ: 14,
		metresPerPixel: 10,
		fallback: false
	};

	it('holds its rows while loading', () => {
		const { container, getByRole } = render(Inspector, {
			lat: 47.4,
			facts: null,
			error: null,
			units: 'metric',
			pointState: 'loading'
		});
		for (const name of ['Terrain', 'Snow and weather'])
			expect(getByRole('region', { name })).toBeTruthy();
		expect(container.querySelectorAll('.skel').length).toBeGreaterThan(6);
		expect(getByRole('table', { name: 'Loading the weather here' })).toBeTruthy();
	});

	it('shows terrain, a snow table and one disclosure for the caveats', () => {
		const now = Math.floor(Date.now() / 1000);
		const point = {
			inside: true,
			lat: 47.4,
			lon: -121.4,
			generated: null,
			min_snow_cm: 0,
			min_wind_kmh: 0,
			depth: { cm: 80, src: {}, t: now },
			gust: [{ t: now, value: 40 }],
			observed: [],
			rates: [],
			ridge: [{ t: now, kmh: 50, dir: 225 }],
			roses: [],
			snow_level: [{ t: now, value: 1200 }],
			totals: [
				{ window: 24, cm: 10 },
				{ window: 72, cm: 25 },
				{ window: 168, cm: 40 }
			]
		} as unknown as PointOut;
		const { getByRole, getByText, container } = render(Inspector, {
			lat: 47.4,
			facts,
			error: null,
			units: 'metric',
			sunState: 'none',
			point,
			pointState: 'ready'
		});
		expect(getByText('1,800 m')).toBeTruthy();
		expect(getByText('NE')).toBeTruthy();
		const table = getByRole('table', { name: 'Forecast snow' });
		expect(table.textContent).toMatch(/Area\s*10 cm\s*25 cm\s*40 cm/);
		expect(getByText('SW 50 km/h')).toBeTruthy();
		expect(container.querySelectorAll('details')).toHaveLength(1);
		expect(getByText('About these numbers')).toBeTruthy();
		expect(container.querySelector('.skel')).toBeNull();
	});
});

describe('FeatureCard', () => {
	it('describes a glacier: its size, top and toe, flow, slope and snow at both ends', () => {
		const now = Math.floor(Date.now() / 1000);
		const point = {
			inside: true,
			elevations: [1000, 2000, 3000],
			snow_level: [{ t: now, value: 2100 }],
			totals: [
				{ window: 24, cm: 5, by_elevation: [0, 10, 20] },
				{ window: 72, cm: 15, by_elevation: [0, 20, 40] },
				{ window: 168, cm: 30, by_elevation: [0, 30, 60] }
			]
		} as unknown as PointOut;
		const { getByText, getByRole } = render(FeatureCard, {
			item: {
				type: 'glacier',
				kind: 'Glacier',
				name: 'Snow Glacier',
				glacierType: 'valley',
				wiki: 'https://en.wikipedia.org/wiki/Snow_Glacier'
			},
			units: 'metric',
			glacier: {
				area: 2_340_000,
				stats: {
					top: 2600,
					toe: 2000,
					topAt: [-121, 48.01],
					toeAt: [-121, 48],
					length: 1500,
					slope: 22,
					steep: 0.12,
					flows: 180
				},
				point,
				pointState: 'ready'
			}
		});
		expect(getByText('Valley glacier')).toBeTruthy();
		expect(getByText('2.3 km²')).toBeTruthy();
		expect(getByText(/2,000 m – 2,600 m/)).toBeTruthy();
		expect(getByText('south')).toBeTruthy();
		expect(getByText(/600 m drop/)).toBeTruthy();
		expect(getByText(/12% over 30°/)).toBeTruthy();
		const table = getByRole('table', { name: 'Forecast snow' });
		expect(table.textContent).toMatch(/Top\s*16 cm\s*32 cm\s*48 cm/);
		expect(table.textContent).toMatch(/Toe\s*10 cm\s*20 cm\s*30 cm/);
		expect(getByText(/rain possible low down/)).toBeTruthy();
		expect(getByRole('link', { name: /Wikipedia/ }).getAttribute('href')).toBe(
			'https://en.wikipedia.org/wiki/Snow_Glacier'
		);
		cleanup();
		const hut = render(FeatureCard, {
			item: {
				type: 'place',
				kind: 'Hut',
				name: 'Hut',
				ele: 1880,
				link: 'https://www.openstreetmap.org/node/1'
			},
			units: 'metric'
		});
		expect(hut.getByText('1,880 m')).toBeTruthy();
		expect(hut.getByRole('link', { name: /OpenStreetMap/ }).getAttribute('href')).toBe(
			'https://www.openstreetmap.org/node/1'
		);
	});

	it('offers a run its profile', async () => {
		const onprofile = vi.fn();
		const { getByRole } = render(FeatureCard, {
			item: {
				type: 'route',
				kind: 'Run',
				name: 'Chute',
				detail: 'advanced',
				line: [
					[-121, 47],
					[-121.01, 47.01]
				],
				link: 'https://www.openstreetmap.org/way/4'
			},
			units: 'metric',
			onprofile
		});
		await fireEvent.click(getByRole('button', { name: /Profile/ }));
		expect(onprofile).toHaveBeenCalled();
		expect(getByRole('link', { name: /OpenStreetMap/ }).getAttribute('href')).toBe(
			'https://www.openstreetmap.org/way/4'
		);
	});
});
