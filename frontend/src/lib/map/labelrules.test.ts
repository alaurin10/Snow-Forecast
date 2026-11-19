// What shows when: peaks by isolation, towns by size, and the Names switch.
import { describe, expect, it } from 'vitest';
import { featureFilter } from '@maplibre/maplibre-gl-style-spec';
import { PEAK_FILTER, SAT_BORDER_LAYERS, SAT_NAME_LAYERS, satLabelLayers } from './style';

const passes = (filter: unknown, zoom: number, props: Record<string, unknown>) =>
	featureFilter(filter as never, 'layers.test.filter').filter({ zoom }, {
		type: 1,
		properties: props
	} as never);

describe('label rules', () => {
	it('shows big standalone peaks zoomed out, more as the map zooms in', () => {
		const peak = (iso: number) => ({ kind: 'peak', name: 'P', ele: 2000, iso });
		expect(passes(PEAK_FILTER, 9, peak(20))).toBe(true);
		expect(passes(PEAK_FILTER, 9, peak(10))).toBe(false);
		expect(passes(PEAK_FILTER, 10, peak(10))).toBe(true);
		expect(passes(PEAK_FILTER, 10, peak(5))).toBe(false);
		expect(passes(PEAK_FILTER, 12, peak(1))).toBe(false);
		expect(passes(PEAK_FILTER, 12, peak(1.3))).toBe(true); // Lundin Peak
		expect(passes(PEAK_FILTER, 13, peak(1))).toBe(true);
		expect(passes(PEAK_FILTER, 14, peak(0))).toBe(true);
		// A file from before isolation shows every peak, as before.
		expect(passes(PEAK_FILTER, 10, { kind: 'peak', name: 'Old' })).toBe(true);
		expect(passes(PEAK_FILTER, 14, { kind: 'hut', name: 'H' })).toBe(false);
	});

	it('names only major cities zoomed out, then towns, villages and hamlets', () => {
		const towns = satLabelLayers(true).find((l) => l.id === 'satlabels-towns') as never as {
			filter: unknown;
		};
		const place = (cls: string, rank: number) => ({ class: cls, rank, name: 'X' });
		expect(passes(towns.filter, 8, place('city', 3))).toBe(true); // Seattle
		expect(passes(towns.filter, 8, place('city', 13))).toBe(false); // Bellevue
		expect(passes(towns.filter, 9, place('city', 13))).toBe(true);
		expect(passes(towns.filter, 9.5, place('town', 13))).toBe(false); // Redmond
		expect(passes(towns.filter, 10, place('town', 13))).toBe(true);
		expect(passes(towns.filter, 10, place('village', 13))).toBe(false);
		expect(passes(towns.filter, 10.5, place('village', 13))).toBe(true);
		expect(passes(towns.filter, 10.5, place('hamlet', 13))).toBe(false);
		expect(passes(towns.filter, 11, place('hamlet', 13))).toBe(true);
	});

	it('the Names switch hides names but keeps the borders', () => {
		const vis = (names: boolean) =>
			Object.fromEntries(
				satLabelLayers(true, names).map((l) => [
					l.id,
					(l.layout as { visibility?: string }).visibility
				])
			);
		const off = vis(false);
		for (const id of SAT_BORDER_LAYERS) expect(off[id]).toBe('visible');
		for (const id of SAT_NAME_LAYERS) expect(off[id]).toBe('none');
		const on = vis(true);
		for (const id of SAT_NAME_LAYERS) expect(on[id]).toBe('visible');
		expect(SAT_BORDER_LAYERS).toEqual(['satlabels', 'satlabels-borders', 'satlabels-countries']);
	});
});
