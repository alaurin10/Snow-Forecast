// Recent satellite test data: three locations, with two, one and no clear scenes.
import type { SatOut, SatScene } from '../types.gen';

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
		{ id: 'sunshine', name: 'Sunshine', lat: 51.08, lon: -115.77, scenes: [] }
	]
};
