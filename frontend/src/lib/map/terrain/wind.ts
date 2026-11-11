// Where wind likely moved the snow: scoured where the ground is open to the wind,
// loaded where higher ground upwind shelters it.
//
// The measure is Winstral's Sx (Winstral, Elder and Davis 2002): the steepest angle up
// to the terrain upwind of a spot, within a search distance. Positive means something
// upwind stands above the spot (lee, snow settles); negative means the ground only falls
// away upwind (windward or a crest, snow is stripped). As in the paper, Sx for a wind
// direction is the mean over a 30° fan of rays, and a near search (the slope itself and
// the roll just above it) is combined with a far one (the ridge the slope hangs from).
// The directions are weighted by how much snow each wind sector could move.

import { bilinear, halve, type Grid } from './grid';

const RAD = Math.PI / 180;
/** The near search: the slope itself. */
export const NEAR_M = 300;
/** The far search: ridge-scale shelter. Also how far beyond the view the grid must reach. */
export const FAR_M = 1500;
/** The deepest zoom the wind grid is built at: about 25 m a pixel here. */
export const WIND_ZOOM = 11;
/** Share of the near search in the combined angle. */
const NEAR_SHARE = 0.6;
/** A combined angle this many degrees up or down counts as fully sheltered or exposed. */
export const SX_FULL = 20;
/** The fan of rays averaged for one wind direction, degrees either side of it. */
const FAN = [-15, 0, 15];
/** Wind sectors carrying less than this share of the loading are left out. */
const MIN_SHARE = 0.05;
/** Below this the effect is too slight to draw or name. */
export const CLEAR = 0.1;
/** From here up it is drawn at full strength. */
const FULL = 0.7;

export interface Offsets {
	dr: Int32Array;
	dc: Int32Array;
	/** Distance along the ray, in pixels. */
	dist: Float32Array;
}

/**
 * Whole-pixel steps along a ray toward an azimuth, for distances in (from, to] pixels:
 * one step along the ray's longer axis at a time, the other rounded to the nearest pixel.
 */
export function rayOffsets(azimuth: number, from: number, to: number): Offsets {
	const sx = Math.sin(azimuth * RAD);
	const sy = -Math.cos(azimuth * RAD);
	const major = Math.max(Math.abs(sx), Math.abs(sy));
	const dr: number[] = [];
	const dc: number[] = [];
	const dist: number[] = [];
	for (let i = 1; i / major <= to + 1e-6; i++) {
		const d = i / major;
		if (d <= from + 1e-6) continue;
		dr.push(Math.round(sy * d));
		dc.push(Math.round(sx * d));
		dist.push(d);
	}
	return { dr: Int32Array.from(dr), dc: Int32Array.from(dc), dist: Float32Array.from(dist) };
}

/**
 * The steepest slope (as a tangent) from every pixel up to the terrain along a ray;
 * −Infinity where no step of the ray lands inside the grid.
 */
export function maxTan(g: Grid, o: Offsets, out: Float32Array): Float32Array {
	const { data: e, width: W, height: H, m } = g;
	out.fill(-Infinity);
	for (let k = 0; k < o.dist.length; k++) {
		const dr = o.dr[k];
		const dc = o.dc[k];
		const inv = 1 / (o.dist[k] * m);
		const off = dr * W + dc;
		const r0 = Math.max(0, -dr);
		const r1 = Math.min(H, H - dr);
		const c0 = Math.max(0, -dc);
		const c1 = Math.min(W, W - dc);
		for (let r = r0; r < r1; r++) {
			const end = r * W + c1;
			for (let i = r * W + c0; i < end; i++) {
				const v = (e[i + off] - e[i]) * inv;
				if (v > out[i]) out[i] = v;
			}
		}
	}
	return out;
}

/** Sx in degrees for wind from an azimuth, searching (from, to] metres upwind. */
export function sx(g: Grid, windFrom: number, from: number, to: number): Float32Array {
	const sum = new Float32Array(g.data.length);
	const buf = new Float32Array(g.data.length);
	for (const da of FAN) {
		maxTan(g, rayOffsets(windFrom + da, from / g.m, to / g.m), buf);
		for (let i = 0; i < sum.length; i++)
			if (buf[i] !== -Infinity) sum[i] += Math.atan(buf[i]) / RAD / FAN.length;
	}
	return sum;
}

/**
 * The wind effect on every pixel for one wind direction, −1 (stripped) to 1 (loaded),
 * added to `acc` with a weight.
 */
function addDirection(g: Grid, half: Grid, windFrom: number, weight: number, acc: Float32Array) {
	const near = sx(g, windFrom, 0, NEAR_M);
	const far = sx(half, windFrom, NEAR_M, FAR_M);
	const { width: W, height: H } = g;
	for (let r = 0; r < H; r++) {
		for (let c = 0; c < W; c++) {
			const i = r * W + c;
			const f = bilinear(far, half.width, half.height, (c + 0.5) / 2, (r + 0.5) / 2);
			const s = (NEAR_SHARE * near[i] + (1 - NEAR_SHARE) * f) / SX_FULL;
			acc[i] += weight * (s > 1 ? 1 : s < -1 ? -1 : s);
		}
	}
}

/** The sectors worth computing and their weights (summing to 1). */
export function windWeights(sectors: number[]): { azimuth: number; weight: number }[] {
	const kept = sectors
		.map((share, i) => ({ azimuth: i * 45, weight: share }))
		.filter((s) => s.weight >= MIN_SHARE);
	const total = kept.reduce((a, s) => a + s.weight, 0);
	return total > 0 ? kept.map((s) => ({ ...s, weight: s.weight / total })) : [];
}

/**
 * The wind effect over a grid, −1 (stripped) to 1 (loaded). `sectors` is the share of
 * the loading by the direction the wind blows from, north first, clockwise. `pause`
 * lets other work in between directions and says whether to carry on.
 */
export async function windEffect(
	g: Grid,
	sectors: number[],
	pause: () => Promise<boolean> = async () => true
): Promise<Float32Array | null> {
	const acc = new Float32Array(g.data.length);
	const half = halve(g);
	for (const { azimuth, weight } of windWeights(sectors)) {
		addDirection(g, half, azimuth, weight, acc);
		if (!(await pause())) return null;
	}
	return acc;
}

export interface WindInput {
	snowCm: number;
	meanKmh: number | null;
	/** Less new snow than this: nothing to move. */
	minSnowCm: number;
	/** Lighter wind than this: little drifting. */
	minWindKmh: number;
}

/**
 * How much snow the wind could move, 0 to 1: nothing below the thresholds, then more
 * with the wind (full 30 km/h above its threshold) and the new snow (full 20 cm above).
 */
export function transport(w: WindInput): number {
	if (w.meanKmh == null || w.snowCm < w.minSnowCm || w.meanKmh < w.minWindKmh) return 0;
	const wind = Math.min(1, (w.meanKmh - w.minWindKmh) / 30);
	const snow = Math.min(1, (w.snowCm - w.minSnowCm) / 20);
	return (0.4 + 0.6 * wind) * (0.5 + 0.5 * snow);
}

export const LOADED_COLOR = '#1b6f9c';
export const SCOURED_COLOR = '#b5651d';

function rgb(hex: string): [number, number, number] {
	const n = parseInt(hex.slice(1), 16);
	return [n >> 16, (n >> 8) & 255, n & 255];
}

/** The effect scaled by the transport, as a two-way wash: clear where it is slight. */
export function paintWind(effect: Float32Array, scale: number): Uint8ClampedArray<ArrayBuffer> {
	const out = new Uint8ClampedArray(effect.length * 4);
	const up = rgb(LOADED_COLOR);
	const down = rgb(SCOURED_COLOR);
	for (let i = 0, j = 0; i < effect.length; i++, j += 4) {
		const v = effect[i] * scale;
		const a = Math.abs(v);
		if (a < CLEAR) continue;
		const col = v > 0 ? up : down;
		out[j] = col[0];
		out[j + 1] = col[1];
		out[j + 2] = col[2];
		// Faint where little snow could move, solid only for a real wind event.
		out[j + 3] = Math.round(30 + 225 * Math.min(1, (a - CLEAR) / (FULL - CLEAR)));
	}
	return out;
}

/** In words, for a spot. */
export function windWord(v: number): string {
	const a = Math.abs(v);
	if (a < CLEAR) return 'Little wind effect';
	const much = a >= 0.35 ? 'Likely' : 'Somewhat';
	return `${much} ${v > 0 ? 'loaded' : 'scoured'}`;
}
