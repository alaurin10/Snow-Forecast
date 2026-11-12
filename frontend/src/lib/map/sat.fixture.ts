// Recent satellite test data: four locations, with two, one, none and a stitched view.
import type { SatComposite, SatOut, SatScene } from '../types.gen';

export const scene = (over: Partial<SatScene> = {}): SatScene => ({
	id: 'S2C_MSIL2A_20261104T182601_R127',
	time: '2026-11-04T18:26:01Z',
	platform: 'Sentinel-2C',
	clear_pct: 92,
	snow_pct: 40,
	nodata_pct: 0,
	view: '0123456789abcdef',
	...over
});

const square = (w: number, s: number, e: number, n: number) => [
	[
		[w, s],
		[e, s],
		[e, n],
		[w, n],
		[w, s]
	] as [number, number][]
];

/** Stitched at Snoqualmie: a 4 Nov strip beside 21 Oct; the newest pass (10 Nov) cloudy. */
export const composite: SatComposite = {
	view: 'fedcba9876543210',
	layers: [
		{
			id: 'S2A_MSIL2A_20261104T190821_R013',
			time: '2026-11-04T12:00:00Z',
			platform: 'Sentinel-2A',
			share_pct: 30
		},
		{
			id: 'S2B_MSIL2A_20261021T191429_R056',
			time: '2026-10-21T12:00:00Z',
			platform: 'Sentinel-2B',
			share_pct: 60
		}
	],
	parts: [
		{
			time: '2026-11-04T12:00:00Z',
			share_pct: 30,
			polygons: [square(-121.5, 47.3, -121.45, 47.5)]
		},
		{ time: '2026-10-21T12:00:00Z', share_pct: 60, polygons: [square(-121.45, 47.3, -121.3, 47.5)] }
	],
	lines: [
		[
			[-121.45, 47.3],
			[-121.45, 47.5]
		]
	],
	filled_pct: 90,
	at_location: '2026-10-21T12:00:00Z',
	latest_pass: '2026-11-10T12:00:00Z'
};

const box = (lat: number, lon: number): [number, number, number, number] => [
	lon - 0.16,
	lat - 0.11,
	lon + 0.16,
	lat + 0.11
];

export const data: SatOut = {
	viirs_date: '2026-11-10',
	days: 30,
	scene_days: 60,
	min_clear_pct: 85,
	zooms: [9, 13],
	locations: [
		{
			id: 'whistler',
			name: 'Whistler',
			lat: 50.06,
			lon: -122.95,
			box: box(50.06, -122.95),
			scenes: [scene()]
		},
		{
			id: 'revelstoke',
			name: 'Revelstoke',
			lat: 51.0,
			lon: -118.16,
			box: box(51.0, -118.16),
			scenes: [
				scene({ id: 'a', time: '2026-11-09T12:00:00Z', view: 'aaaaaaaaaaaaaaaa' }),
				scene({
					id: 'b',
					time: '2026-10-30T19:00:00Z',
					clear_pct: 77,
					snow_pct: 0,
					view: 'bbbbbbbbbbbbbbbb'
				})
			]
		},
		{
			id: 'sunshine',
			name: 'Sunshine',
			lat: 51.08,
			lon: -115.77,
			box: box(51.08, -115.77),
			scenes: []
		},
		{
			id: 'snoqualmie',
			name: 'Snoqualmie Pass',
			lat: 47.424,
			lon: -121.418,
			box: box(47.424, -121.418),
			scenes: [scene({ id: 'c', time: '2026-10-15T12:00:00Z', view: 'cccccccccccccccc' })],
			composite
		}
	]
};
