// Zones, treeline bands and the concern index's table of cases.
import { describe, expect, it } from 'vitest';
import type { AvalancheView, AvyDay, ZoneFeature, ZonesOut } from '../types.gen';
import {
	concernProblem,
	contains,
	problemRule,
	todayRatings,
	treelineAt,
	zoneAt,
	zoneLevel,
	zonesGeojson
} from './avalanche';
import {
	bandOf,
	bandRanges,
	concernAt,
	concernClass,
	paintConcern,
	problemKind,
	slopeFactor,
	type ConcernInputs,
	type ConcernParams
} from './terrain/concern';

function view(
	over: Partial<AvalancheView> = {},
	days: AvyDay[] = [{ date: '2026-12-10', alpine: 3, treeline: 2, below: 1 }]
): AvalancheView {
	return {
		location_id: 'nac:1',
		status: 'current',
		today_max: 3,
		doc: {
			provider: 'nac',
			center: 'Northwest Avalanche Center',
			center_id: 'NWAC',
			zone: 'Mt Hood',
			link: null,
			issued_at: null,
			expires_at: null,
			days,
			problems: [
				{ name: 'Wind Slab', aspects: ['N', 'NE', 'E'], elevations: ['alpine', 'treeline'] },
				{ name: 'Wet Loose', aspects: [], elevations: [] }
			]
		},
		...over
	};
}

function square(id: string, w: number, s: number, e: number, n: number, v = view()): ZoneFeature {
	return {
		id,
		geometry: {
			type: 'MultiPolygon',
			coordinates: [
				[
					[
						[w, s],
						[e, s],
						[e, n],
						[w, n],
						[w, s]
					],
					// a hole in the middle
					[
						[w + 0.4, s + 0.4],
						[e - 0.4, s + 0.4],
						[e - 0.4, n - 0.4],
						[w + 0.4, s + 0.4]
					]
				]
			]
		},
		properties: { id, tz: 'America/Los_Angeles', today: '2026-12-10', view: v }
	};
}

describe('zones', () => {
	it('finds the zone under a spot, honouring holes', () => {
		const a = square('nac:1', -122, 45, -121, 46);
		expect(contains(a.geometry, 45.1, -121.9)).toBe(true);
		expect(contains(a.geometry, 45.5, -121.45)).toBe(false); // in the hole
		expect(zoneAt([a], 47, -121.5)).toBeNull();
		expect(zoneAt([a], 45.1, -121.9)?.id).toBe('nac:1');
	});

	it('prefers a rated zone where two overlap', () => {
		const old = square('nac:2', -122, 45, -121, 46, view({ status: 'expired' }));
		const rated = square('nac:1', -122, 45, -121, 46);
		expect(zoneAt([old, rated], 45.1, -121.9)?.id).toBe('nac:1');
		expect(zoneAt([old], 45.1, -121.9)?.id).toBe('nac:2');
	});

	it("reads today's ratings only from a current forecast", () => {
		expect(todayRatings(view(), '2026-12-10')).toEqual({ alpine: 3, treeline: 2, below: 1 });
		expect(todayRatings(view(), '2026-12-11')).toBeNull();
		expect(todayRatings(view({ status: 'expired' }), '2026-12-10')).toBeNull();
		const unrated = view({}, [{ date: '2026-12-10', alpine: null, treeline: null, below: null }]);
		expect(todayRatings(unrated, '2026-12-10')).toBeNull();
		expect(zoneLevel(square('a', 0, 0, 1, 1))).toBe(3);
		expect(zoneLevel(square('a', 0, 0, 1, 1, view({ status: 'no_rating' })))).toBe(0);
		expect(zonesGeojson([square('a', 0, 0, 1, 1)]).features[0].properties).toEqual({
			id: 'a',
			level: 3,
			status: 'current'
		});
	});
});

describe('treeline', () => {
	const data: Pick<ZonesOut, 'treeline' | 'treeline_spots' | 'spot_km'> = {
		treeline: [
			{ name: 'Mt Hood', center: 'NWAC', zone: 'Mt Hood', band: [1500, 2000] },
			{ name: 'NWAC', center: 'NWAC', band: [1200, 1550] },
			{ name: 'Coast', center: 'avcan', box: [49, -125, 51, -121], band: [1500, 1900] },
			{ name: 'Default', band: [1600, 2100] }
		],
		treeline_spots: [
			{ location_id: 'x', name: 'Whistler', lat: 50.06, lon: -122.95, band: [1550, 1850] }
		],
		spot_km: 40
	};

	it('takes the first rule that matches', () => {
		const hood = square('nac:1', -122, 45, -121, 46);
		expect(treelineAt(data, hood, 45.3, -121.7)).toEqual({
			band: [1500, 2000],
			name: 'Mt Hood',
			own: false
		});
		const other = square(
			'nac:2',
			-122,
			45,
			-121,
			46,
			view({ doc: { ...view().doc!, zone: 'Olympics' } })
		);
		expect(treelineAt(data, other, 45.3, -121.7).name).toBe('NWAC');
		const ca = square(
			'avcan:1',
			-125,
			49,
			-121,
			51,
			view({ doc: { ...view().doc!, center_id: 'avcan' } })
		);
		expect(treelineAt(data, ca, 49.5, -123.5).name).toBe('Coast');
		expect(treelineAt(data, ca, 52, -118).name).toBe('Default'); // outside the box
		expect(treelineAt(data, null, 40, -110).band).toEqual([1600, 2100]);
	});

	it("uses the owner's numbers near a location", () => {
		const ca = square(
			'avcan:1',
			-125,
			49,
			-121,
			51,
			view({ doc: { ...view().doc!, center_id: 'avcan' } })
		);
		expect(treelineAt(data, ca, 50.1, -122.9)).toEqual({
			band: [1550, 1850],
			name: 'Whistler',
			own: true
		});
	});

	it('turns bands into elevation ranges', () => {
		const tl: [number, number] = [1500, 2000];
		expect(bandOf(1499, tl)).toBe('below');
		expect(bandOf(1500, tl)).toBe('treeline');
		expect(bandOf(2000, tl)).toBe('alpine');
		expect(bandRanges(['alpine', 'treeline'], tl)).toEqual([[1500, 9000]]);
		expect(bandRanges(['alpine', 'below'], tl)).toEqual([
			[-500, 1500],
			[2000, 9000]
		]);
		const [wind, wet] = view().doc!.problems!;
		expect(problemRule(wind, tl)).toEqual({ aspects: ['N', 'NE', 'E'], ranges: [[1500, 9000]] });
		// No aspects or bands listed: everywhere.
		expect(problemRule(wet, tl)).toEqual({
			aspects: ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'],
			ranges: []
		});
		expect(
			concernProblem({ name: 'x', aspects: ['NE', 'bogus', 'N'], elevations: ['alpine', 'mid'] })
		).toEqual({
			name: 'x',
			aspects: ['N', 'NE'],
			bands: ['alpine']
		});
	});
});

describe('concern index', () => {
	const params: ConcernParams = {
		slope: [
			[25, 0.5],
			[30, 1],
			[46, 0.7],
			[56, 0.3]
		],
		matchListed: 1,
		matchOther: 0.6,
		matchNone: 0.8,
		windLoaded: 0.5,
		windScoured: -0.25,
		windEffect: 0.2,
		sun: 0.5,
		sunHours: 3,
		classes: [1.5, 2.5, 3.5]
	};
	const inputs: ConcernInputs = {
		danger: { alpine: 3, treeline: 2, below: 1 },
		treeline: [1500, 2000],
		problems: [{ name: 'Wind Slab', aspects: ['N', 'NE', 'E'], bands: ['alpine', 'treeline'] }],
		wind: true,
		windLoading: true,
		sun: false
	};
	const spot = { elev: 2200, slope: 38, aspect: 10, wind: null, sunHours: null };

	it('follows the slope table', () => {
		expect(
			[10, 24.9, 25, 29, 30, 45, 46, 55, 56, 70].map((d) => slopeFactor(d, params.slope))
		).toEqual([0, 0, 0.5, 0.5, 1, 1, 0.7, 0.7, 0.3, 0.3]);
	});

	// Each case: what changes from `spot` and `inputs`, then the score and class.
	const cases: [string, object, Partial<ConcernInputs>, number, number][] = [
		['listed problem, alpine, 38°', {}, {}, 3, 2],
		['same slope facing south: not listed', { aspect: 180 }, {}, 1.8, 1],
		['below treeline: the below rating, not listed', { elev: 1200 }, {}, 0.6, 0],
		['treeline band', { elev: 1700 }, {}, 2, 1],
		['gentle ground is not drawn', { slope: 20 }, {}, 0, -1],
		['25–29° counts half', { slope: 27 }, {}, 1.5, 1],
		['very steep counts less', { slope: 60 }, {}, 0.9, 0],
		['wind-loaded adds', { wind: 0.4 }, {}, 3.5, 3],
		['scoured takes away', { wind: -0.4 }, {}, 2.75, 2],
		['slight wind effect does nothing', { wind: 0.1 }, {}, 3, 2],
		['loading needs a reason', { wind: 0.4 }, { windLoading: false }, 3, 2],
		['scouring needs no reason', { wind: -0.4 }, { windLoading: false }, 2.75, 2],
		['no wind known: no wind factor', { wind: 0.4 }, { wind: false }, 3, 2],
		['sun on a wet day, south, 5 h', { aspect: 180, sunHours: 5 }, { sun: true }, 2.1, 1],
		['sun needs enough hours', { aspect: 180, sunHours: 2 }, { sun: true }, 1.8, 1],
		['sun only on E–W aspects', { sunHours: 5 }, { sun: true }, 3, 2],
		['no problems listed', {}, { problems: [] }, 2.4, 1],
		['no rating for the band', {}, { danger: { alpine: null, treeline: 2, below: 1 } }, 0, -1],
		['High danger, listed', {}, { danger: { alpine: 4, treeline: 4, below: 3 } }, 4, 3]
	];

	it.each(cases)('%s', (_name, s, inp, score, cls) => {
		const f = concernAt({ ...spot, ...s }, { ...inputs, ...inp }, params);
		expect(f.score).toBeCloseTo(score, 6);
		expect(f.cls).toBe(cls);
	});

	it('names the factors', () => {
		const f = concernAt({ ...spot, wind: 0.4 }, inputs, params);
		expect(f).toMatchObject({
			band: 'alpine',
			base: 3,
			slope: 1,
			match: 1,
			problem: 'Wind Slab',
			wind: 0.5,
			sun: 0
		});
	});

	it('classes and paints', () => {
		expect([0, 1, 1.5, 2.49, 2.5, 3.5, 6].map((s) => concernClass(s, params.classes))).toEqual([
			-1, 0, 1, 1, 2, 3, 3
		]);
		const px = paintConcern(Int8Array.from([-1, 0, 3]));
		expect(Array.from(px.slice(0, 4))).toEqual([0, 0, 0, 0]);
		expect(px[7]).toBeGreaterThan(0);
		expect(Array.from(px.slice(8, 11))).toEqual([0xc0, 0x17, 0x7c]);
	});

	it('reads problem names from both providers', () => {
		expect(
			[
				'Wind Slab',
				'Storm Slab',
				'Wet Loose',
				'Wet Slabs',
				'Glide Avalanches',
				'Persistent Slab',
				'Cornices'
			].map(problemKind)
		).toEqual(['wind', 'storm', 'wet', 'wet', 'wet', 'other', 'other']);
	});
});
