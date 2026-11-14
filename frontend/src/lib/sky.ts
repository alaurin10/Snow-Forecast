// The weather behind the page, on two axes: the weather at the location's current hour
// (clear … blowing snow) and where the sun is (night, dawn, day, golden hour, dusk),
// worked out from that day's sunrise and sunset. The sky never follows the chart while
// you scrub; it follows the clock (see skystate.svelte.ts), so an open tab goes from day
// to dusk to night on its own.
import type { WxIcon } from './periodwx';
import type { HourlyOut, Snapshot, SunDay } from './types.gen';

export type Weather =
	| 'clear'
	| 'partly'
	| 'overcast'
	| 'fog'
	| 'drizzle'
	| 'rain'
	| 'storm'
	| 'mixed'
	| 'snow'
	| 'heavy'
	| 'blowing';
export const WEATHERS: readonly Weather[] = [
	'clear',
	'partly',
	'overcast',
	'fog',
	'drizzle',
	'rain',
	'storm',
	'mixed',
	'snow',
	'heavy',
	'blowing'
] as const;

export type Phase = 'night' | 'dawn' | 'day' | 'golden' | 'dusk';
export const PHASES: readonly Phase[] = ['night', 'dawn', 'day', 'golden', 'dusk'] as const;

export interface SkyState {
	weather: Weather;
	phase: Phase;
	/** How high the sun is, roughly: 0 on the horizon, 1 three hours or more above it,
	 *  −1 an hour and a half or more below it. Colours follow it continuously. */
	alt: number;
	/** How far through the current day (sunrise → sunset) or night (sunset → sunrise),
	 *  0 to 1: the sun's or the moon's place along its arc. */
	arc: number;
	/** The sun is down: the moon and stars show, and the icons draw the moon. */
	night: boolean;
	/** Wind at the hour, km/h, and the direction it blows from (degrees), for motion. */
	wind: number;
	wdir: number | null;
	/** A short phrase for the sky, e.g. "Light snow" or "Clear night". */
	label: string;
}

export const WEATHER_LABEL: Record<Weather, string> = {
	clear: 'Clear',
	partly: 'Partly cloudy',
	overcast: 'Overcast',
	fog: 'Fog',
	drizzle: 'Drizzle',
	rain: 'Rain',
	storm: 'Thunderstorm',
	mixed: 'Rain and snow',
	snow: 'Light snow',
	heavy: 'Heavy snow',
	blowing: 'Blowing snow'
};

export const PHASE_LABEL: Record<Phase, string> = {
	night: 'Night',
	dawn: 'Dawn',
	day: 'Day',
	golden: 'Golden hour',
	dusk: 'Dusk'
};

/** The words for a sky: the weather, with the light where it changes the name. */
export function skyLabel(weather: Weather, phase: Phase): string {
	if (weather === 'clear' && phase === 'night') return 'Clear night';
	if (weather === 'clear' && (phase === 'dawn' || phase === 'dusk')) return 'Alpenglow';
	return WEATHER_LABEL[weather];
}

/** The weather icon for a sky: the conditions pill shows it in place of the words, so the
 *  pill and the backdrop always agree. */
export function sceneIcon(sky: Pick<SkyState, 'weather' | 'night'>): WxIcon {
	switch (sky.weather) {
		case 'clear':
			return sky.night ? 'clear-night' : 'clear-day';
		case 'partly':
			return sky.night ? 'partly-night' : 'partly-day';
		case 'overcast':
			return 'cloud';
		case 'fog':
			return 'fog';
		case 'drizzle':
		case 'rain':
			return 'rain';
		case 'storm':
			return 'thunder';
		case 'mixed':
			return 'mix';
		case 'snow':
		case 'heavy':
		case 'blowing':
			return 'snow';
	}
}

/** Night and dusk want dark text on light glass turned round: Auto mode goes dark. */
export const darkPhase = (p: Phase) => p === 'night' || p === 'dusk';

/** The calm default before any forecast has loaded. */
export const DEFAULT_SKY: SkyState = {
	weather: 'partly',
	phase: 'day',
	alt: 1,
	arc: 0.5,
	night: false,
	wind: 0,
	wdir: null,
	label: WEATHER_LABEL.partly
};

/** Snow over the next three hours that counts as heavy: 0.9 in. */
const HEAVY_3H_CM = 2.29;
/** Wind that lifts snow off the ground: sustained, or in gusts. */
const BLOW_KMH = 35;
const BLOW_GUST_KMH = 55;
/** Minutes from the horizon at which the light changes. */
const NIGHT_MIN = 40; // below the horizon: dawn starts / dusk ends
const LOW_MIN = 20; // above it: dawn or dusk becomes golden hour
const GOLDEN_MIN = 70; // above it: golden hour becomes day
/** Minutes over which the sun's height runs 0 → 1 (above) and 0 → −1 (below). */
const ALT_UP_MIN = 180;
const ALT_DOWN_MIN = 90;

const num = (v: number | null | undefined) => (typeof v === 'number' ? v : 0);
const clamp = (x: number, a: number, b: number) => Math.min(b, Math.max(a, x));
const isCode = (c: number | null | undefined, ...ranges: [number, number][]) =>
	typeof c === 'number' && ranges.some(([a, b]) => c >= a && c <= b);

/** The weather at hour `i`: what falls first, then how cloudy. */
export function weatherAt(h: HourlyOut, i: number): Weather {
	const snow = num(h.snow_cm[i]);
	const rain = num(h.rain_mm[i]);
	const code = h.wcode[i];
	const wind = num(h.wind_kmh?.[i]);
	const gust = num(h.gust_kmh?.[i]);
	let snow3 = 0;
	for (let k = i; k < Math.min(i + 3, h.t.length); k++) snow3 += num(h.snow_cm[k]);
	// Snow on the ground from the last 12 hours, for the wind to pick up.
	let snow12 = 0;
	for (let k = Math.max(0, i - 11); k <= i; k++) snow12 += num(h.snow_cm[k]);
	const windy = wind >= BLOW_KMH || gust >= BLOW_GUST_KMH;

	if (isCode(code, [95, 99])) return 'storm';
	if (snow3 >= HEAVY_3H_CM) return 'heavy';
	if (windy && (snow > 0.05 || snow12 >= 1)) return 'blowing';
	if (snow > 0.05 && rain >= 0.3) return 'mixed';
	if (snow > 0.05) return 'snow';
	const drizzleCode = isCode(code, [51, 57]);
	const rainCode = isCode(code, [61, 67], [80, 82]);
	if (rain >= 0.2 || ((drizzleCode || rainCode) && rain > 0.05))
		return drizzleCode || (!rainCode && rain < 0.5) ? 'drizzle' : 'rain';
	if (code === 45 || code === 48) return 'fog';
	const cloud = num(h.cloud[i]);
	if (cloud >= 85) return 'overcast';
	if (cloud >= 35) return 'partly';
	return 'clear';
}

/** Where the sun is at time `t` (ms), from the days' sunrises and sunsets. Without them
 *  (none for that day, or the sun doesn't rise or set) the hour's day/night flag decides. */
export function sunAt(
	sun: SunDay[],
	t: number,
	isDay = true
): Pick<SkyState, 'phase' | 'alt' | 'arc' | 'night'> {
	const events: { t: number; rise: boolean }[] = [];
	for (const d of sun) {
		if (d.sunrise) events.push({ t: Date.parse(d.sunrise), rise: true });
		if (d.sunset) events.push({ t: Date.parse(d.sunset), rise: false });
	}
	events.sort((a, b) => a.t - b.t);
	let last: (typeof events)[number] | undefined;
	let next: (typeof events)[number] | undefined;
	for (const e of events) {
		if (e.t <= t) last = e;
		else {
			next = e;
			break;
		}
	}
	// Only a sunrise → sunset or sunset → sunrise pair says where we are.
	if (!last || !next || last.rise === next.rise || next.t - last.t > 30 * 3600e3) {
		return isDay
			? { phase: 'day', alt: 1, arc: 0.5, night: false }
			: { phase: 'night', alt: -1, arc: 0.5, night: true };
	}
	const day = last.rise;
	const arc = clamp((t - last.t) / (next.t - last.t), 0, 1);
	const toEvent = next.t - t;
	const fromEvent = t - last.t;
	// Minutes from the nearer horizon crossing: above it by day, below it by night.
	const mins = Math.min(toEvent, fromEvent) / 60_000;
	// By day, the morning half is after sunrise; by night, the morning half is before it.
	const morning = day ? fromEvent < toEvent : toEvent < fromEvent;
	if (day) {
		const alt = clamp(mins / ALT_UP_MIN, 0, 1);
		const phase: Phase =
			mins >= GOLDEN_MIN ? 'day' : mins >= LOW_MIN ? 'golden' : morning ? 'dawn' : 'dusk';
		return { phase, alt, arc, night: false };
	}
	const alt = -clamp(mins / ALT_DOWN_MIN, 0, 1);
	const phase: Phase = mins >= NIGHT_MIN ? 'night' : morning ? 'dawn' : 'dusk';
	return { phase, alt, arc, night: true };
}

/** The sky at hour `at` of the hourly series, at time `t` (ms; the hour's start if not
 *  given) for the sun. */
export function pickScene(h: HourlyOut, sun: SunDay[] = [], at = 0, t?: number): SkyState {
	if (!h.t.length) return DEFAULT_SKY;
	const i = clamp(at, 0, h.t.length - 1);
	const weather = weatherAt(h, i);
	const s = sunAt(sun, t ?? Date.parse(h.t[i]), h.is_day[i] !== 0);
	return {
		weather,
		...s,
		wind: num(h.wind_kmh?.[i]),
		wdir: h.wdir?.[i] ?? null,
		label: skyLabel(weather, s.phase)
	};
}

/** The time a snapshot is shown at: the clock, but never before the forecast's own "now"
 *  (a clock running slow mustn't show an hour that's already gone from the data). */
export function shownAt(snap: Snapshot, clock: number): number {
	return Math.max(Date.parse(snap.now) || 0, clock);
}

/** A location's sky at time `clock` (ms; the forecast's "now" if not given), at
 *  mid-mountain. */
export function skyOf(snap: Snapshot, clock?: number): SkyState {
	const band = snap.bands[1] ?? snap.bands[0];
	if (!band) return DEFAULT_SKY;
	const t = clock === undefined ? Date.parse(snap.now) : shownAt(snap, clock);
	return pickScene(band.hourly, snap.sun ?? [], hourIndex(band.hourly, t), t);
}

/** The clock has run past the snapshot's hours: time to fetch a newer one. */
export function pastData(snap: Snapshot, clock: number): boolean {
	const band = snap.bands[1] ?? snap.bands[0];
	const last = band?.hourly.t.at(-1);
	return !!last && clock >= Date.parse(last) + 3600e3;
}

/** Index of the hour holding `now` (an ISO time or ms; 0 if none). */
export function hourIndex(h: HourlyOut, now: string | number | null | undefined): number {
	if (now === null || now === undefined) return 0;
	const t = typeof now === 'number' ? now : Date.parse(now);
	let k = 0;
	for (let i = 0; i < h.t.length; i++) if (Date.parse(h.t[i]) <= t) k = i;
	return k;
}

/** A typical sky for a weather and a light, for the Settings preview. */
export function sampleSky(weather: Weather, phase: Phase, wind = 10): SkyState {
	const at: Record<Phase, Pick<SkyState, 'alt' | 'arc' | 'night'>> = {
		night: { alt: -1, arc: 0.4, night: true },
		dawn: { alt: -0.1, arc: 0.97, night: true },
		day: { alt: 1, arc: 0.45, night: false },
		golden: { alt: 0.25, arc: 0.9, night: false },
		dusk: { alt: -0.1, arc: 0.03, night: true }
	};
	return { weather, phase, ...at[phase], wind, wdir: 250, label: skyLabel(weather, phase) };
}

/** The skies the Settings preview steps through. */
export const PREVIEW_SKIES: readonly SkyState[] = [
	sampleSky('clear', 'day'),
	sampleSky('clear', 'golden'),
	sampleSky('clear', 'dusk'),
	sampleSky('clear', 'night'),
	sampleSky('partly', 'day', 20),
	sampleSky('partly', 'night'),
	sampleSky('overcast', 'day', 25),
	sampleSky('fog', 'dawn', 3),
	sampleSky('drizzle', 'day', 12),
	sampleSky('rain', 'day', 35),
	sampleSky('storm', 'dusk', 45),
	sampleSky('mixed', 'day', 20),
	sampleSky('snow', 'day', 8),
	sampleSky('snow', 'night', 10),
	sampleSky('heavy', 'dusk', 25),
	sampleSky('blowing', 'day', 55)
];
