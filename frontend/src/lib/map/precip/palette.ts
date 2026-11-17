// The colours the precipitation is drawn in, as a lookup table for the shader: one row a
// type (snow, mix, rain), one column a rate code. The same colours the server paints its
// pictures with (backend/snowwatch/maps/palette.py, the "fine" palette): each ramp's stops
// from ../../radar.ts, running smoothly between them in log rate, mixed in OKLab.
import { RAMPS, type RampStep } from '../../radar';
import { codeRate, rateCode, RATE_CODES } from './codec';

/** Rows of the table, top to bottom. */
export const LUT_ROWS = ['snow', 'mix', 'rain'] as const;
export const LUT_WIDTH = RATE_CODES;

/** mm of water an hour: the lightest drawn, and where it reaches full strength
 *  (palette.py FINE_FROM, FINE_SOLID). */
export const DRAW_FROM = 0.1;
export const DRAW_SOLID = 0.25;
/** The same as codes, for the shader, and the strength at the lightest rate. */
export const CODE_FROM = rateCode(DRAW_FROM);
export const CODE_SOLID = rateCode(DRAW_SOLID);
export const ALPHA_FROM = 0.4;

type V3 = [number, number, number];

const hex = (h: string): V3 => [
	parseInt(h.slice(1, 3), 16),
	parseInt(h.slice(3, 5), 16),
	parseInt(h.slice(5, 7), 16)
];

function toOklab(c: V3): V3 {
	const lin = c.map((v) => (v > 10 ? ((v / 255 + 0.055) / 1.055) ** 2.4 : v / 255 / 12.92));
	const l = Math.cbrt(0.4122214708 * lin[0] + 0.5363325363 * lin[1] + 0.0514459929 * lin[2]);
	const m = Math.cbrt(0.2119034982 * lin[0] + 0.6806995451 * lin[1] + 0.1073969566 * lin[2]);
	const s = Math.cbrt(0.0883024619 * lin[0] + 0.2817188376 * lin[1] + 0.6299787005 * lin[2]);
	return [
		0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
		1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
		0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
	];
}

function fromOklab(lab: V3): V3 {
	const l = (lab[0] + 0.3963377774 * lab[1] + 0.2158037573 * lab[2]) ** 3;
	const m = (lab[0] - 0.1055613458 * lab[1] - 0.0638541728 * lab[2]) ** 3;
	const s = (lab[0] - 0.0894841775 * lab[1] - 1.291485548 * lab[2]) ** 3;
	const lin = [
		4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
		-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
		-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s
	];
	return lin.map((v) => {
		const x = Math.min(1, Math.max(0, v));
		return Math.round(255 * (x > 0.0031308 ? 1.055 * x ** (1 / 2.4) - 0.055 : 12.92 * x));
	}) as V3;
}

/** A ramp's colour at a rate: the first stop's below it, the last's above it. */
export function rampColor(steps: RampStep[], mm: number): V3 {
	const cols = steps.map((s) => hex(s.color));
	if (mm <= steps[0].from) return cols[0];
	const last = steps.length - 1;
	if (mm >= steps[last].from) return cols[last];
	for (let i = 0; i < last; i++) {
		if (mm < steps[i + 1].from) {
			const f =
				(Math.log(mm) - Math.log(steps[i].from)) /
				(Math.log(steps[i + 1].from) - Math.log(steps[i].from));
			const a = toOklab(cols[i]);
			const b = toOklab(cols[i + 1]);
			return fromOklab([
				a[0] + (b[0] - a[0]) * f,
				a[1] + (b[1] - a[1]) * f,
				a[2] + (b[2] - a[2]) * f
			]);
		}
	}
	return cols[last];
}

/** The table as RGBA bytes, LUT_WIDTH × 3 (alpha 255: the shader sets the strength). */
export function buildLut(): Uint8Array {
	const out = new Uint8Array(LUT_WIDTH * LUT_ROWS.length * 4);
	LUT_ROWS.forEach((kind, row) => {
		for (let code = 0; code < LUT_WIDTH; code++) {
			const [r, g, b] = rampColor(RAMPS[kind].steps, codeRate(Math.max(1, code)));
			out.set([r, g, b, 255], (row * LUT_WIDTH + code) * 4);
		}
	});
	return out;
}
