// The API is metric only; the browser converts for display.

export type UnitSystem = 'imperial' | 'metric';

export const cmToIn = (cm: number): number => cm / 2.54;
export const mmToIn = (mm: number): number => mm / 25.4;
export const cToF = (c: number): number => (c * 9) / 5 + 32;
export const mToFt = (m: number): number => m * 3.28084;
export const kmhToMph = (kmh: number): number => kmh * 0.621371;

/** Round to a step, e.g. elevations to the nearest 50 ft. */
export const roundTo = (value: number, step: number): number => Math.round(value / step) * step;

// Numeric converters for chart scales (null stays null).
type Conv = (v: number | null | undefined) => number | null;
const conv =
	(f: (v: number) => number): Conv =>
	(v) =>
		v === null || v === undefined ? null : f(v);

export function converters(units: UnitSystem) {
	const imp = units === 'imperial';
	return {
		snow: conv((cm) => (imp ? cmToIn(cm) : cm)),
		water: conv((mm) => (imp ? mmToIn(mm) : mm)),
		temp: conv((c) => (imp ? cToF(c) : c)),
		height: conv((m) => (imp ? mToFt(m) : m)),
		speed: conv((kmh) => (imp ? kmhToMph(kmh) : kmh)),
		snowUnit: imp ? 'in' : 'cm',
		waterUnit: imp ? 'in' : 'mm',
		tempUnit: imp ? '°F' : '°C',
		heightUnit: imp ? 'ft' : 'm',
		speedUnit: imp ? 'mph' : 'km/h',
		freezing: imp ? 32 : 0,
		snowDigits: imp ? 1 : 0,
		waterDigits: imp ? 2 : 1
	};
}

export function snow(cm: number | null | undefined, units: UnitSystem): string {
	if (cm === null || cm === undefined) return '–';
	return units === 'imperial' ? `${cmToIn(cm).toFixed(1)} in` : `${cm.toFixed(0)} cm`;
}

export function temperature(c: number | null | undefined, units: UnitSystem): string {
	if (c === null || c === undefined) return '–';
	return units === 'imperial' ? `${Math.round(cToF(c))}°F` : `${Math.round(c)}°C`;
}

export function elevation(m: number | null | undefined, units: UnitSystem): string {
	if (m === null || m === undefined) return '–';
	return units === 'imperial'
		? `${roundTo(mToFt(m), 50).toLocaleString('en-US')} ft`
		: `${roundTo(m, 10).toLocaleString('en-US')} m`;
}

/** A short distance on the ground: "600 m", "1.2 km", or "0.4 mi", "2.5 mi". */
export function distance(km: number | null | undefined, units: UnitSystem): string {
	if (km === null || km === undefined) return '–';
	if (units === 'imperial') {
		const mi = km * 0.621371;
		return mi < 10 ? `${Math.max(0.1, roundTo(mi, 0.1)).toFixed(1)} mi` : `${Math.round(mi)} mi`;
	}
	if (km < 1) return `${Math.max(100, roundTo(km * 1000, 100))} m`;
	return km < 10 ? `${roundTo(km, 0.1).toFixed(1)} km` : `${Math.round(km)} km`;
}

export function speed(kmh: number | null | undefined, units: UnitSystem): string {
	if (kmh === null || kmh === undefined) return '–';
	return units === 'imperial' ? `${Math.round(kmhToMph(kmh))} mph` : `${Math.round(kmh)} km/h`;
}

export function water(mm: number | null | undefined, units: UnitSystem): string {
	if (mm === null || mm === undefined) return '–';
	return units === 'imperial' ? `${mmToIn(mm).toFixed(2)} in` : `${mm.toFixed(1)} mm`;
}

/** A snow amount without its unit, at display precision. */
export function snowNum(cm: number | null | undefined, units: UnitSystem): string {
	if (cm === null || cm === undefined) return '–';
	return units === 'imperial' ? cmToIn(cm).toFixed(1) : cm.toFixed(0);
}
