// The API is metric only; the browser converts for display.

export type UnitSystem = 'imperial' | 'metric';

export const cmToIn = (cm: number): number => cm / 2.54;
export const mmToIn = (mm: number): number => mm / 25.4;
export const cToF = (c: number): number => (c * 9) / 5 + 32;
export const mToFt = (m: number): number => m * 3.28084;
export const kmhToMph = (kmh: number): number => kmh * 0.621371;

/** Round to a step, e.g. elevations to the nearest 50 ft. */
export const roundTo = (value: number, step: number): number => Math.round(value / step) * step;

export function snow(cm: number | null, units: UnitSystem): string {
	if (cm === null) return '–';
	return units === 'imperial' ? `${cmToIn(cm).toFixed(1)} in` : `${cm.toFixed(0)} cm`;
}

export function temperature(c: number | null, units: UnitSystem): string {
	if (c === null) return '–';
	return units === 'imperial' ? `${Math.round(cToF(c))}°F` : `${Math.round(c)}°C`;
}

export function elevation(m: number | null, units: UnitSystem): string {
	if (m === null) return '–';
	return units === 'imperial'
		? `${roundTo(mToFt(m), 50).toLocaleString('en-US')} ft`
		: `${roundTo(m, 10).toLocaleString('en-US')} m`;
}

export function speed(kmh: number | null, units: UnitSystem): string {
	if (kmh === null) return '–';
	return units === 'imperial' ? `${Math.round(kmhToMph(kmh))} mph` : `${Math.round(kmh)} km/h`;
}
