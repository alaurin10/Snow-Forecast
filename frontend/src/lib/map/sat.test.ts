// Recent satellite: which location's scene shows, how it's labelled, and what's drawn.
import { describe, expect, it } from 'vitest';
import { composite, data, scene } from './sat.fixture';
import {
	ago,
	datesGeojson,
	dayLabel,
	nearestSpot,
	recentSpec,
	satViews,
	sceneLabel,
	stitchedSpan
} from './sat';
import { featureFilter } from '@maplibre/maplibre-gl-style-spec';
import { mapStyle, SAT_LABEL_LAYERS } from './style';

describe('picking and labelling scenes', () => {
	it('takes the nearest location within range', () => {
		expect(nearestSpot(data, 50.1, -122.9)?.spot.id).toBe('whistler');
		expect(nearestSpot(data, 51.05, -116.2)?.spot.id).toBe('sunshine');
		expect(nearestSpot(data, 45, -110)).toBeNull();
		expect(nearestSpot(null, 50.1, -122.9)).toBeNull();
	});

	it('says how old a scene is by calendar day', () => {
		const now = new Date(2026, 10, 10, 9).getTime();
		expect(ago(new Date(2026, 10, 10, 1).toISOString(), now)).toBe('today');
		expect(ago(new Date(2026, 10, 9, 23).toISOString(), now)).toBe('yesterday');
		expect(ago(new Date(2026, 10, 4, 12).toISOString(), now)).toBe('6 days ago');
	});

	it('reads like the plan’s chip', () => {
		const now = new Date(2026, 10, 10, 12).getTime();
		const s = scene({ time: new Date(2026, 10, 4, 12).toISOString() });
		expect(sceneLabel(s, now)).toBe('4 Nov · 6 days ago · 92% clear');
		expect(dayLabel('2026-11-10')).toBe('10 Nov');
	});
});

describe('the stitched view', () => {
	it('comes first, then the whole scenes', () => {
		const spot = data.locations!.find((l) => l.id === 'snoqualmie')!;
		expect(satViews(spot).map((v) => v.kind)).toEqual(['stitched', 'scene']);
		expect(satViews(data.locations![1]).map((v) => v.kind)).toEqual(['scene', 'scene']);
		expect(satViews(null)).toEqual([]);
		expect(stitchedSpan(composite)).toBe('21 Oct–4 Nov');
		const within = {
			...composite,
			layers: [
				{ ...composite.layers[0], time: new Date(2026, 10, 9, 12).toISOString() },
				{ ...composite.layers[0], time: new Date(2026, 10, 2, 12).toISOString() }
			]
		};
		expect(stitchedSpan(within)).toBe('2–9 Nov');
	});

	it('draws a line where two passes meet, and dates each part, the newest marked', () => {
		const fc = datesGeojson(composite);
		expect(fc.features.map((f) => f.properties)).toEqual([
			{ kind: 'line' },
			{ kind: 'part', label: '4 Nov', newest: true },
			{ kind: 'part', label: '21 Oct', newest: false }
		]);
		expect(fc.features[0].geometry).toEqual({
			type: 'MultiLineString',
			coordinates: composite.lines
		});
		expect(fc.features[1].geometry).toEqual({
			type: 'MultiPolygon',
			coordinates: composite.parts[0].polygons
		});
	});
});

describe('what the base draws', () => {
	const snoq = data.locations!.find((l) => l.id === 'snoqualmie')!;

	it('one layer of finished tiles for the view, over the area, and the daily mosaic', () => {
		const spec = recentSpec(data, snoq, { kind: 'stitched', composite }, 'natural');
		expect(spec.viirs?.tiles[0]).toBe(
			'/api/tiles/gibs/VIIRS_NOAA20_CorrectedReflectance_TrueColor/2026-11-10/{z}/{x}/{y}'
		);
		expect(spec.view).toMatchObject({
			id: 'view-fedcba9876543210-natural',
			tiles: ['/api/sat/tiles/fedcba9876543210/natural/{z}/{x}/{y}.webp'],
			tileSize: 512,
			minzoom: 9,
			maxzoom: 13,
			bounds: snoq.box
		});
		expect(spec.view?.attribution).toContain('Copernicus Sentinel');
		expect(spec.dates).toEqual(datesGeojson(composite));
	});

	it('a whole scene has no outlines, and the snow bands swap both layers', () => {
		const spec = recentSpec(data, snoq, { kind: 'scene', scene: snoq.scenes![0] }, 'snow');
		expect(spec.view?.tiles[0]).toBe('/api/sat/tiles/cccccccccccccccc/snow/{z}/{x}/{y}.webp');
		expect(spec.viirs?.tiles[0]).toContain('BandsM11-I2-I1');
		expect(spec.dates).toBeNull();
	});

	it('the wide view goes round the area, with its dates beside the centre’s', () => {
		const wideBox: [number, number, number, number] = [-121.9, 47.1, -120.9, 47.75];
		const wide = { ...composite, view: '0123456789abcdef' };
		const spot = { ...snoq, wide, wide_box: wideBox };
		const spec = recentSpec(
			{ ...data, wide_zooms: [7, 12] },
			spot,
			{ kind: 'stitched', composite },
			'snow'
		);
		expect(spec.wide).toMatchObject({
			id: 'wide-0123456789abcdef-snow',
			tiles: ['/api/sat/tiles/0123456789abcdef/snow/{z}/{x}/{y}.webp'],
			minzoom: 7,
			maxzoom: 12,
			bounds: wideBox
		});
		expect(spec.dates?.features).toEqual([
			...datesGeojson(wide, true).features,
			...datesGeojson(composite).features
		]);
		// Stepping to a whole scene keeps the wide view and its dates.
		const scene = recentSpec(data, spot, { kind: 'scene', scene: snoq.scenes![0] }, 'natural');
		expect(scene.wide?.id).toBe('wide-0123456789abcdef-natural');
		expect(scene.dates).toEqual(datesGeojson(wide, true));
		expect(scene.dates?.features.every((f) => f.properties?.wide === true)).toBe(true);
	});

	it('only the daily mosaic with no view, and nothing without the index', () => {
		expect(recentSpec(data, null, null, 'natural')).toMatchObject({
			wide: null,
			view: null,
			dates: null
		});
		expect(recentSpec(null, null, null, 'natural')).toEqual({
			viirs: null,
			wide: null,
			view: null,
			dates: null
		});
	});

	it('puts place names and contours over recent imagery, and nothing that darkens it', () => {
		const style = mapStyle({
			dark: false,
			full: true,
			units: 'metric',
			base: 'recent',
			runs: true,
			peaks: true,
			places: true,
			glaciers: true,
			contours: true,
			shade: 'light',
			overlay: 'none',
			worker: true,
			contourTiles: 'contours://{z}/{x}/{y}'
		});
		const vis = (id: string) =>
			(style.layers.find((l) => l.id === id)?.layout as { visibility?: string } | undefined)
				?.visibility;
		for (const id of SAT_LABEL_LAYERS) expect(vis(id)).toBe('visible');
		// Names and borders come from vector tiles, so county lines can be left out.
		expect(style.sources.labels).toMatchObject({ type: 'vector', maxzoom: 14 });
		expect(style.sources.satlabels).toBeUndefined();
		const border = (props: Record<string, unknown>) =>
			['satlabels', 'satlabels-borders', 'satlabels-countries'].filter((id) => {
				const layer = style.layers.find((l) => l.id === id) as { filter: unknown };
				return featureFilter(layer.filter as never, `layers.${id}.filter`).filter({ zoom: 10 }, {
					type: 2,
					properties: props
				} as never);
			});
		expect(border({ admin_level: 6, maritime: 0 })).toEqual([]); // county
		expect(border({ admin_level: 4, maritime: 1 })).toEqual([]); // at sea
		expect(border({ admin_level: 4, maritime: 0 })).toEqual(['satlabels', 'satlabels-borders']);
		expect(border({ admin_level: 2, maritime: 0 })).toEqual(['satlabels', 'satlabels-countries']);
		expect(vis('contour-lines')).toBe('visible');
		expect(vis('sat')).toBe('none');
		expect(vis('esri')).toBe('none');
		// Nothing dims it: no hill shading, and no 3D haze over the ground.
		expect(vis('shade')).toBe('none');
		expect(style.sky?.['fog-ground-blend']).toBe(1);
	});
});
