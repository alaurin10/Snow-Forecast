// The Observed tab's sentences: what the station's last month adds up to, and whether
// the forecast got it right.
import { describe, expect, it } from 'vitest';
import type { Snotel, SnotelDay, VerificationOut } from '../types.gen';
import { forecastVerdict, obsDays, stationRead } from './read';

const day = (i: number, over: Partial<SnotelDay> = {}): SnotelDay => {
	const d = new Date(Date.UTC(2026, 10, 1 + i)).toISOString().slice(0, 10);
	return { date: d, depth_cm: 50, swe_mm: 150, temp_c: -3, precip_mm: 0, ...over };
};

/** A station whose daily depths are `depths` (oldest first) and that reads `now` today. */
const station = (
	depths: (number | null)[],
	over: Partial<Snotel> = {},
	temps?: [number, number][]
): Snotel => ({
	triplet: '1:WA:SNTL',
	name: 'Test',
	elev_m: 1600,
	obs_time: null,
	depth_cm: depths.at(-1) ?? null,
	swe_mm: 150,
	change24_cm: null,
	change72_cm: null,
	daily: depths.map((d, i) =>
		day(i, {
			depth_cm: d,
			tmin_c: temps?.[i]?.[0] ?? null,
			tmax_c: temps?.[i]?.[1] ?? null
		})
	),
	...over
});

describe('new snow each day', () => {
	it('is the next morning’s depth gain, never a loss, with today running to the latest reading', () => {
		const days = obsDays(
			[day(0, { depth_cm: 10 }), day(1, { depth_cm: 25 }), day(2, { depth_cm: 20 })],
			{
				depth_cm: 26,
				swe_mm: null
			}
		);
		expect(days.map((d) => d.new_cm)).toEqual([15, 0, 6]);
	});

	it('counts snow water × 10 where there is no depth sensor', () => {
		const days = obsDays(
			[day(0, { depth_cm: null, swe_mm: 100 }), day(1, { depth_cm: null, swe_mm: 112 })],
			{ depth_cm: null, swe_mm: 112 }
		);
		expect(days.map((d) => d.new_cm)).toEqual([12, 0]);
	});
});

describe('the station in a sentence', () => {
	it('leads with the last three days when it snowed', () => {
		const r = stationRead(
			station([50, 50, 50, 50, 50, 50, 50, 50, 60, 70], { change24_cm: 4, change72_cm: 20 }),
			'metric'
		);
		expect(r.headline).toBe('20 cm of new snow in the last 3 days');
		expect(r.new24).toBe(4);
		expect(r.new72).toBe(20);
		expect(r.new7).toBe(20);
		expect(r.notes[0]).toBe('20 cm deeper than a week ago');
	});

	it('names the day of the week’s last snowfall', () => {
		// Nov 1–10 2026; 8 cm fell on Nov 5 (a Thursday), then it settled.
		const r = stationRead(station([40, 40, 40, 40, 40, 48, 47, 46, 45, 45]), 'metric');
		expect(r.headline).toBe('8 cm of new snow this week, most recently on Thu');
	});

	it('counts the days since the last snow, or says the ground is bare', () => {
		const dry = stationRead(station([60, 70, 70, 69, 68, 67, 66, 65, 64, 63, 62, 61]), 'imperial');
		expect(dry.headline).toBe('No new snow in 11 days');
		expect(dry.notes[0]).toBe('2.4 in shallower than a week ago');
		const bare = stationRead(station([0, 0, 0, 0, 0, 0, 0, 0]), 'metric');
		expect(bare.headline).toBe('No snow on the ground at the station');
		const month = stationRead(station(Array(30).fill(80)), 'metric');
		expect(month.headline).toBe('No new snow in over a month');
	});

	it('never counts settling as new snow', () => {
		const r = stationRead(
			station([50, 50, 50, 50, 50, 50, 50, 50, 50, 50], { change24_cm: -3, change72_cm: -6 }),
			'metric'
		);
		expect(r.new24).toBe(0);
		expect(r.new72).toBe(0);
	});

	it('says how many of the last seven days thawed', () => {
		const temps: [number, number][] = Array.from({ length: 10 }, (_, i) => [-8, i >= 7 ? 2 : -1]);
		const r = stationRead(station(Array(10).fill(50), {}, temps), 'metric');
		expect(r.thawDays).toBe(3);
		expect(r.notes).toContain('Above freezing on 3 of the last 7 days');
		const cold = stationRead(station(Array(10).fill(50), {}, Array(10).fill([-10, -2])), 'metric');
		expect(cold.notes).toContain('Below freezing all week');
		expect(stationRead(station(Array(10).fill(50)), 'metric').thawDays).toBeNull();
	});
});

const scores = (over: Partial<VerificationOut> = {}): VerificationOut => ({
	location_id: 'x',
	station: '1:WA:SNTL',
	station_name: 'Test',
	station_elev_m: 1600,
	band_elev_m: 1800,
	since: '2026-12-01',
	n_days: 4,
	ready: true,
	needs_days: 0,
	headline: 'cons_slr',
	rows: [
		{ source: 'cons_settled', n: 3, bias_cm: 2, mae_cm: 3, hits: 0, misses: 0, false_alarms: 0 }
	],
	water_rows: [
		{ source: 'cons', n: 4, bias_mm: -0.5, mae_mm: 2, hits: 0, misses: 0, false_alarms: 0 }
	],
	pairs: [
		{
			date: '2026-12-01',
			observed_cm: 10,
			from_swe: false,
			cons_cm: 0,
			cons_slr_cm: 0,
			cons_settled_cm: 12,
			observed_water_mm: 10,
			cons_water_mm: 9
		},
		{
			date: '2026-12-02',
			observed_cm: 0,
			from_swe: false,
			cons_cm: 0,
			cons_slr_cm: 0,
			cons_settled_cm: 4,
			observed_water_mm: 0,
			cons_water_mm: 1
		},
		{
			date: '2026-12-03',
			observed_cm: 5,
			from_swe: false,
			cons_cm: 0,
			cons_slr_cm: 0,
			cons_settled_cm: 5,
			observed_water_mm: 6,
			cons_water_mm: 6
		},
		{
			date: '2026-12-04',
			observed_cm: 0,
			from_swe: false,
			cons_cm: 0,
			cons_slr_cm: 0,
			cons_settled_cm: 9,
			skip: 'warm',
			observed_water_mm: 8,
			cons_water_mm: 7
		}
	],
	...over
});

describe('did the forecast get it right?', () => {
	it('sums the scored days and says which way it leans', () => {
		const v = forecastVerdict(scores(), 'metric')!;
		expect(v.kind).toBe('snow');
		expect(v.days).toBe(3); // the warm day is left out
		expect(v.forecast).toBe(21);
		expect(v.observed).toBe(15);
		expect(v.lean).toBe('high');
		expect(v.sentence).toBe(
			'Forecast more snow than fell, by about 2 cm a day; a typical day was off by 3 cm.'
		);
	});

	it('uses the forecast at the station once it has a week', () => {
		const data = scores({
			rows: [
				{
					source: 'cons_settled',
					n: 7,
					bias_cm: 2,
					mae_cm: 3,
					hits: 0,
					misses: 0,
					false_alarms: 0
				},
				{
					source: 'stn_settled',
					n: 7,
					bias_cm: -0.2,
					mae_cm: 1,
					hits: 0,
					misses: 0,
					false_alarms: 0
				}
			]
		});
		data.pairs = data.pairs.map((p) => ({ ...p, stn_settled_cm: 5 }));
		const v = forecastVerdict(data, 'metric')!;
		expect(v.forecast).toBe(15);
		expect(v.lean).toBe('close');
		expect(v.sentence).toBe('About right on balance; a typical day was off by 1 cm.');
	});

	it('falls back to the gauge while the depth can check nothing, and waits until ready', () => {
		const v = forecastVerdict(scores({ n_days: 0 }), 'metric')!;
		expect(v.kind).toBe('water');
		expect(v.days).toBe(4);
		expect(v.forecast).toBe(23);
		expect(v.observed).toBe(24);
		expect(v.lean).toBe('close');
		expect(forecastVerdict(scores({ ready: false }), 'metric')).toBeNull();
	});
});
