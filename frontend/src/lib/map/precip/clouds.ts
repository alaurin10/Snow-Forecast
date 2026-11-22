// Forecast clouds as numbers (backend/snowwatch/maps/cloudheights.py; keep in step).
//
// A frame is the total cover and, where NOAA's National Blend of Models gives cloud
// heights (the US and Canada to about 55°N, to ~84 h), the low cloud's base, top and
// cover and the cover of the cloud above it, in metres above sea level. Zoomed in, the map
// holds each pixel's elevation against them: ground inside the cloud is fog, ground above
// its top is clear, ground beneath its base lightly shaded (./cloudgl.ts).
//
// The file is a gzip stream of a 16-byte header ("SWC1", width, height, flags, metres per
// height step / 10, region pixels per plane pixel) and byte planes, each row stored as the
// difference from the row above: cover, then with heights known, low, base, top (when the
// tops are known) and above. Covers are 0..250 (0.4% a code).

export const HAS_HEIGHTS = 1;
export const HAS_TOPS = 2;
const HEADER_BYTES = 16;
/** Codes per 100% of cover. */
export const COVER_FULL = 250;

/** A decoded frame, ready to upload: two textures' worth of interleaved bytes. */
export interface CloudPlanes {
	cloud: true;
	width: number;
	height: number;
	/** Region pixels per plane pixel. */
	ds: number;
	flags: number;
	/** Metres per height code. */
	stepM: number;
	/** cover, known, low, above: four bytes a pixel, row 0 the north. */
	shares: Uint8Array;
	/** base, top: two bytes a pixel (zeros without heights; top 255 without tops). */
	heights: Uint8Array;
}

function unfilter(plane: Uint8Array, width: number, height: number): void {
	for (let i = width, n = width * height; i < n; i++)
		plane[i] = (plane[i] + plane[i - width]) & 255;
}

/** A frame from its inflated bytes; null if it isn't one. */
export function parseClouds(raw: Uint8Array): CloudPlanes | null {
	if (raw.length < HEADER_BYTES) return null;
	if (raw[0] !== 0x53 || raw[1] !== 0x57 || raw[2] !== 0x43 || raw[3] !== 0x31) return null; // "SWC1"
	const v = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
	const width = v.getUint16(4, true);
	const height = v.getUint16(6, true);
	const flags = raw[8];
	const stepM = raw[9] * 10;
	const ds = v.getUint16(10, true) || 4;
	const n = width * height;
	const heights = !!(flags & HAS_HEIGHTS);
	const tops = heights && !!(flags & HAS_TOPS);
	const count = heights ? (tops ? 6 : 5) : 1;
	if (!n || raw.length !== HEADER_BYTES + count * n) return null;
	if (heights && !stepM) return null;
	const planes: Uint8Array[] = [];
	for (let k = 0; k < count; k++) {
		const p = raw.slice(HEADER_BYTES + k * n, HEADER_BYTES + (k + 1) * n);
		unfilter(p, width, height);
		planes.push(p);
	}
	const [cover, known, low, base, ...rest] = planes;
	const top = tops ? rest[0] : undefined;
	const above = heights ? rest[rest.length - 1] : undefined;
	const shares = new Uint8Array(n * 4);
	const hts = new Uint8Array(n * 2);
	for (let i = 0; i < n; i++) {
		shares[i * 4] = cover[i];
		if (heights) {
			shares[i * 4 + 1] = known[i];
			shares[i * 4 + 2] = low[i];
			shares[i * 4 + 3] = above![i];
			hts[i * 2] = base[i];
			hts[i * 2 + 1] = top ? top[i] : 255;
		}
	}
	return { cloud: true, width, height, ds, flags, stepM: stepM || 30, shares, heights: hts };
}

/**
 * What the ground at `elev` metres looks like under a pixel's clouds (the shader's sums,
 * for tests and words): `fog` the share of it hidden in cloud, `shade` the dimming of
 * ground beneath cloud. Covers in %, heights in metres (`top` Infinity: unknown).
 */
export function cloudAt(
	elev: number,
	c: { low: number; above: number; base: number; top: number }
): { fog: number; shade: number } {
	const edge = (a: number, b: number, x: number) => {
		const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
		return t * t * (3 - 2 * t);
	};
	const inside =
		edge(c.base - FEATHER_M, c.base + FEATHER_M, elev) *
		(1 - edge(c.top - FEATHER_M, c.top + FEATHER_M, elev));
	const below = 1 - edge(c.base - FEATHER_M, c.base + FEATHER_M, elev);
	const low = c.low / 100;
	const above = c.above / 100;
	const overhead = below * (1 - (1 - low) * (1 - above)) + (1 - below) * above;
	return { fog: low * inside, shade: overhead * (1 - inside * low) };
}

/** Metres over which the ground goes into or out of the cloud (a soft cloud line). */
export const FEATHER_M = 60;
