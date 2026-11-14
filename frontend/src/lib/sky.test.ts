// The sky: weather from the current hour (codes, wind, what falls), the light from the
// sun's place (sunrise and sunset), and the icon that goes with them.
import { describe, expect, it } from 'vitest';
import {
	darkPhase,
	hourIndex,
	pastData,
	pickScene,
	PREVIEW_SKIES,
	sceneIcon,
	skyLabel,
	skyOf,
	sunAt,
	weatherAt,
	WEATHERS,
	type Weather
} from './sky';
import type { HourlyOut, Snapshot, SunDay } from './types.gen';

/** Three hours from 2 PM, with the given values for every hour unless overridden. */
function hours(v: Partial<Record<keyof HourlyOut, (number | null)[]>> = {}): HourlyOut {
	const t = ['2026-11-04T14:00-07:00', '2026-11-04T15:00-07:00', '2026-11-04T16:00-07:00'];
	const fill = (x: number) => t.map(() => x);
	return {
		t,
		snow_cm: fill(0),
		rain_mm: fill(0),
		cloud: fill(0),
		wcode: fill(0),
		is_day: fill(1),
		wind_kmh: fill(5),
		gust_kmh: fill(10),
		wdir: fill(270),
		...v
	} as unknown as HourlyOut;
}
const day = (date: string, rise: string, set: string): SunDay => ({
	date,
	sunrise: `${date}T${rise}-07:00`,
	sunset: `${date}T${set}-07:00`,
	daylight_s: 36000
});
const sun: SunDay[] = [
	day('2026-11-03', '07:00', '17:00'),
	day('2026-11-04', '07:00', '17:00'),
	day('2026-11-05', '07:00', '17:00')
];
const at = (hhmm: string, date = '2026-11-04') => Date.parse(`${date}T${hhmm}-07:00`);

describe('weatherAt', () => {
	const w = (v: Parameters<typeof hours>[0]) => weatherAt(hours(v), 0);

	it('reads cloud cover when nothing falls', () => {
		expect(w({})).toBe('clear');
		expect(w({ cloud: [50, 50, 50] })).toBe('partly');
		expect(w({ cloud: [95, 95, 95] })).toBe('overcast');
		expect(w({ wcode: [45, 45, 45] })).toBe('fog');
	});

	it('puts what falls ahead of cloud', () => {
		expect(w({ snow_cm: [0.3, 0, 0], cloud: [100, 100, 100] })).toBe('snow');
		expect(w({ snow_cm: [1, 1, 0.5] })).toBe('heavy');
		expect(w({ snow_cm: [0.3, 0, 0], rain_mm: [0.5, 0, 0] })).toBe('mixed');
	});

	it('tells drizzle from rain, by code first and amount second', () => {
		expect(w({ rain_mm: [0.3, 0, 0] })).toBe('drizzle');
		expect(w({ rain_mm: [1.2, 0, 0] })).toBe('rain');
		expect(w({ rain_mm: [1.2, 0, 0], wcode: [53, 53, 53] })).toBe('drizzle');
		expect(w({ rain_mm: [0.3, 0, 0], wcode: [63, 63, 63] })).toBe('rain');
		expect(w({ rain_mm: [0.1, 0, 0], wcode: [51, 51, 51] })).toBe('drizzle');
		expect(w({ rain_mm: [0.1, 0, 0] })).toBe('clear');
	});

	it('makes thunderstorm codes (95–99) a storm, whatever falls', () => {
		for (const code of [95, 96, 99])
			expect(w({ wcode: [code, 0, 0], rain_mm: [3, 0, 0] })).toBe('storm');
		expect(w({ wcode: [94, 0, 0], cloud: [100, 0, 0] })).toBe('overcast');
	});

	it('lifts falling or fresh snow into blowing snow in strong wind', () => {
		expect(w({ snow_cm: [0.3, 0, 0], wind_kmh: [40, 40, 40] })).toBe('blowing');
		expect(w({ snow_cm: [0.3, 0, 0], gust_kmh: [60, 60, 60] })).toBe('blowing');
		// Fresh snow from earlier hours, nothing falling now.
		const h = hours({ snow_cm: [0.6, 0.6, 0], wind_kmh: [10, 10, 45] });
		expect(weatherAt(h, 2)).toBe('blowing');
		// Wind with no snow about is just wind.
		expect(w({ wind_kmh: [50, 50, 50] })).toBe('clear');
		// Heavy snow stays heavy snow.
		expect(w({ snow_cm: [1, 1, 0.5], wind_kmh: [50, 50, 50] })).toBe('heavy');
	});
});

describe('sunAt', () => {
	it('names the light by minutes from sunrise and sunset', () => {
		expect(sunAt(sun, at('03:00')).phase).toBe('night');
		expect(sunAt(sun, at('06:40')).phase).toBe('dawn');
		expect(sunAt(sun, at('07:10')).phase).toBe('dawn');
		expect(sunAt(sun, at('07:40')).phase).toBe('golden');
		expect(sunAt(sun, at('12:00')).phase).toBe('day');
		expect(sunAt(sun, at('16:00')).phase).toBe('golden');
		expect(sunAt(sun, at('16:50')).phase).toBe('dusk');
		expect(sunAt(sun, at('17:30')).phase).toBe('dusk');
		expect(sunAt(sun, at('18:00')).phase).toBe('night');
	});

	it('gives a sun height that rises through the morning and goes negative after dark', () => {
		const alts = ['06:00', '07:00', '08:00', '10:00', '12:00'].map((t) => sunAt(sun, at(t)).alt);
		for (let i = 1; i < alts.length; i++) expect(alts[i]).toBeGreaterThanOrEqual(alts[i - 1]);
		expect(sunAt(sun, at('07:00')).alt).toBe(0);
		expect(sunAt(sun, at('12:00')).alt).toBe(1);
		expect(sunAt(sun, at('22:00')).alt).toBe(-1);
		expect(sunAt(sun, at('17:45')).alt).toBeCloseTo(-0.5);
	});

	it('runs the arc across the day, and across the night through midnight', () => {
		expect(sunAt(sun, at('12:00')).arc).toBeCloseTo(0.5);
		expect(sunAt(sun, at('12:00')).night).toBe(false);
		// Sunset 17:00 to sunrise 07:00 is 14 hours; midnight is half way.
		const mid = sunAt(sun, at('00:00', '2026-11-05'));
		expect(mid).toMatchObject({ phase: 'night', night: true });
		expect(mid.arc).toBeCloseTo(0.5);
	});

	it("falls back to the hour's day/night flag without sunrise and sunset", () => {
		expect(sunAt([], at('12:00'), true)).toMatchObject({ phase: 'day', night: false });
		expect(sunAt([], at('12:00'), false)).toMatchObject({ phase: 'night', night: true });
		const polar: SunDay[] = [{ date: '2026-11-04', sunrise: null, sunset: null, daylight_s: 0 }];
		expect(sunAt(polar, at('12:00'), false).phase).toBe('night');
	});
});

describe('pickScene', () => {
	it('combines the weather and the light', () => {
		const dark = hours({ snow_cm: [0.4, 0, 0], is_day: [0, 0, 0] });
		dark.t = ['2026-11-04T21:00-07:00', '2026-11-04T22:00-07:00', '2026-11-04T23:00-07:00'];
		expect(pickScene(dark, sun)).toMatchObject({
			weather: 'snow',
			phase: 'night',
			night: true,
			label: 'Light snow'
		});
	});

	it('names a clear sky by the light: alpenglow at dawn and dusk, clear night after dark', () => {
		const h = hours();
		expect(pickScene(h, sun, 0, at('17:20')).label).toBe('Alpenglow');
		expect(pickScene(h, sun, 0, at('20:00')).label).toBe('Clear night');
		expect(pickScene(h, sun, 0, at('12:00')).label).toBe('Clear');
		// A partly cloudy dusk keeps its name.
		expect(pickScene(hours({ cloud: [50, 50, 50] }), sun, 0, at('17:20')).label).toBe(
			'Partly cloudy'
		);
	});

	it('carries the wind for the motion', () => {
		const s = pickScene(hours({ wind_kmh: [30, 0, 0], wdir: [200, 0, 0] }), sun);
		expect(s).toMatchObject({ wind: 30, wdir: 200 });
	});

	it('finds the hour holding now, from an ISO time or a clock', () => {
		const h = hours();
		expect(hourIndex(h, '2026-11-04T15:20-07:00')).toBe(1);
		expect(hourIndex(h, at('16:59'))).toBe(2);
		expect(hourIndex(h, null)).toBe(0);
	});
});

describe('skyOf and the clock', () => {
	const snap = (h: HourlyOut): Snapshot =>
		({
			now: '2026-11-04T14:00-07:00',
			sun,
			bands: [{ hourly: h }, { hourly: h }, { hourly: h }]
		}) as unknown as Snapshot;
	const h = hours({ cloud: [0, 50, 95] });

	it('follows the clock through the hours, never before the forecast’s now', () => {
		const s = snap(h);
		expect(skyOf(s).weather).toBe('clear');
		expect(skyOf(s, at('15:10')).weather).toBe('partly');
		expect(skyOf(s, at('16:30'))).toMatchObject({ weather: 'overcast', phase: 'golden' });
		// A slow clock shows the forecast's own hour.
		expect(skyOf(s, at('09:00')).weather).toBe('clear');
	});

	it('knows when the clock has run past the data', () => {
		const s = snap(h);
		expect(pastData(s, at('16:30'))).toBe(false);
		expect(pastData(s, at('17:00'))).toBe(true);
	});
});

describe('sceneIcon', () => {
	const icon = (weather: Weather, night = false) => sceneIcon({ weather, night });
	it('gives every weather an icon', () => {
		expect(Object.fromEntries(WEATHERS.map((w) => [w, icon(w)]))).toEqual({
			clear: 'clear-day',
			partly: 'partly-day',
			overcast: 'cloud',
			fog: 'fog',
			drizzle: 'rain',
			rain: 'rain',
			storm: 'thunder',
			mixed: 'mix',
			snow: 'snow',
			heavy: 'snow',
			blowing: 'snow'
		});
	});
	it('draws the moon after dark', () => {
		expect(icon('clear', true)).toBe('clear-night');
		expect(icon('partly', true)).toBe('partly-night');
		expect(icon('snow', true)).toBe('snow');
	});
});

describe('labels and phases', () => {
	it('names every weather', () => {
		for (const w of WEATHERS) expect(skyLabel(w, 'day')).toMatch(/^[A-Z]/);
	});
	it('goes dark (in Auto) at dusk and night only', () => {
		expect(['night', 'dawn', 'day', 'golden', 'dusk'].filter((p) => darkPhase(p as never))).toEqual(
			['night', 'dusk']
		);
	});
	it('previews every weather and every light', () => {
		expect(new Set(PREVIEW_SKIES.map((s) => s.weather))).toEqual(new Set(WEATHERS));
		expect(new Set(PREVIEW_SKIES.map((s) => s.phase)).size).toBe(5);
	});
});
