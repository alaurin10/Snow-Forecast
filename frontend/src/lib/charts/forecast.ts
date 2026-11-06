// Data for the all-in-one forecast chart: the band's hourly series grouped into
// steps whose size follows the chosen range (hourly for a day, day and night
// halves for 10+ days). Values stay metric; the chart converts for display.
import type { HourlyOut } from '../types.gen';
import { HEAVY_CM, type PrecipKind } from '../daybars';
import { dateOf, hourOf } from '../time';

export type Metric = 'precip' | 'temp' | 'wind' | 'cloud' | 'fl';
export const RANGES = [1, 3, 5, 10, 15] as const;
/** Snow-to-liquid ratio used to show rain on the snow scale. */
export const SLR = 10;
export type Range = (typeof RANGES)[number];
/** Hours per step for each range. */
export const STEP: Record<Range, number> = { 1: 1, 3: 3, 5: 6, 10: 12, 15: 12 };

export interface Step {
	/** Index of the step's first hour in the hourly arrays. */
	i0: number;
	t: string;
	hours: number;
	night: boolean;
	/**
	 * All precipitation as snow depth (cm): snow as it falls, rain at the snow it would
	 * make at 10:1. One scale, in inches of snow, for every bar.
	 */
	precip: number;
	kind: PrecipKind;
	/** Snow depth (cm) and rain as liquid (cm), kept apart because their inches differ. */
	snow: number;
	rain: number;

	/** Running total of snow (cm) from the chart's first step. */
	cum: number;
	temp: number | null;
	/** Day halves of 12 h steps show the high, nights the low. */
	tempKind: 'mean' | 'high' | 'low';
	/** Spread across the weather models (the range band on the chart). */
	tempLo: number | null;
	tempHi: number | null;
	flLo: number | null;
	flHi: number | null;
	/** Highest chance of precipitation in the step (%). */
	pop: number | null;
	/** Cloud cover by height (%): low below about 3 km, mid 3–8 km, high above. */
	cloudLow: number | null;
	cloudMid: number | null;
	cloudHigh: number | null;
	wind: number | null;
	gust: number | null;
	dir: number | null;
	cloud: number | null;
	fl: number | null;
}

/** Ranges the data can fill. */
export function availableRanges(hours: number): Range[] {
	return RANGES.filter((r) => r * 24 <= hours);
}

const num = (v: number | null | undefined): v is number => v !== null && v !== undefined;
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const max = (xs: number[]) => (xs.length ? Math.max(...xs) : null);
const min = (xs: number[]) => (xs.length ? Math.min(...xs) : null);

/** The model range for a step's temperature: the spread of the highs, the lows, or the means. */
function band(lo: number[], hi: number[], kind: Step['tempKind']) {
	const f = kind === 'high' ? max : kind === 'low' ? min : mean;
	return { tempLo: f(lo), tempHi: f(hi) };
}

/** Snow (cm) per calendar date, for the 6+ in heavy-snow rule. */
function dailySnow(h: HourlyOut): Map<string, number> {
	const out = new Map<string, number>();
	h.t.forEach((t, i) => out.set(dateOf(t), (out.get(dateOf(t)) ?? 0) + (h.snow_cm[i] ?? 0)));
	return out;
}

export function buildSteps(h: HourlyOut, range: Range): Step[] {
	const step = STEP[range];
	const len = h.t.length;
	// Start on a clean boundary: any hour, every 3 or 6 h from midnight, or 6 AM / 6 PM.
	const aligned = (i: number) => {
		const hr = hourOf(h.t[i]);
		return step === 1 || (step === 12 ? hr % 12 === 6 : hr % step === 0);
	};
	let start = 0;
	while (start < len && !aligned(start)) start++;
	const n = Math.min((range * 24) / step, Math.floor((len - start) / step));
	const daily = dailySnow(h);
	const steps: Step[] = [];
	let cum = 0;
	for (let k = 0; k < n; k++) {
		const i0 = start + k * step;
		const idx = Array.from({ length: step }, (_, j) => i0 + j);
		const mid = i0 + Math.floor(step / 2);
		// One type per step, from how much of the snow-equivalent total is rain:
		// under a fifth is snow, over four fifths is rain, anything between is mixed.
		let snow = 0;
		let rainCm = 0;
		for (const i of idx) {
			snow += h.snow_cm[i] ?? 0;
			rainCm += (h.rain_mm[i] ?? 0) / 10;
		}
		cum += snow;
		const asSnow = snow + rainCm * SLR;
		const rainShare = asSnow > 0 ? (rainCm * SLR) / asSnow : 0;
		let kind: PrecipKind =
			asSnow < 0.05 ? 'none' : rainShare < 0.2 ? 'snow' : rainShare > 0.8 ? 'rain' : 'mix';
		// Orange is for snow only, on a 6+ in day.
		if (kind === 'snow' && (daily.get(dateOf(h.t[mid])) ?? 0) >= HEAVY_CM) kind = 'heavy';
		const temps = idx.map((i) => h.temp_c[i]).filter(num);
		const night = h.is_day[mid] === 0;
		const tempKind = step === 12 ? (night ? 'low' : 'high') : 'mean';
		steps.push({
			i0,
			t: h.t[i0],
			hours: step,
			night,
			precip: asSnow,
			kind,
			snow,
			rain: rainCm,
			cum,
			temp: tempKind === 'high' ? max(temps) : tempKind === 'low' ? min(temps) : mean(temps),
			tempKind,
			...band(
				idx.map((i) => h.temp_lo?.[i]).filter(num),
				idx.map((i) => h.temp_hi?.[i]).filter(num),
				tempKind
			),
			flLo: mean(idx.map((i) => h.fl_lo?.[i]).filter(num)),
			flHi: mean(idx.map((i) => h.fl_hi?.[i]).filter(num)),
			pop: max(idx.map((i) => h.pop?.[i]).filter(num)),
			cloudLow: mean(idx.map((i) => h.cloud_low?.[i]).filter(num)),
			cloudMid: mean(idx.map((i) => h.cloud_mid?.[i]).filter(num)),
			cloudHigh: mean(idx.map((i) => h.cloud_high?.[i]).filter(num)),
			wind: max(idx.map((i) => h.wind_kmh[i]).filter(num)),
			gust: max(idx.map((i) => h.gust_kmh[i]).filter(num)),
			dir: h.wdir[mid] ?? null,
			cloud: mean(idx.map((i) => h.cloud[i]).filter(num)),
			fl: mean(idx.map((i) => h.fl_m[i]).filter(num))
		});
	}
	return steps;
}

/** A tidy axis: about `count` round steps covering [lo, hi]. */
export function niceAxis(
	lo: number,
	hi: number,
	count = 5
): { min: number; max: number; ticks: number[] } {
	if (!(hi > lo)) hi = lo + 1;
	const raw = (hi - lo) / count;
	const mag = 10 ** Math.floor(Math.log10(raw));
	const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
	const a = Math.floor(lo / step) * step;
	const b = Math.ceil(hi / step) * step;
	const ticks: number[] = [];
	for (let v = a; v <= b + step / 1e6; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
	return { min: a, max: b, ticks };
}
