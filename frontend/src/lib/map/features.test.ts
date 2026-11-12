import { describe, expect, it } from 'vitest';
import type { AtesOut, MapStation, ObsOut, StationsOut } from '../types.gen';
import {
	ago,
	ATES,
	atesGeojson,
	depthColor,
	DEPTH_STEPS,
	networkName,
	newSnowLabel,
	REPORT_KINDS,
	reportColor,
	reportsGeojson,
	sparkline,
	stationsGeojson
} from './features';
import { hereItems, skiLines, type Hit } from './here';

const station = (over: Partial<MapStation> = {}): MapStation => ({
	id: '908:WA:SNTL',
	name: 'Olallie Meadows',
	network: 'snotel',
	lat: 47.37,
	lon: -121.44,
	elev_m: 1222,
	obs_time: '2026-11-12T17:00+00:00',
	depth_cm: 40,
	change24_cm: 15,
	daily: [],
	...over
});

describe('snow stations', () => {
	it('colours depth and labels new snow in the viewer’s units', () => {
		expect(depthColor(0)).toBe(DEPTH_STEPS[0].color);
		expect(depthColor(40)).toBe(DEPTH_STEPS[2].color);
		expect(depthColor(250)).toBe(DEPTH_STEPS[4].color);
		expect(depthColor(null)).toBe('#8a8f98');
		expect(newSnowLabel(15.2, 'metric')).toBe('+15');
		expect(newSnowLabel(15.2, 'imperial')).toBe('+6');
		expect(newSnowLabel(0.5, 'metric')).toBe('');
		expect(newSnowLabel(-3, 'metric')).toBe('');
	});

	it('builds the map’s points', () => {
		const d: StationsOut = {
			generated_at: 'x',
			stations: [station(), station({ change24_cm: null, network: 'bc' })]
		};
		const fc = stationsGeojson(d, 'metric');
		expect(fc.features[0].properties).toMatchObject({ i: 0, label: '+15', fresh: true });
		expect(fc.features[1].properties).toMatchObject({ i: 1, label: '', fresh: false });
		expect(fc.features[0].geometry).toEqual({ type: 'Point', coordinates: [-121.44, 47.37] });
		expect(networkName(d.stations[1])).toMatch(/BC River Forecast Centre/);
	});

	it('draws a week as a sparkline, with gaps for missing days', () => {
		const days = [10, 12, null, 20, 30].map((v) => ({ depth_cm: v }));
		const { d, max } = sparkline(days, 100, 40);
		expect(max).toBe(30);
		expect(d.match(/M/g)).toHaveLength(2);
		expect(d.startsWith('M0.0,26.7L25.0,24.0')).toBe(true);
		expect(d.endsWith('L100.0,0.0')).toBe(true);
		expect(sparkline([{ depth_cm: 5 }], 100, 40).d).toBe('');
	});

	it('says how old a reading is', () => {
		const now = Date.parse('2026-11-12T18:00:00Z');
		expect(ago('2026-11-12T17:30:00Z', now)).toBe('within the hour');
		expect(ago('2026-11-12T13:00:00Z', now)).toBe('5 h ago');
		expect(ago('2026-11-09T18:00:00Z', now)).toBe('3 days ago');
		expect(ago(null, now)).toBe('');
	});
});

describe('field reports and ATES', () => {
	it('colours a report by its most telling kind', () => {
		expect(reportColor(['avalanche', 'quick'])).toBe(REPORT_KINDS.avalanche.color);
		expect(reportColor([])).toBe(REPORT_KINDS.quick.color);
		const d: ObsOut = {
			generated_at: 'x',
			days: 14,
			features: [
				{
					geometry: { type: 'Point', coordinates: [-117, 51] },
					properties: {
						id: 'a',
						title: 't',
						time: '2026-11-11T19:00+00:00',
						region: 'Purcells',
						kinds: ['snowpack'],
						images: 0,
						url: null
					}
				}
			]
		};
		expect(reportsGeojson(d).features[0].properties).toEqual({
			i: 0,
			color: REPORT_KINDS.snowpack.color
		});
	});

	it('keeps ATES ratings as the file gave them', () => {
		const d: AtesOut = {
			files: [],
			features: [
				{
					geometry: { type: 'LineString', coordinates: [] },
					properties: { rating: 'complex', name: 'Couloir', file: 'a.kmz' }
				}
			]
		};
		expect(atesGeojson(d).features[0].properties).toEqual({
			rating: 'complex',
			name: 'Couloir',
			file: 'a.kmz'
		});
	});
});

describe('what a tap landed on', () => {
	const ski: GeoJSON.FeatureCollection = {
		type: 'FeatureCollection',
		features: [
			{
				type: 'Feature',
				properties: { kind: 'run', osm: 'w1', name: 'Couloir' },
				geometry: {
					type: 'LineString',
					coordinates: [
						[0, 0],
						[0, 1],
						[0, 2]
					]
				}
			},
			{
				type: 'Feature',
				properties: { kind: 'route', osm: 'r2' },
				geometry: {
					type: 'MultiLineString',
					coordinates: [
						[
							[1, 1],
							[1, 2]
						],
						[
							[1, 0],
							[1, 1]
						]
					]
				}
			},
			{
				type: 'Feature',
				properties: { kind: 'peak' },
				geometry: { type: 'Point', coordinates: [0, 0] }
			}
		]
	};

	it('indexes runs and routes by their OpenStreetMap ids', () => {
		const lines = skiLines(ski);
		expect([...lines.keys()]).toEqual(['w1', 'r2']);
		expect(lines.get('r2')).toEqual([
			[1, 0],
			[1, 1],
			[1, 2]
		]);
	});

	it('lists each thing once, in words, with the whole line of a run', () => {
		const hits: Hit[] = [
			{
				layer: 'places',
				properties: { kind: 'hut', type: 'alpine_hut', name: 'Wedgemount Hut', ele: 1880 }
			},
			{
				layer: 'runs',
				properties: {
					kind: 'run',
					type: 'downhill',
					difficulty: 'expert',
					name: 'Couloir',
					osm: 'w1'
				},
				geometry: {
					type: 'LineString',
					coordinates: [
						[0, 0],
						[0, 1]
					]
				}
			},
			// The same run in the next tile.
			{ layer: 'runs', properties: { kind: 'run', name: 'Couloir', osm: 'w1' } },
			{ layer: 'glaciers', properties: { kind: 'glacier', name: '' } },
			{ layer: 'ates-fill', properties: { rating: 'challenging', name: '', file: 'a.kmz' } },
			{ layer: 'places', properties: { kind: 'pass', type: 'pass', name: '' } }
		];
		const items = hereItems(hits, 'metric', skiLines(ski));
		expect(items.map((i) => [i.kind, i.name, i.detail ?? ''])).toEqual([
			['Hut', 'Wedgemount Hut', '1,880 m'],
			['Run', 'Couloir', 'expert'],
			['Glacier', 'Glacier ice', ''],
			['ATES', 'Challenging', 'from a.kmz'],
			['Pass', 'Unnamed', '']
		]);
		expect(items[1].line).toHaveLength(3);
		expect(items[1].osm).toBe('w1');
		expect(items[3].color).toBe(ATES.challenging.color);
		// Without the index, the line as drawn.
		expect(hereItems([hits[1]], 'metric', null)[0].line).toHaveLength(2);
		// A run mapped as an outline: named, but no profile.
		const ring: Hit = {
			layer: 'runs',
			properties: { kind: 'run', name: 'Glacier Bowl', osm: 'w9' },
			geometry: {
				type: 'LineString',
				coordinates: [
					[0, 0],
					[0, 1],
					[1, 1],
					[0, 0]
				]
			}
		};
		const bowl = hereItems([ring], 'metric', null)[0];
		expect(bowl.name).toBe('Glacier Bowl');
		expect(bowl.line).toBeUndefined();
		expect(bowl.osm).toBeUndefined();
	});
});
