// Words for avalanche danger, ski-day ratings and their reasons.
import type { Reason } from './types.gen';
import { snow, speed, temperature, water, type UnitSystem } from './units';

/** The North American avalanche danger scale. Always shown with the number. */
export const DANGER_WORDS: Record<number, string> = {
	1: 'Low',
	2: 'Moderate',
	3: 'Considerable',
	4: 'High',
	5: 'Extreme'
};

export const dangerWord = (level: number | null | undefined): string =>
	level ? (DANGER_WORDS[level] ?? '–') : 'No rating';

/** One reason for a ski-day rating, in the viewer's units. */
export function reasonText(r: Reason, units: UnitSystem): string {
	const v = r.value ?? null;
	switch (r.code) {
		case 'new_snow':
			return `${snow(v, units)} new`;
		case 'heavy_wet':
			return 'heavy, wet snow';
		case 'clear':
			return 'dry with little low cloud';
		case 'grey':
			return 'no new snow, grey or showery';
		case 'rain':
			return `${water(v, units)} rain at mid`;
		case 'gusts':
			return `gusts ${speed(v, units)} at the summit: lift holds likely`;
		case 'flat_light':
			return 'flat light (low cloud or fog)';
		case 'very_cold':
			return `very cold (high ${temperature(v, units)})`;
		default:
			return r.code;
	}
}

const POINTS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

/** Compass point for a direction in degrees (where the wind comes from). */
export const compass = (deg: number | null | undefined): string =>
	deg === null || deg === undefined
		? '–'
		: POINTS[Math.round((((deg % 360) + 360) % 360) / 45) % 8];

/** A WMO weather code as a short phrase (Open-Meteo's codes). */
export function skyWord(code: number | null | undefined): string {
	if (code === null || code === undefined) return '–';
	if (code === 0) return 'Clear';
	if (code <= 2) return 'Partly cloudy';
	if (code === 3) return 'Cloudy';
	if (code <= 48) return 'Fog';
	if (code <= 57) return 'Drizzle';
	if (code <= 67) return 'Rain';
	if (code <= 77) return 'Snow';
	if (code <= 82) return 'Rain showers';
	if (code <= 86) return 'Snow showers';
	return 'Thunderstorms';
}
