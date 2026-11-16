// Slope and aspect from elevation, and the colours the terrain overlays paint them in.
//
// Horn's 3×3 method on a tile with a one-pixel border (see dem.ts `bordered`), using
// ground metres per pixel for each row's latitude. Analysis runs at zoom 12 at most
// (about 10–13 m a pixel across the West): finer lidar slope is mostly noise at the
// scale avalanches care about.

import { metresPerPixel, tileLat } from './dem';

/** The deepest zoom the slope and aspect overlays are computed at. */
export const ANALYSIS_ZOOM = 12;

export type TerrainMode = 'slope' | 'aspect' | 'match';

/** Compass sectors, clockwise from north. */
export const SECTORS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const;
export type Sector = (typeof SECTORS)[number];

/** Slope classes as drawn: clear below 25°. `from` is the first whole degree in the class. */
export const SLOPE_CLASSES = [
	{ from: 25, label: '25–29°', color: '#f2dc3d' },
	{ from: 30, label: '30–34°', color: '#f39a2c' },
	{ from: 35, label: '35–39°', color: '#e2402b' },
	{ from: 40, label: '40–45°', color: '#a8329f' },
	{ from: 46, label: '46–50°', color: '#3f55d1' },
	{ from: 51, label: '51°+', color: '#1b1b1f' }
] as const;

export const ASPECT_COLORS: Record<Sector, string> = {
	N: '#2f63d6',
	NE: '#27a7c4',
	E: '#3fb456',
	SE: '#b9cc33',
	S: '#f2c12e',
	SW: '#f0862a',
	W: '#d8413a',
	NW: '#8f49c2'
};
/** Below this, ground is too flat for its aspect to mean much. */
export const FLAT_DEG = 5;
/** Teal: nothing like a danger-scale colour, so it can't read as a rating. */
export const MATCH_COLOR = '#0fa3b1';

/** One way terrain can match: any of these aspects within any of these elevation ranges. */
export interface MatchRule {
	aspects: Sector[];
	/** [lowest, highest] metres; an empty list means every elevation. */
	ranges: [number, number][];
}

export interface MatchParams {
	/** Lowest slope that counts, degrees. */
	slopeMin: number;
	/** A pixel matches if any rule does (one rule per avalanche problem). */
	rules: MatchRule[];
}

/** Aspect bit masks, one per rule, for the painting loop. */
function ruleMasks(match: MatchParams) {
	return match.rules.map((r) => ({
		mask: r.aspects.reduce((m, s) => m | (1 << SECTORS.indexOf(s)), 0),
		ranges: r.ranges
	}));
}

/** Whether an aspect (compass degrees) and elevation meet any rule. */
export function matches(
	rules: { mask: number; ranges: [number, number][] }[],
	aspect: number,
	elev: number
): boolean {
	return matchesSector(rules, Math.round(aspect / 45) % 8, elev);
}

/** The same, from the aspect's sector (index into SECTORS). */
function matchesSector(
	rules: { mask: number; ranges: [number, number][] }[],
	sector: number,
	elev: number
): boolean {
	const bit = 1 << sector;
	for (const r of rules) {
		if (!(r.mask & bit)) continue;
		if (!r.ranges.length) return true;
		for (const [lo, hi] of r.ranges) if (elev >= lo && elev <= hi) return true;
	}
	return false;
}

function rgb(hex: string): [number, number, number] {
	const n = parseInt(hex.slice(1), 16);
	return [n >> 16, (n >> 8) & 255, n & 255];
}

/** Slope in degrees and aspect in compass degrees (the way the slope faces). */
export function hornAt(
	g: Float32Array,
	stride: number,
	r: number,
	c: number,
	mx: number,
	my: number
): { slope: number; aspect: number } {
	const i = r * stride + c;
	const a = g[i - stride - 1];
	const b = g[i - stride];
	const cc = g[i - stride + 1];
	const d = g[i - 1];
	const f = g[i + 1];
	const gg = g[i + stride - 1];
	const h = g[i + stride];
	const ii = g[i + stride + 1];
	// Rise to the east, and rise to the south (rows run southward).
	const dzdx = (cc + 2 * f + ii - (a + 2 * d + gg)) / (8 * mx);
	const dzdy = (gg + 2 * h + ii - (a + 2 * b + cc)) / (8 * my);
	const slope = (Math.atan(Math.hypot(dzdx, dzdy)) * 180) / Math.PI;
	// The slope faces downhill: east component −dzdx, north component +dzdy.
	let aspect = (Math.atan2(-dzdx, dzdy) * 180) / Math.PI;
	if (aspect < 0) aspect += 360;
	return { slope, aspect };
}

export function sectorOf(aspect: number): Sector {
	return SECTORS[Math.round(aspect / 45) % 8];
}

/** Which class a slope falls in (index into SLOPE_CLASSES), −1 below 25°. */
export function slopeClass(deg: number): number {
	const d = Math.floor(deg);
	for (let k = SLOPE_CLASSES.length - 1; k >= 0; k--) if (d >= SLOPE_CLASSES[k].from) return k;
	return -1;
}

/**
 * A tile's slope and aspect, worked out once and kept: changing the overlay's mode or the
 * avalanche problems it matches then only recolours. Slope in hundredths of a degree
 * (rounded down), aspect as its compass sector (index into SECTORS).
 */
export interface Classes {
	slope: Uint16Array;
	sector: Uint8Array;
}

/** Slope and aspect for every pixel of a tile. `grid` has a one-pixel border, as for `paint`. */
export function classify(grid: Float32Array, size: number, z: number, y: number): Classes {
	const stride = size + 2;
	const slope = new Uint16Array(size * size);
	const sector = new Uint8Array(size * size);
	const DEG = 180 / Math.PI;
	for (let r = 0; r < size; r++) {
		const lat = tileLat(y + (r + 0.5) / size, z);
		const m8 = 8 * metresPerPixel(lat, z, size);
		for (let c = 0; c < size; c++) {
			// hornAt, written out: no object per pixel.
			const i = (r + 1) * stride + c + 1;
			const a = grid[i - stride - 1];
			const b = grid[i - stride];
			const cc = grid[i - stride + 1];
			const d = grid[i - 1];
			const f = grid[i + 1];
			const gg = grid[i + stride - 1];
			const h = grid[i + stride];
			const ii = grid[i + stride + 1];
			const dzdx = (cc + 2 * f + ii - (a + 2 * d + gg)) / m8;
			const dzdy = (gg + 2 * h + ii - (a + 2 * b + cc)) / m8;
			const deg = Math.atan(Math.hypot(dzdx, dzdy)) * DEG;
			let aspect = Math.atan2(-dzdx, dzdy) * DEG;
			if (aspect < 0) aspect += 360;
			const j = r * size + c;
			slope[j] = Math.floor(deg * 100);
			sector[j] = Math.round(aspect / 45) % 8;
		}
	}
	return { slope, sector };
}

/**
 * Colour a tile from its slope and aspect (see `classify`); `elev` is the tile's own
 * elevations (size² values), read by `match`. Returns RGBA pixels, or null when nothing
 * would show.
 */
export function paintClasses(
	mode: TerrainMode,
	k: Classes,
	elev: Float32Array,
	size: number,
	match?: MatchParams
): Uint8ClampedArray<ArrayBuffer> | null {
	const out = new Uint8ClampedArray(size * size * 4);
	const slopeRgb = SLOPE_CLASSES.map((s) => rgb(s.color));
	const aspectRgb = SECTORS.map((s) => rgb(ASPECT_COLORS[s]));
	const matchRgb = rgb(MATCH_COLOR);
	const rules = match ? ruleMasks(match) : [];
	// Slope classes by whole degree, so the loop needn't search the class list.
	const byDegree = Array.from({ length: 91 }, (_, d) => slopeClass(d));
	const flat = FLAT_DEG * 100;
	const min = match ? Math.ceil(match.slopeMin * 100) : 0;
	let any = false;
	for (let j = 0; j < size * size; j++) {
		const sl = k.slope[j];
		let col: [number, number, number] | null = null;
		if (mode === 'slope') {
			const c = byDegree[Math.min(90, Math.floor(sl / 100))];
			if (c >= 0) col = slopeRgb[c];
		} else if (mode === 'aspect') {
			if (sl >= flat) col = aspectRgb[k.sector[j]];
		} else if (match && sl >= min) {
			if (matchesSector(rules, k.sector[j], elev[j])) col = matchRgb;
		}
		if (col) {
			const o = j * 4;
			out[o] = col[0];
			out[o + 1] = col[1];
			out[o + 2] = col[2];
			out[o + 3] = 255;
			any = true;
		}
	}
	return any ? out : null;
}

/** The middle of a bordered grid: the tile's own elevations. */
export function unborder(grid: Float32Array, size: number): Float32Array {
	const stride = size + 2;
	const out = new Float32Array(size * size);
	for (let r = 0; r < size; r++)
		out.set(grid.subarray((r + 1) * stride + 1, (r + 1) * stride + 1 + size), r * size);
	return out;
}

/**
 * Paint one tile. `grid` is the tile's elevations with a one-pixel border
 * ((size + 2)² values). Returns RGBA pixels, or null when nothing would show.
 */
export function paint(
	mode: TerrainMode,
	grid: Float32Array,
	size: number,
	z: number,
	y: number,
	match?: MatchParams
): Uint8ClampedArray<ArrayBuffer> | null {
	return paintClasses(mode, classify(grid, size, z, y), unborder(grid, size), size, match);
}
