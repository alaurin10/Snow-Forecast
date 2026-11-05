// Every chart rendered from a real snapshot (Whistler: snowy; Crystal: mostly
// dry), checking that every data mark stays inside its plot area.
import { describe, expect, it, afterEach } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import whistler from '../../fixtures/whistler.json';
import crystal from '../../fixtures/crystal.json';
import type { Snapshot } from '../../types.gen';
import { crosshair } from '../../crosshair.svelte';
import HourlyStack from '../HourlyStack.svelte';
import DayNightBars from '../DayNightBars.svelte';
import ModelAgreement from '../ModelAgreement.svelte';
import Exceedance from '../Exceedance.svelte';
import TrendChart from '../TrendChart.svelte';
import Sparkline from '../Sparkline.svelte';

const snowy = whistler as unknown as Snapshot;
const dry = crystal as unknown as Snapshot;

afterEach(() => {
	cleanup();
	crosshair.reset();
});

/** Points visited by an SVG path (absolute M/L/H/V/Q/C/Z, as our charts emit). */
function pathPoints(d: string): [number, number][] {
	const pts: [number, number][] = [];
	let x = 0;
	let y = 0;
	for (const [, cmd, args] of d.matchAll(/([MLHVQCZ])([^MLHVQCZ]*)/g)) {
		const n = (args.match(/-?\d*\.?\d+(e-?\d+)?/g) ?? []).map(Number);
		if (cmd === 'H') n.forEach((v) => pts.push([(x = v), y]));
		else if (cmd === 'V') n.forEach((v) => pts.push([x, (y = v)]));
		else if (cmd !== 'Z')
			for (let i = 0; i + 1 < n.length; i += 2) pts.push([(x = n[i]), (y = n[i + 1])]);
	}
	return pts;
}

/** Assert every `.mark` inside each plot group lies within [0, iw] × [0, ih] (+ slack). */
function expectMarksInside(container: HTMLElement, slack = 1) {
	const plots = container.querySelectorAll<SVGGElement>('g.plot');
	expect(plots.length).toBeGreaterThan(0);
	let checked = 0;
	plots.forEach((g) => {
		const iw = Number(g.dataset.iw);
		const ih = Number(g.dataset.ih);
		// The chance-of-precip and x-label rows sit just below the plot by design.
		const below = 26;
		g.querySelectorAll<SVGElement>('.mark').forEach((el) => {
			const pts: [number, number][] = [];
			const a = (n: string) => Number(el.getAttribute(n));
			if (el.tagName === 'path') pts.push(...pathPoints(el.getAttribute('d') ?? ''));
			if (el.tagName === 'rect')
				pts.push([a('x'), a('y')], [a('x') + a('width'), a('y') + a('height')]);
			if (el.tagName === 'line') pts.push([a('x1'), a('y1')], [a('x2'), a('y2')]);
			if (el.tagName === 'circle') pts.push([a('cx'), a('cy')]);
			const title = g.closest('figure')?.querySelector('.title')?.textContent;
			for (const [x, y] of pts) {
				const where = `${title}: <${el.tagName} class="${el.getAttribute('class')}"> at (${x.toFixed(1)}, ${y.toFixed(1)}) in ${iw}×${ih}`;
				expect(x, where).toBeGreaterThanOrEqual(-slack);
				expect(x, where).toBeLessThanOrEqual(iw + slack);
				expect(y, where).toBeGreaterThanOrEqual(-slack);
				expect(y, where).toBeLessThanOrEqual(ih + below);
				checked++;
			}
		});
	});
	expect(checked).toBeGreaterThan(0);
}

describe.each([
	['snowy', snowy],
	['dry', dry]
])('%s snapshot', (_name, snap) => {
	const band = snap.bands[1];

	it('hourly stack keeps marks in bounds at phone and desktop widths', () => {
		for (const width of [340, 900]) {
			const { container, unmount } = render(HourlyStack, {
				props: { band, bands: snap.bands, units: 'imperial', width }
			});
			expectMarksInside(container);
			expect(container.querySelectorAll('figure')).toHaveLength(6);
			unmount();
		}
	});

	it('day/night bars keep marks in bounds and have a hit target per period', () => {
		const { container } = render(DayNightBars, {
			props: { periods: band.periods, units: 'metric', width: 360 }
		});
		expectMarksInside(container);
		expect(container.querySelectorAll('rect.hit[role="button"]')).toHaveLength(20);
	});

	it('model agreement keeps marks in bounds', () => {
		const { container } = render(ModelAgreement, {
			props: { daily: snap.daily, models: snap.models, units: 'imperial', width: 360 }
		});
		expectMarksInside(container);
	});

	it('sparkline keeps marks in bounds on a shared scale', () => {
		const periods = band.periods.map((p) => ({
			key: p.key,
			label: p.label,
			kind: p.kind,
			date: p.date,
			snow_cm: p.snow_cm
		}));
		const max = Math.max(2.54, ...periods.map((p) => p.snow_cm ?? 0));
		const { container } = render(Sparkline, { props: { periods, max, width: 280 } });
		const bars = container.querySelectorAll('path.mark');
		expect(bars.length).toBe(periods.filter((p) => (p.snow_cm ?? 0) > 0).length);
		if (bars.length) expectMarksInside(container, 0.5);
		else expect(container.querySelector('svg')).not.toBeNull();
	});

	it('exceedance curve keeps marks in bounds', () => {
		const { container } = render(Exceedance, {
			props: {
				title: 'Next 5 days',
				members: band.windows['next5'].members_cm ?? [],
				units: 'imperial',
				width: 320
			}
		});
		expectMarksInside(container);
	});
});

it('no chart has a second y-axis: one tick column per plot', () => {
	const band = snowy.bands[1];
	const { container } = render(HourlyStack, {
		props: { band, bands: snowy.bands, units: 'imperial', width: 600 }
	});
	container.querySelectorAll<SVGGElement>('g.plot').forEach((g) => {
		const xs = new Set(
			[...g.querySelectorAll('text.tick')].map((t) => t.getAttribute('x')).filter((x) => x === '-6')
		);
		const right = [...g.querySelectorAll('text.tick')].filter(
			(t) => Number(t.getAttribute('x')) > Number(g.dataset.iw)
		);
		expect(xs.size).toBeLessThanOrEqual(1);
		expect(right).toHaveLength(0);
	});
});

it('the crosshair moves every hourly header together', () => {
	const band = snowy.bands[1];
	const { container } = render(HourlyStack, {
		props: { band, bands: snowy.bands, units: 'imperial', width: 600 }
	});
	const readouts = () => [...container.querySelectorAll('.readout')].map((r) => r.textContent);
	const atNow = readouts();
	expect(container.querySelector('.when')?.textContent?.trim()).toBe('Now');
	const i = band.hourly.temp_c.findIndex((t, k) => k > 0 && t !== band.hourly.temp_c[0]);
	crosshair.set(i);
	flushSync();
	const moved = readouts();
	expect(container.querySelector('.when')?.textContent?.trim()).not.toBe('Now');
	expect(moved[2]).not.toBe(atNow[2]); // temperature header follows the crosshair
	expect(container.querySelectorAll('line.cross')).toHaveLength(6);
});

it('empty states render without errors', () => {
	const { container } = render(Exceedance, {
		props: { title: 'Days 6–10', members: [], units: 'imperial', width: 300 }
	});
	expect(container.textContent).toContain('No ensemble data');
	const t = render(TrendChart, { props: { runs: [], units: 'imperial', width: 300 } });
	expect(t.container.textContent).toContain('two or more runs');
});
