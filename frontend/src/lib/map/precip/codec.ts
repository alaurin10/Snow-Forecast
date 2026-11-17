// Precipitation frames as numbers (backend/snowwatch/maps/dataframe.py; keep in step).
//
// A frame is a rate plane (one byte a pixel: 0 dry, 1..127 log-spaced from RATE_MIN to
// RATE_MAX mm of water an hour) and two type planes at a quarter of the region's
// resolution: the share of the precipitation that is snow, and the share that is mixed or
// freezing (rain is the rest). The type planes are filled across dry ground, so
// interpolating at an echo's edge never mixes in "no type".
//
// The file is a gzip stream of a 16-byte header and the planes, each row stored as
// differences from the row above. Nothing here touches an image decoder: the bytes that
// come out are the bytes the server put in.

/** mm of water an hour at code 1 and at the top code. */
export const RATE_MIN = 0.05;
export const RATE_MAX = 100;
export const RATE_STEPS = 126;
/** Codes in use: 0 (dry) to 127. */
export const RATE_CODES = RATE_STEPS + 2;
/** Region pixels per type pixel. */
export const TYPE_DS = 4;
export const HEADER_BYTES = 16;

const SPAN = Math.log(RATE_MAX / RATE_MIN);

/** mm of water an hour for a code (fractional codes too); 0 below code 1. */
export function codeRate(code: number): number {
	return code >= 1 ? RATE_MIN * Math.exp(((code - 1) / RATE_STEPS) * SPAN) : 0;
}

/** The (fractional) code for a rate; 0 below RATE_MIN. */
export function rateCode(mm: number): number {
	if (!(mm >= RATE_MIN)) return 0;
	return Math.min(1 + RATE_STEPS, 1 + (RATE_STEPS * Math.log(mm / RATE_MIN)) / SPAN);
}

/** A decoded frame, ready to upload as textures. */
export interface Planes {
	/** Rate codes, `width` × `height`, row 0 the north. */
	rate: Uint8Array;
	width: number;
	height: number;
	/** Snow and mix shares interleaved (two bytes a pixel), `typeWidth` × `typeHeight`. */
	type: Uint8Array;
	typeWidth: number;
	typeHeight: number;
	/** Region pixels per rate pixel. */
	ds: number;
}

/** Undo "each row as the difference from the row above", in place. */
function unfilter(plane: Uint8Array, width: number, height: number): void {
	for (let i = width, n = width * height; i < n; i++)
		plane[i] = (plane[i] + plane[i - width]) & 255;
}

/** A frame's planes from its inflated bytes; null if it isn't one. */
export function parse(raw: Uint8Array): Planes | null {
	if (raw.length < HEADER_BYTES) return null;
	if (raw[0] !== 0x53 || raw[1] !== 0x57 || raw[2] !== 0x46 || raw[3] !== 0x31) return null; // "SWF1"
	const v = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
	const width = v.getUint16(4, true);
	const height = v.getUint16(6, true);
	const typeWidth = v.getUint16(8, true);
	const typeHeight = v.getUint16(10, true);
	const ds = raw[12];
	const planes = raw[13];
	const n = width * height;
	const tn = typeWidth * typeHeight;
	if (!ds || planes !== 2 || !n || !tn || raw.length !== HEADER_BYTES + n + 2 * tn) return null;
	// Copies: the planes outlive `raw`, and are handed to another thread.
	const rate = raw.slice(HEADER_BYTES, HEADER_BYTES + n);
	unfilter(rate, width, height);
	const snow = raw.slice(HEADER_BYTES + n, HEADER_BYTES + n + tn);
	const mix = raw.slice(HEADER_BYTES + n + tn);
	unfilter(snow, typeWidth, typeHeight);
	unfilter(mix, typeWidth, typeHeight);
	const type = new Uint8Array(2 * tn);
	for (let i = 0; i < tn; i++) {
		type[2 * i] = snow[i];
		type[2 * i + 1] = mix[i];
	}
	return { rate, width, height, type, typeWidth, typeHeight, ds };
}

/**
 * The rate plane at half the size each way (a phone keeps the radar loop this way and the
 * frame at rest in full). Each output pixel is the mean of its 2×2 codes, which is the
 * value bilinear filtering would give at their middle.
 */
export function halve(p: Planes): Planes {
	const w = Math.ceil(p.width / 2);
	const h = Math.ceil(p.height / 2);
	const out = new Uint8Array(w * h);
	const src = p.rate;
	for (let r = 0; r < h; r++) {
		const r0 = 2 * r * p.width;
		const r1 = Math.min(2 * r + 1, p.height - 1) * p.width;
		for (let c = 0; c < w; c++) {
			const c0 = 2 * c;
			const c1 = Math.min(c0 + 1, p.width - 1);
			out[r * w + c] = (src[r0 + c0] + src[r0 + c1] + src[r1 + c0] + src[r1 + c1] + 2) >> 2;
		}
	}
	return { ...p, rate: out, width: w, height: h, ds: p.ds * 2 };
}

/** Bytes a frame's planes take as textures. */
export const planeBytes = (p: Planes) => p.rate.length + p.type.length;
