// The snow total as numbers (backend/snowwatch/maps/totaldata.py; keep in step).
//
// A step is the snow from the totals' start to one moment: an area plane (the plain
// total, cm, at half the region's resolution) and the snow at each elevation from 0 m
// every `bandM` metres (a plane per band, about 6 km a cell), so the map can give each
// pixel the snow at its own elevation. Each byte is a code: 0 none, 1..255 log-spaced
// from CM_MIN to CM_MAX cm.
//
// The file is a gzip stream of a 16-byte header ("SWT1", area width and height, band
// width and height, band count, band step / 50 m) and the planes, each row stored as the
// difference from the row above.

export const CM_MIN = 0.2;
export const CM_MAX = 1000;
export const CM_CODES = 254;
const SPAN = Math.log(CM_MAX / CM_MIN);
const HEADER_BYTES = 16;

/** cm for a code (fractional codes too); 0 below code 1. */
export function codeCm(code: number): number {
	return code >= 1 ? CM_MIN * Math.exp(((code - 1) / CM_CODES) * SPAN) : 0;
}

/** The (fractional) code for a depth in cm; 0 below CM_MIN. */
export function cmCode(cm: number): number {
	if (!(cm >= CM_MIN)) return 0;
	return Math.min(1 + CM_CODES, 1 + (CM_CODES * Math.log(Math.min(cm, CM_MAX) / CM_MIN)) / SPAN);
}

/** A decoded step, ready to upload as textures. */
export interface StepPlanes {
	step: true;
	/** Area codes, `areaWidth` × `areaHeight`, row 0 the north. */
	area: Uint8Array;
	areaWidth: number;
	areaHeight: number;
	/** The bands' codes, band after band (lowest first), each `bandWidth` × `bandHeight`. */
	bands: Uint8Array;
	bandWidth: number;
	bandHeight: number;
	/** How many bands (0: no snow by elevation, the area alone). */
	bandCount: number;
	/** Metres between bands, from 0 m. */
	bandM: number;
}

function unfilter(plane: Uint8Array, width: number, height: number): void {
	for (let i = width, n = width * height; i < n; i++)
		plane[i] = (plane[i] + plane[i - width]) & 255;
}

/** A step from its inflated bytes; null if it isn't one. */
export function parseStep(raw: Uint8Array): StepPlanes | null {
	if (raw.length < HEADER_BYTES) return null;
	if (raw[0] !== 0x53 || raw[1] !== 0x57 || raw[2] !== 0x54 || raw[3] !== 0x31) return null; // "SWT1"
	const v = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
	const areaWidth = v.getUint16(4, true);
	const areaHeight = v.getUint16(6, true);
	const bandWidth = v.getUint16(8, true);
	const bandHeight = v.getUint16(10, true);
	const bandCount = raw[12];
	const bandM = raw[13] * 50;
	const n = areaWidth * areaHeight;
	const bn = bandWidth * bandHeight;
	if (!n || raw.length !== HEADER_BYTES + n + bandCount * bn) return null;
	if (bandCount && (!bn || !bandM)) return null;
	const area = raw.slice(HEADER_BYTES, HEADER_BYTES + n);
	unfilter(area, areaWidth, areaHeight);
	const bands = raw.slice(HEADER_BYTES + n);
	for (let k = 0; k < bandCount; k++)
		unfilter(bands.subarray(k * bn, (k + 1) * bn), bandWidth, bandHeight);
	return {
		step: true,
		area,
		areaWidth,
		areaHeight,
		bands,
		bandWidth,
		bandHeight,
		bandCount,
		bandM
	};
}
