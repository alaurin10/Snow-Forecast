// Every chart rendered from a real snapshot (Whistler: snowy; Crystal: mostly
// dry), checking that every data mark stays inside its plot area.
import { describe, expect, it, afterEach } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import { expectMarksInside } from './marks';
import whistler from '../../fixtures/whistler.json';
import crystal from '../../fixtures/crystal.json';
import type { Snapshot } from '../../types.gen';
import { crosshair } from '../../crosshair.svelte';
import ForecastChart from '../ForecastChart.svelte';
import ModelAgreement from '../ModelAgreement.svelte';
import Exceedance from '../Exceedance.svelte';
import TrendChart from '../TrendChart.svelte';
import { pathPoints } from './marks';

const snowy = whistler as unknown as Snapshot;
const dry = crystal as unknown as Snapshot;

afterEach(() => {
	cleanup();
	crosshair.reset();
});

/** The forecast chart draws in a 1000-wide viewBox per plot: nothing may fall outside. */
function expectInViewBox(container: HTMLElement, slack = 1) {
	const svgs = [...container.querySelectorAll<SVGSVGElement>('svg[viewBox^="0 0 1000"]')];
	expect(svgs.length).toBeGreaterThan(0);
	let checked = 0;
	for (const svg of svgs) {
		const [, , w, h] = (svg.getAttribute('viewBox') ?? '').split(' ').map(Number);
		for (const el of svg.querySelectorAll('path')) {
			for (const [x, y] of pathPoints(el.getAttribute('d') ?? '')) {
				expect(x).toBeGreaterThanOrEqual(-slack);
				expect(x).toBeLessThanOrEqual(w + slack);
				expect(y).toBeGreaterThanOrEqual(-slack);
				expect(y).toBeLessThanOrEqual(h + slack);
				checked++;
			}
		}
		for (const el of svg.querySelectorAll('rect')) {
			const x = Number(el.getAttribute('x') ?? 0);
			const y = Number(el.getAttribute('y') ?? 0);
			expect(x).toBeGreaterThanOrEqual(-slack);
			expect(y).toBeGreaterThanOrEqual(-slack);
			expect(x + Number(el.getAttribute('width') ?? 0)).toBeLessThanOrEqual(w + slack);
			expect(y + Number(el.getAttribute('height') ?? 0)).toBeLessThanOrEqual(h + slack);
			checked++;
		}
	}
	expect(checked).toBeGreaterThan(0);
}

describe.each([
	['snowy', snowy],
	['dry', dry]
])('%s snapshot', (_name, snap) => {
	const band = snap.bands[1];

	it('forecast chart keeps every mark inside its plot', () => {
		const { container } = render(ForecastChart, {
			props: { band, bands: snap.bands, units: 'imperial' }
		});
		expectInViewBox(container);
	});

	it('model agreement keeps marks in bounds', () => {
		const { container } = render(ModelAgreement, {
			props: { daily: snap.daily, models: snap.models, units: 'imperial', width: 360 }
		});
		expectMarksInside(container);
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

it('empty states render without errors', () => {
	const { container } = render(Exceedance, {
		props: { title: 'Days 6–10', members: [], units: 'imperial', width: 300 }
	});
	expect(container.textContent).toContain('No ensemble data');
	const t = render(TrendChart, { props: { runs: [], units: 'imperial', width: 300 } });
	expect(t.container.textContent).toContain('two or more runs');
});
