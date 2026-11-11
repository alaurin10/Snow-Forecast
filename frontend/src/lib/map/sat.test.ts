// Recent satellite: which location's scene shows, how it's labelled, and what's drawn.
import { describe, expect, it } from 'vitest';
import { data, scene } from './sat.fixture';
import { ago, dayLabel, nearestSpot, recentSpec, sceneDay, sceneLabel } from './sat';
import { mapStyle } from './style';

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
		expect(sceneLabel(s, now)).toBe('Sentinel-2C · 4 Nov · 6 days ago · 92% clear');
		expect(dayLabel('2026-11-10')).toBe('10 Nov');
		expect(sceneDay(scene())).toBe('2026-11-04');
	});
});

describe('what the base draws', () => {
	it('has daily VIIRS, HLS from the same pass and every Sentinel-2 tile of it', () => {
		const spec = recentSpec(data, scene(), 'natural');
		expect(spec.viirs?.tiles[0]).toBe(
			'/api/tiles/gibs/VIIRS_NOAA20_CorrectedReflectance_TrueColor/2026-11-10/{z}/{x}/{y}'
		);
		expect(spec.hls?.tiles[0]).toContain('/HLS_S30_Nadir_BRDF_Adjusted_Reflectance/2026-11-04/');
		expect(spec.s2.map((s) => s.tiles[0])).toEqual([
			'/api/tiles/s2/natural/S2C_MSIL2A_20261104T182601_R127_T10UEA_20261104T221403/{z}/{x}/{y}.webp',
			'/api/tiles/s2/natural/S2C_MSIL2A_20261104T182601_R127_T10UDA_20261104T221403/{z}/{x}/{y}.webp'
		]);
		expect(spec.s2[0].bounds).toEqual([-123, 49.5, -121.5, 50.5]);
		expect(spec.s2[0].tileSize).toBe(512);
		expect(spec.s2[0].attribution).toContain('Copernicus Sentinel');
	});

	it('swaps to the snow-vs-cloud bands, without HLS (GIBS has no such view of it)', () => {
		const spec = recentSpec(data, scene(), 'snow');
		expect(spec.viirs?.tiles[0]).toContain('BandsM11-I2-I1');
		expect(spec.hls).toBeNull();
		expect(spec.s2[0].tiles[0]).toContain('/api/tiles/s2/snow/');
	});

	it('draws only the daily mosaic with no scene, and nothing without the index', () => {
		expect(recentSpec(data, null, 'natural')).toMatchObject({ hls: null, s2: [] });
		expect(recentSpec(data, scene({ hls: false }), 'natural').hls).toBeNull();
		expect(recentSpec(null, null, 'natural')).toEqual({ viirs: null, hls: null, s2: [] });
	});

	it('puts place names and contours over recent imagery, not Esri’s', () => {
		const style = mapStyle({
			dark: false,
			full: true,
			units: 'metric',
			base: 'recent',
			runs: true,
			peaks: true,
			contours: true,
			shade: 'light',
			overlay: 'none',
			worker: true,
			contourTiles: 'contours://{z}/{x}/{y}'
		});
		const vis = (id: string) =>
			(style.layers.find((l) => l.id === id)?.layout as { visibility?: string } | undefined)
				?.visibility;
		expect(vis('satlabels')).toBe('visible');
		expect(vis('contour-lines')).toBe('visible');
		expect(vis('sat')).toBe('none');
		expect(vis('esri')).toBe('none');
	});
});
