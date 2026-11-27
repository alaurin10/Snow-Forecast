// Named peaks everywhere (forecasts anywhere need them to find a spot by): from the label
// tiles, beneath the saved areas' own, under the same Peaks switch.
import { describe, expect, it } from 'vitest';
import { featureFilter } from '@maplibre/maplibre-gl-style-spec';
import type { FilterSpecification } from 'maplibre-gl';
import { mapStyle, PEAK_LAYERS } from './style';

const style = (peaks: boolean, full = true) =>
	mapStyle({
		dark: false,
		full,
		units: 'imperial',
		base: 'topo',
		runs: true,
		peaks,
		places: true,
		glaciers: true,
		contours: false,
		shade: 'light',
		overlay: 'none',
		worker: false
	});

describe('peaks everywhere', () => {
	it('come from the label tiles, beneath the saved areas’ peaks, under the Peaks switch', () => {
		const s = style(true);
		const ids = s.layers.map((l) => l.id);
		const all = s.layers.find((l) => l.id === 'peak-labels-all')!;
		expect(all).toMatchObject({ source: 'labels', 'source-layer': 'mountain_peak' });
		expect(ids.indexOf('peak-labels-all')).toBeLessThan(ids.indexOf('peak-labels'));
		expect(PEAK_LAYERS).toContain('peak-labels-all');
		const off = style(false).layers.find((l) => l.id === 'peak-labels-all')!;
		expect((off.layout as { visibility: string }).visibility).toBe('none');
		// Not on the small overview map.
		expect(style(true, false).layers.some((l) => l.id === 'peak-labels-all')).toBe(false);
	});

	it('show the most prominent zoomed out and every named peak close in', () => {
		const all = style(true).layers.find((l) => l.id === 'peak-labels-all')!;
		const f = featureFilter(
			(all as { filter: FilterSpecification }).filter as never,
			'layers.peak-labels-all.filter'
		);
		const peak = (rank: number, extra: Record<string, unknown> = {}) => ({
			type: 1 as const,
			properties: { class: 'peak', name: 'Big Chief', rank, ele: 2200, ...extra }
		});
		const at = (zoom: number, feature: ReturnType<typeof peak>) =>
			f.filter({ zoom }, feature as never);
		expect(at(9, peak(1))).toBe(true);
		expect(at(9, peak(2))).toBe(false);
		expect(at(11, peak(4))).toBe(true);
		expect(at(13, peak(40))).toBe(true);
		expect(at(13, peak(1, { class: 'saddle' }))).toBe(false);
		expect(at(13, { type: 1, properties: { class: 'peak', rank: 1 } } as never)).toBe(false);
	});
});
