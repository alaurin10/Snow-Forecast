// Flags: short "worth a look" notes, worded in the viewer's units.
import type { Flag } from './types.gen';
import { DANGER_WORDS } from './conditions';
import { MODEL_NAMES } from './models';
import { weekday } from './time';
import { elevation, snow, speed, temperature, water, type UnitSystem } from './units';

const day = (d: string | null | undefined) => (d ? weekday(d) : '');

/** A flag's short title for a badge, e.g. "Powder Sat". */
export function flagTitle(f: Flag): string {
	switch (f.type) {
		case 'powder_day':
			return `Powder ${day(f.date)}`;
		case 'storm_incoming':
			return `Storm ${day(f.date)}`;
		case 'model_outlier':
			return 'Model outlier';
		case 'low_confidence':
			return 'Low confidence';
		case 'rain_on_snow':
			return `Rain on snow ${day(f.date)}`;
		case 'snow_level_crossing':
			return f.detail === 'below_base' ? 'Snow to the base' : 'Snow level rising';
		case 'wind_hold':
			return `Wind holds ${day(f.date)}`;
		case 'best_day':
			return `Best day ${day(f.date)}`;
		case 'wind_loading':
			return `Wind loading ${day(f.date)}`;
		case 'rapid_warming':
			return `Rapid warming ${day(f.date)}`;
		case 'refreeze':
			return `Refreeze ${day(f.date)}`;
		case 'nws_alert':
			return f.detail ?? 'NWS alert';
		case 'avalanche_danger':
			return `Avalanche ${f.value ?? ''} · ${DANGER_WORDS[f.value ?? 0] ?? ''}`;
		default:
			return f.type.replace(/_/g, ' ');
	}
}

/** One sentence explaining the flag. */
export function flagText(f: Flag, units: UnitSystem): string {
	const v = f.value ?? null;
	const v2 = f.value2 ?? null;
	switch (f.type) {
		case 'powder_day':
			return `${snow(v, units)} of new snow by ${day(f.date)} (the night before plus the day).`;
		case 'storm_incoming':
			return (
				`${snow(v, units)} in 48 h from ${day(f.date)}` +
				(v2 !== null ? `; ${v2}% of ensemble members agree on a storm.` : '.')
			);
		case 'model_outlier':
			return `${MODEL_NAMES[f.model ?? ''] ?? f.model} has ${snow(v, units)} over 10 days, far above the ensemble's high end (${snow(v2, units)}).`;
		case 'low_confidence':
			return `The models disagree: the next 5 days could bring anywhere from ${snow(v, units)} to ${snow(v2, units)}.`;
		case 'rain_on_snow':
			return `${water(v, units)} of rain at mid-mountain ${day(f.date)}, onto snow.`;
		case 'snow_level_crossing':
			return f.detail === 'below_base'
				? `The snow level drops to ${elevation(v, units)}, below the base (${elevation(v2, units)}), by ${day(f.date)}.`
				: `The snow level rises to ${elevation(v, units)}, above mid-mountain (${elevation(v2, units)}), by ${day(f.date)}.`;
		case 'wind_hold':
			return `Summit gusts to ${speed(v, units)} during lift hours ${day(f.date)}: lift holds likely.`;
		case 'best_day':
			return `${day(f.date)} rates ${f.detail ?? 'best'} for skiing this week.`;
		case 'wind_loading':
			return `${snow(v, units)} of snow in 24 h with ridge wind to ${speed(v2, units)} ${day(f.date)}: fresh drifts on lee slopes.`;
		case 'rapid_warming': {
			const parts = [];
			if (v !== null && v > 0) parts.push(`the freezing level up ${elevation(v, units)}`);
			if (v2 !== null && v2 > 0)
				parts.push(`${units === 'imperial' ? Math.round((v2 * 9) / 5) : Math.round(v2)}° warmer`);
			return `Within 24 h by ${day(f.date)}: ${parts.join(' and ') || 'a sharp warm-up'}.`;
		}
		case 'refreeze':
			return `A good overnight refreeze ${day(f.date)} (low ${temperature(v, units)}) after a high of ${temperature(v2, units)}.`;
		case 'nws_alert':
			return `National Weather Service: ${f.detail ?? 'alert'}.`;
		case 'avalanche_danger':
			return `The avalanche center rates danger ${f.value} (${DANGER_WORDS[f.value ?? 0] ?? ''}) today. Read the forecast.`;
		default:
			return '';
	}
}

/** Was this flag first raised in the run that produced the data? */
export const isNew = (f: Flag, runId: number | null | undefined) =>
	runId !== null && runId !== undefined && f.first_run === runId;
