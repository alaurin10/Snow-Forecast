// The Observed tab in plain words: what the station's numbers add up to (how much snow
// fell, how deep it is, whether it thawed) and whether the forecast got it right. Pure
// functions, so the sentences are tested apart from the cards that show them.
import type { Snotel, SnotelDay, VerificationOut, VerificationPair } from '../types.gen';
import { depthRow, waterRow } from '../scores';
import { snow, water, type UnitSystem } from '../units';
import { weekday } from '../time';

/** Less new snow than this (cm) isn't worth a headline. */
export const NOTABLE_CM = 2;

/** One day at the station: the snow that fell during it and its low and high. */
export interface ObsDay {
	date: string;
	/** Depth gain during the day (never negative); from snow water where there's no depth. */
	new_cm: number | null;
	depth_cm: number | null;
	swe_mm: number | null;
	tmin_c: number | null;
	tmax_c: number | null;
}

/**
 * Each day's new snow: how much deeper the snow was the next morning (as the forecast
 * scorecard counts it), or the snow-water gain × 10 where the station has no depth
 * sensor. The last day runs to the station's latest reading (`now`), so today counts.
 */
export function obsDays(
	days: SnotelDay[],
	now: { depth_cm: number | null; swe_mm: number | null } = { depth_cm: null, swe_mm: null }
): ObsDay[] {
	const gain = (a: number | null, b: number | null) =>
		a === null || b === null ? null : Math.max(0, b - a);
	return days.map((d, i) => {
		const next = days[i + 1];
		const depthNext = next ? next.depth_cm : now.depth_cm;
		const sweNext = next ? next.swe_mm : now.swe_mm;
		const byDepth = gain(d.depth_cm, depthNext);
		return {
			date: d.date,
			new_cm: byDepth ?? gain(d.swe_mm, sweNext),
			depth_cm: d.depth_cm,
			swe_mm: d.swe_mm,
			tmin_c: d.tmin_c ?? null,
			tmax_c: d.tmax_c ?? null
		};
	});
}

const sum = (vals: (number | null)[]) => vals.reduce<number>((a, v) => a + (v ?? 0), 0);

export interface StationRead {
	/** The last 30 days, oldest first. */
	days: ObsDay[];
	hasDepth: boolean;
	/** Snow on the ground now (the latest hourly reading). */
	depth_cm: number | null;
	/** New snow (depth gain, never negative) over the last 24 h, 72 h and 7 days. */
	new24: number | null;
	new72: number | null;
	new7: number | null;
	/** Depth now against a week ago (negative: settled or melted). */
	weekChange: number | null;
	/** Days in the last 7 whose high went above freezing (null: no highs reported). */
	thawDays: number | null;
	headline: string;
	/** Short facts under the headline. */
	notes: string[];
}

/** What the station's last month adds up to, in words. */
export function stationRead(station: Snotel, units: UnitSystem): StationRead {
	const all = obsDays(station.daily ?? [], {
		depth_cm: station.depth_cm,
		swe_mm: station.swe_mm
	});
	const days = all.slice(-30);
	const hasDepth = days.some((d) => d.depth_cm !== null);
	const any = days.some((d) => d.new_cm !== null);
	const last = (n: number) => days.slice(-n).map((d) => d.new_cm);
	// The hourly changes are the freshest for a day or three; settling can make them
	// negative, which isn't new snow. Each total is at least the shorter one inside it.
	const clamp = (v: number | null | undefined) =>
		v === null || v === undefined ? null : Math.max(0, v);
	const new24 = hasDepth ? (clamp(station.change24_cm) ?? (any ? sum(last(1)) : null)) : null;
	const new72raw = hasDepth ? (clamp(station.change72_cm) ?? (any ? sum(last(3)) : null)) : null;
	const new72 = new72raw === null ? null : Math.max(new72raw, new24 ?? 0);
	const new7raw = any ? sum(last(7)) : null;
	const new7 = new7raw === null ? null : Math.max(new7raw, new72 ?? 0);

	const depthNow =
		station.depth_cm ?? [...days].reverse().find((d) => d.depth_cm !== null)?.depth_cm ?? null;
	const weekAgo = days.length >= 7 ? days[days.length - 7].depth_cm : null;
	const weekChange = depthNow === null || weekAgo === null ? null : depthNow - weekAgo;

	const highs = days.slice(-7).filter((d) => d.tmax_c !== null);
	const thawDays = highs.length ? highs.filter((d) => (d.tmax_c as number) > 0).length : null;

	// Days since the last notable snowfall, counting back from today.
	const sinceSnow = (() => {
		for (let i = days.length - 1; i >= 0; i--)
			if ((days[i].new_cm ?? 0) >= NOTABLE_CM) return days.length - 1 - i;
		return null;
	})();
	const lastSnowDay = sinceSnow === null ? null : days[days.length - 1 - sinceSnow];

	let headline: string;
	if ((new72 ?? 0) >= NOTABLE_CM) headline = `${snow(new72, units)} of new snow in the last 3 days`;
	else if ((new7 ?? 0) >= NOTABLE_CM)
		headline = `${snow(new7, units)} of new snow this week${lastSnowDay ? `, most recently on ${weekday(lastSnowDay.date)}` : ''}`;
	else if (hasDepth && (depthNow === null || depthNow < 1))
		headline = 'No snow on the ground at the station';
	else if (!any) headline = 'No recent readings from the station';
	else if (sinceSnow === null)
		headline =
			days.length >= 28 ? 'No new snow in over a month' : `No new snow in ${days.length} days`;
	else headline = `No new snow in ${sinceSnow} days`;

	const notes: string[] = [];
	if (weekChange !== null && depthNow !== null && depthNow >= 1) {
		const d = Math.abs(weekChange);
		notes.push(
			d < 1
				? 'About as deep as a week ago'
				: `${snow(d, units)} ${weekChange > 0 ? 'deeper' : 'shallower'} than a week ago`
		);
	}
	if (thawDays !== null)
		notes.push(
			thawDays === 0
				? `Below freezing all ${highs.length === 7 ? 'week' : `${highs.length} days`}`
				: `Above freezing on ${thawDays} of the last ${highs.length} days`
		);

	return {
		days,
		hasDepth,
		depth_cm: hasDepth ? depthNow : null,
		new24,
		new72,
		new7,
		weekChange,
		thawDays,
		headline,
		notes
	};
}

/** Whether the depth chart scores the forecast for the station's own spot. */
export const snowAtStation = (data: VerificationOut): boolean =>
	depthRow(data)?.source === 'stn_settled';

/** Whether the precipitation chart scores the forecast for the station's own spot. */
export const waterAtStation = (data: VerificationOut): boolean =>
	waterRow(data)?.source === 'stn_cons';

/** The forecast new snow a day is scored against (cm). */
export function forecastSnow(data: VerificationOut, p: VerificationPair): number | null {
	if (snowAtStation(data)) return p.stn_settled_cm ?? null;
	const headline =
		data.headline === 'cons_slr'
			? p.cons_slr_cm
			: data.headline === 'cons_col'
				? (p.cons_col_cm ?? p.cons_slr_cm)
				: p.cons_cm;
	return p.cons_settled_cm ?? headline;
}

/** The forecast precipitation a day is scored against (mm). */
export const forecastWater = (data: VerificationOut, p: VerificationPair): number | null =>
	(waterAtStation(data) ? p.stn_water_mm : p.cons_water_mm) ?? null;

export interface Verdict {
	kind: 'snow' | 'water';
	/** Days both sides have a number for. */
	days: number;
	forecast: number;
	observed: number;
	lean: 'close' | 'high' | 'low';
	/** The average miss and lean per day (cm for snow, mm for water). */
	miss: number | null;
	bias: number | null;
	sentence: string;
}

/** Did the forecast get it right? New snow where the depth can say, else the gauge. */
export function forecastVerdict(data: VerificationOut, units: UnitSystem): Verdict | null {
	if (!data.ready) return null;
	const kind: 'snow' | 'water' = data.n_days > 0 ? 'snow' : 'water';
	let fcTotal = 0;
	let obsTotal = 0;
	let n = 0;
	for (const p of data.pairs) {
		const fc = kind === 'snow' ? forecastSnow(data, p) : forecastWater(data, p);
		const ob = kind === 'snow' ? (p.skip ? null : p.observed_cm) : (p.observed_water_mm ?? null);
		if (fc === null || fc === undefined || ob === null || ob === undefined) continue;
		fcTotal += fc;
		obsTotal += ob;
		n++;
	}
	if (!n) return null;
	const row = kind === 'snow' ? depthRow(data) : waterRow(data);
	const bias = row ? ('bias_cm' in row ? row.bias_cm : row.bias_mm) : null;
	const miss = row ? ('mae_cm' in row ? row.mae_cm : row.mae_mm) : null;
	const fmt = (v: number) => (kind === 'snow' ? snow(v, units) : water(v, units));
	const near = kind === 'snow' ? 0.5 : 1;
	const lean: Verdict['lean'] =
		bias === null || Math.abs(bias) < near ? 'close' : bias > 0 ? 'high' : 'low';
	const what = kind === 'snow' ? 'snow' : 'precipitation';
	const typical = miss === null ? '' : `; a typical day was off by ${fmt(miss)}`;
	const sentence =
		lean === 'close'
			? `About right on balance${typical}.`
			: `Forecast ${lean === 'high' ? 'more' : 'less'} ${what} than ${kind === 'snow' ? 'fell' : 'the gauge caught'}, by about ${fmt(Math.abs(bias!))} a day${typical}.`;
	return { kind, days: n, forecast: fcTotal, observed: obsTotal, lean, miss, bias, sentence };
}
