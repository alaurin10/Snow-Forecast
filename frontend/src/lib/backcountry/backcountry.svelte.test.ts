// The Backcountry tab's pieces, rendered from a real backcountry snapshot (Rainy Pass).
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import rainy from '../fixtures/rainy.json';
import type { AvalancheView, Snapshot } from '../types.gen';
import { expectMarksInside } from '../charts/__tests__/marks';
import LoadingRose from './LoadingRose.svelte';
import DangerPyramid from './DangerPyramid.svelte';
import BackcountryTab from './BackcountryTab.svelte';
import Outlook from './Outlook.svelte';
import ProblemRose from './ProblemRose.svelte';
import TouringTable from './TouringTable.svelte';

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
			'Avalanche weather, day by day',
			'Where the wind is putting snow',
			'Touring weather'
		])
			expect(getByRole('heading', { name: title })).toBeTruthy();
		expect(container.textContent).toMatch(/doesn't judge whether a tour is safe/);
		expect(container.querySelectorAll('.rose').length).toBe(2);
	});
});

describe('problem rose', () => {
	it('fills only the listed aspects and elevations', () => {
		const { container, getByRole } = render(ProblemRose, {
			aspects: ['N', 'NE'],
			elevations: ['alpine', 'treeline']
		});
		expect(container.querySelectorAll('path').length).toBe(24);
		expect(container.querySelectorAll('path.on').length).toBe(4);
		expect(getByRole('img').getAttribute('aria-label')).toBe('N, NE aspects; alpine, treeline');
	});
	it('takes aspects with no elevations as every elevation', () => {
		const { container } = render(ProblemRose, { aspects: ['S'], elevations: [] });
		expect(container.querySelectorAll('path.on').length).toBe(3);
	});
	it('is drawn beside a problem in the bulletin', () => {
		const { container } = render(DangerPyramid, {
			view: view('current'),
			tz: 'America/Los_Angeles',
			today: '2026-12-01'
		});
		expect(container.querySelectorAll('.problems svg.prose').length).toBe(1);
	});
});

describe('outlook', () => {
	const days = tour.backcountry!.outlook!;
	const today = tour.now.slice(0, 10);
	const steps = {
		snow_cm: [10, 25, 40],
		storm_cm: [30, 50, 80],
		wind_kmh: [25, 40, 60],
		rain_mm: [1, 6, 20],
		rise_c: [5, 8, 12],
		thaw_h: [3, 8]
	};

	it('gives every day a tile with its grade and a line per factor that pushes', () => {
		const { container, getByText } = render(Outlook, { days, avy: null, today, units: 'imperial' });
		const tiles = container.querySelectorAll('li.day');
		expect(tiles.length).toBe(days.length);
		tiles.forEach((tile, i) => {
			const d = days[i];
			expect(tile.querySelector('.chip')?.classList.contains(`s${d.stress}`)).toBe(true);
			const active = Object.values(d.levels).filter((v) => v > 0).length;
			expect(tile.querySelectorAll('.fact').length).toBe(active);
			if (!active) expect(tile.textContent).toMatch(/Calm/);
			// Each factor's own level, as a meter.
			tile.querySelectorAll('.fact').forEach((f) => {
				expect(f.querySelectorAll('.meter i').length).toBe(3);
			});
		});
		expect(getByText('Today')).toBeTruthy();
	});

	it('explains its levels in a key under the days', () => {
		const { container } = render(Outlook, { days, avy: null, today, units: 'imperial', steps });
		const key = container.querySelector('.key')!;
		expect(key.compareDocumentPosition(container.querySelector('.days')!)).toBe(
			Node.DOCUMENT_POSITION_PRECEDING
		);
		expect(key.textContent).toMatch(/It isn't a danger rating/);
		expect(key.textContent).toMatch(/buried weak\s+layers/);
		expect(key.querySelectorAll('.scale .word').length).toBe(4);
		const rows = key.querySelectorAll('.thr tbody tr');
		expect(rows.length).toBe(4);
		expect(rows[0].textContent).toMatch(/4 in in a day, or 12 in over 3 days/);
	});

	it('leaves out the numbers when the snapshot has none', () => {
		const { container } = render(Outlook, { days, avy: null, today, units: 'imperial' });
		expect(container.querySelector('.thr')).toBeNull();
		expect(container.querySelectorAll('.scale .word').length).toBe(4);
	});

	it('shows the published rating only on the days the bulletin covers', () => {
		const v = view('current');
		v.doc!.days = [{ date: today, alpine: 3, treeline: 2, below: 1 }];
		const { container } = render(Outlook, { days, avy: v, today, units: 'imperial' });
		const tiles = [...container.querySelectorAll('li.day')];
		expect(tiles[0].querySelector('.danger')?.textContent).toMatch(/3 · Considerable/);
		for (const t of tiles.slice(1)) expect(t.querySelector('.danger')).toBeNull();
		expect(container.querySelector('.key')?.textContent).toMatch(/own danger rating/);
	});

	it('never shows an expired rating', () => {
		const { container } = render(Outlook, {
			days,
			avy: view('expired', false),
			today,
			units: 'imperial'
		});
		expect(container.querySelectorAll('.danger').length).toBe(0);
	});

	it('never borrows the danger scale for its own grade', () => {
		const { container } = render(Outlook, { days, avy: null, today, units: 'imperial' });
		for (const el of container.querySelectorAll('.chip'))
			expect(el.textContent).not.toMatch(/Low|Moderate|Considerable|High|Extreme/);
		expect(container.querySelectorAll('.chip.danger').length).toBe(0);
	});

	it('shows only the facts, all four every day, when the server has its estimates off', () => {
		const { container } = render(Outlook, {
			days,
			avy: null,
			today,
			units: 'imperial',
			graded: false,
			steps
		});
		expect(container.querySelectorAll('.chip').length).toBe(0);
		expect(container.querySelectorAll('.meter').length).toBe(0);
		expect(container.querySelector('.lede')).toBeNull();
		expect(container.querySelector('.thr')).toBeNull();
		expect(container.textContent).not.toMatch(/Weather loading/i);
		expect(container.querySelectorAll('li.day .fact').length).toBe(days.length * 4);
	});

	it('waits for a run when the snapshot has no outlook yet', () => {
		const { container } = render(Outlook, { days: [], avy: null, today, units: 'imperial' });
		expect(container.textContent).toMatch(/arrives with the next forecast run/);
	});
});

describe('touring weather', () => {
	it('has a column per day and a row per fact', () => {
		const { container, getByText } = render(TouringTable, { snap: tour, units: 'imperial' });
		expect(container.querySelectorAll('thead th').length).toBe(6); // the label and five days
		for (const row of ['Low cloud', 'Ridge wind', 'Summit gusts', 'Sunrise', 'Day length'])
			expect(getByText(row)).toBeTruthy();
		// The night before, at each of the location's elevations.
		for (const b of tour.bands) expect(getByText(b.label)).toBeTruthy();
		expect(container.querySelectorAll('.rf').length).toBe(15);
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
