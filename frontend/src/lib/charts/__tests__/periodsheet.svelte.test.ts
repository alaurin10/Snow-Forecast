// The period details: the big number is the headline depth, with its ratio under it
// and the other method's figure in the details.
import { describe, expect, it, afterEach, vi } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import whistler from '../../fixtures/whistler.json';
import type { PeriodOut, Snapshot } from '../../types.gen';

vi.mock('../../api', () => ({
	getMeta: () => Promise.resolve({ snowfall_cm_per_mm: 0.7 })
}));
import PeriodSheet from '../PeriodSheet.svelte';

const snap = whistler as unknown as Snapshot;
// A cold, snowy period: the temperature-based depth beats 7:1.
const cold = snap.bands[2].periods.find(
	(p) => p.slr && p.slr > 7 && (p.snow_cm ?? 0) > 5 && p.snow_cm_raw !== p.snow_cm
) as PeriodOut;

afterEach(cleanup);

describe('period sheet', () => {
	it('shows the temperature-based depth and its ratio, and the 7:1 snowfall', () => {
		expect(snap.depth_method).toBe('slr');
		expect(cold).toBeTruthy();
		const { container, getByText } = render(PeriodSheet, {
			period: cold,
			bandLabel: 'Summit',
			units: 'metric',
			depthMethod: 'slr',
			onclose: () => {}
		});
		const big = container.querySelector('.big')?.textContent ?? '';
		expect(big).toContain(String(Math.round(cold.snow_cm ?? 0)));
		expect(container.textContent).toContain(`at ${cold.slr}:1`);
		expect(getByText('Model snowfall at 7:1')).toBeTruthy();
		expect(container.textContent).toMatch(/ratio from the temperature while it snows/);
		expect(container.textContent).not.toMatch(/uses a fixed 7:1/);
	});

	it('says 7:1 when that is the headline', () => {
		const raw = { ...cold, snow_cm: cold.snow_cm_raw };
		const { container, getByText } = render(PeriodSheet, {
			period: raw,
			bandLabel: 'Summit',
			units: 'metric',
			depthMethod: 'raw',
			onclose: () => {}
		});
		expect(container.textContent).toContain('at 7:1');
		expect(getByText(`With the snow ratio (${cold.slr}:1)`)).toBeTruthy();
		expect(container.textContent).toMatch(/uses a fixed 7:1/);
	});
});
