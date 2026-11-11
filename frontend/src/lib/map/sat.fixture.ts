// Recent satellite test data: three locations, with two, one and no clear scenes.
import type { SatComposite, SatOut, SatScene } from '../types.gen';

export const scene = (over: Partial<SatScene> = {}): SatScene => ({
	id: 'S2C_MSIL2A_20261104T182601_R127',
	time: '2026-11-04T18:26:01Z',
	platform: 'Sentinel-2C',
	clear_pct: 92,
	snow_pct: 40,
	nodata_pct: 0,
	hls: true,
	items: [
		{
			id: 'S2C_MSIL2A_20261104T182601_R127_T10UEA_20261104T221403',
			bbox: [-123, 49.5, -121.5, 50.5]
		},
		{
			id: 'S2C_MSIL2A_20261104T182601_R127_T10UDA_20261104T221403',
			bbox: [-124.4, 49.5, -122.8, 50.5]
		}
	],
	...over
});

const NEW_ITEM = 'S2A_MSIL2A_20261104T190821_R013_T10TFT_20261104T221403';
const OLD_ITEM = 'S2B_MSIL2A_20261021T191429_R056_T10TFT_20261021T211203';

/** Stitched at Snoqualmie: a 4 Nov strip over 21 Oct; the newest pass (10 Nov) cloudy. */
export const composite: SatComposite = {
	layers: [
		{
			id: 'S2A_MSIL2A_20261104T190821_R013',
			time: '2026-11-04T12:00:00Z',
			platform: 'Sentinel-2A',
			share_pct: 30,
			items: [{ id: NEW_ITEM, bbox: [-122.3, 46.9, -120.9, 47.9] }],
			bbox: [-121.5, 47.3, -121.45, 47.5]
		},
		{
			id: 'S2B_MSIL2A_20261021T191429_R056',
			time: '2026-10-21T12:00:00Z',
			platform: 'Sentinel-2B',
			share_pct: 60,
			items: [
				{ id: OLD_ITEM, bbox: [-122.3, 46.9, -120.9, 47.9] },
				{
					id: 'S2B_MSIL2A_20261021T191429_R056_T10TGT_20261021T211203',
					bbox: [-121, 46.9, -119.6, 47.9]
				}
			],
			bbox: [-121.45, 47.3, -121.3, 47.5]
		}
	],
	filled_pct: 90,
	at_location: '2026-10-21T12:00:00Z',
	latest_pass: '2026-11-10T12:00:00Z',
	box: [-121.58, 47.31, -121.26, 47.53],
	boundaries: [
		[
			[-121.45, 47.3],
			[-121.45, 47.5]
		]
	],
	labels: [
		{ lon: -121.48, lat: 47.4, time: '2026-11-04T12:00:00Z' },
		{ lon: -121.38, lat: 47.4, time: '2026-10-21T12:00:00Z' }
	]
};

export const data: SatOut = {
	viirs_date: '2026-11-10',
	hls_date: '2026-11-04',
	days: 30,
	min_clear_pct: 70,
	locations: [
		{ id: 'whistler', name: 'Whistler', lat: 50.06, lon: -122.95, scenes: [scene()] },
		{
			id: 'revelstoke',
			name: 'Revelstoke',
			lat: 51.0,
			lon: -118.16,
			scenes: [
				scene({ id: 'a', time: '2026-11-09T12:00:00Z', hls: false }),
				scene({ id: 'b', time: '2026-10-30T19:00:00Z', clear_pct: 77, snow_pct: 0 })
			]
		},
		{ id: 'sunshine', name: 'Sunshine', lat: 51.08, lon: -115.77, scenes: [] },
		{
			id: 'snoqualmie',
			name: 'Snoqualmie Pass',
			lat: 47.424,
			lon: -121.418,
			scenes: [scene({ id: 'c', time: '2026-10-15T12:00:00Z' })],
			composite
		}
	]
};
