// Words for the Backcountry tab's day-by-day outlook. The server grades each day's
// weather (config `backcountry:`); this turns the grades and facts into text in the
// viewer's units. Nothing here is a danger rating, and none of it uses the danger
// scale's words or colours.
import type { AvalancheView, OutlookDay, OutlookSteps } from '../types.gen';
import { weekday } from '../time';
import { cmToIn, elevation, kmhToMph, mmToIn, snow, speed, water, type UnitSystem } from '../units';

export type Factor = 'snow' | 'wind' | 'rain' | 'warm';
export const FACTORS: readonly Factor[] = ['snow', 'wind', 'rain', 'warm'] as const;
export const FACTOR_NAMES: Record<Factor, string> = {
	snow: 'Snow',
	wind: 'Wind',
	rain: 'Rain',
	warm: 'Warming'
};

/** Weather loading, 0–3. Deliberately not the danger scale's words. */
export const STRESS_WORDS = ['Little', 'Some', 'Strong', 'Very strong'] as const;
/** What each level means, for the key under the days. */
export const STRESS_MEANINGS = [
	'Not much stressing the snowpack',
	'Small fresh drifts or a little wet snow',
	'Enough to build fresh slabs or soak the surface',
	'A big loading day, or two Strong factors at once'
] as const;
export const stressWord = (n: number): string =>
	STRESS_WORDS[Math.max(0, Math.min(3, Math.round(n)))];

const degrees = (c: number, units: UnitSystem) =>
	`${Math.round(units === 'imperial' ? (c * 9) / 5 : c)}°${units === 'imperial' ? 'F' : 'C'}`;

export interface Cell {
	/** The fact, e.g. "11.8 in" or "S 34 mph". */
	value: string;
	/** A few words that go with it, e.g. "16.7 in / 3 days" or "loads N". */
	detail: string;
	level: number;
}

/** One factor of one day, worded. */
export function cell(d: OutlookDay, f: Factor, units: UnitSystem): Cell {
	const level = d.levels[f];
	if (f === 'snow') {
		const more = (d.storm_cm ?? 0) > (d.new_cm ?? 0) + 0.5;
		return {
			value: snow(d.new_cm, units),
			detail: more ? `${snow(d.storm_cm, units)} / 3 days` : '',
			level
		};
	}
	if (f === 'wind') {
		const from = d.wind_from ? `${d.wind_from} ` : '';
		const detail = d.loading?.length
			? `loads ${d.loading.join('–')}`
			: d.wind_from
				? 'little to drift'
				: 'light';
		return { value: `${from}${speed(d.wind_kmh, units)}`, detail, level };
	}
	if (f === 'rain') {
		if (d.rain_mm === null) return { value: '–', detail: 'no snow cover', level };
		const wet = d.rain_mm >= 0.1;
		return {
			value: wet ? water(d.rain_mm, units) : 'None',
			detail: wet && d.rain_to_m !== null ? `to ${elevation(d.rain_to_m, units)}` : '',
			level
		};
	}
	// The warmth itself when there is some, else the freezing level. Kept short: each
	// factor is one line on a phone.
	const rise = d.temp_rise_c ?? 0;
	if (d.thaw_h > 0) return { value: `${d.thaw_h} h thaw`, detail: 'at the summit', level };
	if (rise >= 5) return { value: `${degrees(rise, units)} warmer`, detail: 'in 24 h', level };
	return {
		value: d.fl_max_m === null ? '–' : elevation(d.fl_max_m, units),
		detail: 'freezing level',
		level
	};
}

/** The factors pushing on the snowpack that day, in their usual order. */
export const activeFactors = (d: OutlookDay): Factor[] => FACTORS.filter((f) => d.levels[f] > 0);

/**
 * What each level takes, per factor, in the viewer's units: the key's table. Rounded
 * to what a reader would say ("4 in", "16 mph"); the server grades on the exact values.
 */
export function thresholds(
	st: OutlookSteps,
	units: UnitSystem
): { factor: Factor; steps: string[] }[] {
	const imp = units === 'imperial';
	const depth = (cm: number) => (imp ? `${Math.round(cmToIn(cm))} in` : `${Math.round(cm)} cm`);
	const wind = (kmh: number) =>
		imp ? `${Math.round(kmhToMph(kmh))} mph` : `${Math.round(kmh)} km/h`;
	const rain = (mm: number) => (imp ? `${mmToIn(mm).toFixed(2)} in` : `${mm} mm`);
	const rise = (c: number) => `${degrees(c, units)} rise`;
	return [
		{
			factor: 'snow',
			steps: st.snow_cm.map((v, i) =>
				i === 0
					? `${depth(v)} in a day, or ${depth(st.storm_cm[i])} over 3 days`
					: `${depth(v)}, or ${depth(st.storm_cm[i])}`
			)
		},
		{ factor: 'wind', steps: st.wind_kmh.map(wind) },
		{ factor: 'rain', steps: st.rain_mm.map(rain) },
		{
			factor: 'warm',
			steps: st.rise_c.map((v, i) =>
				i < st.thaw_h.length ? `${rise(v)}, or ${st.thaw_h[i]} h thaw` : rise(v)
			)
		}
	];
}

/** What is pushing on the snowpack that day, strongest first, as short phrases. */
export function drivers(d: OutlookDay, units: UnitSystem): string[] {
	const out: [number, string][] = [];
	const lv = d.levels;
	if (lv.snow)
		out.push([
			lv.snow,
			(d.new_cm ?? 0) >= 2.5
				? `${snow(d.new_cm, units)} of new snow`
				: `${snow(d.storm_cm, units)} in 72 h`
		]);
	if (lv.wind)
		out.push([
			lv.wind,
			`${d.wind_from ?? ''} wind to ${speed(d.wind_kmh, units)}`.trim() +
				(d.loading?.length ? ` loading ${d.loading.join('–')} slopes` : '')
		]);
	if (lv.rain)
		out.push([
			lv.rain,
			`${water(d.rain_mm, units)} of rain` +
				(d.rain_to_m !== null ? ` up to ${elevation(d.rain_to_m, units)}` : '')
		]);
	if (lv.warm) {
		const night = (d.refreeze ?? []).find((n) => n.band === 'summit')?.status;
		out.push([
			lv.warm,
			d.thaw_h > 0
				? `${d.thaw_h} h above freezing at the summit${night === 'None' ? ' after no refreeze' : ''}`
				: `${degrees(d.temp_rise_c ?? 0, units)} of warming in 24 h`
		]);
	}
	return out.sort((a, b) => b[0] - a[0]).map(([, text]) => text);
}

const dayName = (date: string, today: string) => (date === today ? 'today' : weekday(date));
const list = (parts: string[]) =>
	parts.length <= 2
		? parts.join(' and ')
		: `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** One or two sentences on the days ahead: when the weather pushes hardest, and with what. */
export function outlookSummary(days: OutlookDay[], today: string, units: UnitSystem): string {
	if (!days.length) return '';
	const peak = Math.max(...days.map((d) => d.stress));
	const name = (d: OutlookDay) => dayName(d.date, today);
	if (peak === 0)
		return `Quiet weather for the snowpack through ${name(days[days.length - 1])}: no real new snow, drifting, rain or warming.`;
	// The days at the peak, with runs of days joined ("Fri to Sun and Tue").
	const spans: string[] = [];
	let lastTop = 0;
	for (let i = 0; i < days.length; i++) {
		if (days[i].stress !== peak) continue;
		let j = i;
		while (j + 1 < days.length && days[j + 1].stress === peak) j++;
		spans.push(j === i ? name(days[i]) : `${name(days[i])} to ${name(days[j])}`);
		lastTop = j;
		i = j;
	}
	const first = days.find((d) => d.stress === peak)!;
	const why = list(drivers(first, units).slice(0, 2));
	const several = days.filter((d) => d.stress === peak).length > 1;
	let out = `${stressWord(peak)} weather loading ${list(spans)}`;
	if (why) out += several ? `. ${capital(name(first))} brings ${why}` : `: ${why}`;
	out += '.';
	const after = days.slice(lastTop + 1).find((d) => d.stress <= 1);
	if (after && peak >= 2) out += ` Easing by ${name(after)}.`;
	return out;
}

/** The highest published rating for a date, while the bulletin is current and covers it. */
export function publishedDanger(avy: AvalancheView | null, date: string): number | null {
	if (avy?.status !== 'current' || !avy.doc) return null;
	const day = (avy.doc.days ?? []).find((d) => d.date === date);
	if (!day) return null;
	const levels = [day.alpine, day.treeline, day.below].filter(
		(v): v is number => v !== null && v !== undefined
	);
	return levels.length ? Math.max(...levels) : null;
}
