// How sure the forecast is, read from what the snapshot already holds: the ensembles'
// 10–90% range against the consensus, each model's own total, and how the consensus
// has moved over the last runs. Pure, so the rules are easy to test and to change.
import type { BandOut, DailyRow, TrendRun } from './types.gen';

export type Confidence = 'high' | 'medium' | 'low';

export const CONFIDENCE_WORD: Record<Confidence, string> = {
	high: 'High',
	medium: 'Medium',
	low: 'Low'
};

/** A range this narrow (2 in) is agreement, whatever the total. */
export const AGREE_CM = 5;
/** Small totals are judged against this (4 in), so 1 cm vs 3 cm isn't "they disagree". */
const FLOOR_CM = 10;
/** The range as a share of the total: up to this is high confidence… */
const HIGH = 0.75;
/** …up to this is medium, wider is low. */
const MEDIUM = 1.5;
/** A total that moved less than this (1 in) between runs held steady. */
export const STEADY_CM = 2.5;

/**
 * Confidence from a likely range (the ensembles' 10–90%, or the models' lowest and
 * highest) around a total. Null when there is no range to judge by.
 */
export function confidenceOf(
	center: number | null | undefined,
	lo: number | null | undefined,
	hi: number | null | undefined
): Confidence | null {
	if (lo === null || lo === undefined || hi === null || hi === undefined) return null;
	const spread = Math.max(0, hi - lo);
	if (spread <= AGREE_CM) return 'high';
	const rel = spread / Math.max(center ?? 0, FLOOR_CM);
	return rel <= HIGH ? 'high' : rel <= MEDIUM ? 'medium' : 'low';
}

export interface ModelTotal {
	model: string;
	cm: number;
}

export type WindowKey = 'next5' | 'd6_10';

/** The periods each window covers (as the server's `WINDOWS`). */
const WINDOW_PERIODS: Record<WindowKey, [number, number]> = { next5: [0, 10], d6_10: [10, 20] };
export const WINDOW_LABEL: Record<WindowKey, string> = {
	next5: 'Next 5 days',
	d6_10: 'Days 6–10'
};

export interface WindowRead {
	key: WindowKey;
	label: string;
	/** The consensus total. */
	snow_cm: number | null;
	/** The likely range, and where it comes from. */
	lo: number | null;
	hi: number | null;
	basis: 'ensemble' | 'models' | null;
	/** The ensemble range is scaled from mid-mountain, not run at this elevation. */
	estimated: boolean;
	/** Each model that covers the whole window, least snow first. */
	models: ModelTotal[];
	confidence: Confidence | null;
}

/** One window at one elevation: the total, its likely range and each model's total. */
export function windowRead(band: BandOut, key: WindowKey): WindowRead {
	const w = band.windows[key];
	const [a, b] = WINDOW_PERIODS[key];
	const periods = band.periods.slice(a, b);
	const sums: Record<string, number> = {};
	const seen: Record<string, number> = {};
	for (const p of periods) {
		for (const [m, v] of Object.entries(p.models)) {
			if (v === null || v === undefined) continue;
			sums[m] = (sums[m] ?? 0) + v;
			seen[m] = (seen[m] ?? 0) + 1;
		}
	}
	const models = Object.keys(sums)
		.filter((m) => periods.length > 0 && seen[m] === periods.length)
		.map((m) => ({ model: m, cm: sums[m] }))
		.sort((x, y) => x.cm - y.cm);
	const ens = w?.ens ?? null;
	let lo: number | null = null;
	let hi: number | null = null;
	let basis: WindowRead['basis'] = null;
	if (ens && ens.p10 !== null && ens.p90 !== null) {
		[lo, hi, basis] = [ens.p10, ens.p90, 'ensemble'];
	} else if (models.length >= 3) {
		[lo, hi, basis] = [models[0].cm, models[models.length - 1].cm, 'models'];
	}
	const snow = w?.snow_cm ?? null;
	return {
		key,
		label: WINDOW_LABEL[key],
		snow_cm: snow,
		lo,
		hi,
		basis,
		estimated: ens?.estimated ?? false,
		models,
		confidence: snow === null ? null : confidenceOf(snow, lo, hi)
	};
}

/** One sentence for a window's confidence. */
export function confidenceNote(r: WindowRead): string {
	if (r.confidence === null) return 'Not enough models reach this far to say.';
	const dry = (r.hi ?? 0) <= AGREE_CM && (r.snow_cm ?? 0) < STEADY_CM;
	if (dry) return 'Little or no snow, and the models agree on that.';
	if (r.confidence === 'high') return 'The models agree closely.';
	if (r.confidence === 'medium') return 'The models agree on the pattern, less on the amount.';
	return 'The models disagree: take the total as a rough guide.';
}

export interface DayRead {
	date: string;
	/** Each model's snow that day (cm); null where it has ended. */
	models: Record<string, number | null>;
	/** The models' median, while at least three cover the day. */
	median: number | null;
	/** The ensembles' 10–90% range and median for the day alone. */
	lo: number | null;
	hi: number | null;
	mid: number | null;
	confidence: Confidence | null;
}

const median = (vals: number[]): number => {
	const s = [...vals].sort((a, b) => a - b);
	const m = s.length >> 1;
	return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

/** Day by day at mid-mountain: each model, the models' median and the ensemble range. */
export function dayReads(daily: DailyRow[]): DayRead[] {
	return daily.map((d) => {
		const vals = Object.values(d.models).filter((v): v is number => v !== null && v !== undefined);
		const med = vals.length >= 3 ? median(vals) : null;
		const lo = d.ens_day?.p10 ?? null;
		const hi = d.ens_day?.p90 ?? null;
		const mid = d.ens_day?.p50 ?? null;
		return {
			date: d.date,
			models: d.models,
			median: med,
			lo,
			hi,
			mid,
			confidence: confidenceOf(med ?? mid, lo, hi)
		};
	});
}

export interface TrendRead {
	/** Change in the total over the days both runs cover (cm, + is more snow now). */
	change_cm: number;
	direction: 'up' | 'down' | 'steady';
	/** When the earlier run was issued. */
	since: string;
	/** How many runs back that is. */
	runs_back: number;
	/** How many days the two runs share. */
	days: number;
}

/**
 * How the consensus has moved: the newest run against the oldest of the last `count`,
 * over the same calendar days (up to five), so a storm sliding out of the window
 * doesn't read as the forecast changing.
 */
export function trendRead(runs: TrendRun[], count = 5): TrendRead | null {
	const recent = runs.slice(-count);
	if (recent.length < 2) return null;
	const latest = recent[recent.length - 1];
	const first = recent[0];
	const has = (r: TrendRun, d: string) => r.daily[d] !== null && r.daily[d] !== undefined;
	const dates = Object.keys(latest.daily)
		.sort()
		.filter((d) => has(latest, d) && has(first, d))
		.slice(0, 5);
	if (!dates.length) return null;
	const sum = (r: TrendRun) => dates.reduce((acc, d) => acc + (r.daily[d] ?? 0), 0);
	const change = sum(latest) - sum(first);
	return {
		change_cm: change,
		direction: Math.abs(change) < STEADY_CM ? 'steady' : change > 0 ? 'up' : 'down',
		since: first.issued_at,
		runs_back: recent.length - 1,
		days: dates.length
	};
}
