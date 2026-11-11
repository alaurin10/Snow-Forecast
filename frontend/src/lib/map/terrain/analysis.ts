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
	const bit = 1 << (Math.round(aspect / 45) % 8);
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
	const stride = size + 2;
	const out = new Uint8ClampedArray(size * size * 4);
	const slopeRgb = SLOPE_CLASSES.map((s) => rgb(s.color));
	const aspectRgb = SECTORS.map((s) => rgb(ASPECT_COLORS[s]));
	const matchRgb = rgb(MATCH_COLOR);
	const rules = match ? ruleMasks(match) : [];
	let any = false;
	for (let r = 0; r < size; r++) {
		const lat = tileLat(y + (r + 0.5) / size, z);
		const m = metresPerPixel(lat, z, size);
		for (let c = 0; c < size; c++) {
			const { slope, aspect } = hornAt(grid, stride, r + 1, c + 1, m, m);
			let col: [number, number, number] | null = null;
			if (mode === 'slope') {
				const k = slopeClass(slope);
				if (k >= 0) col = slopeRgb[k];
			} else if (mode === 'aspect') {
				if (slope >= FLAT_DEG) col = aspectRgb[Math.round(aspect / 45) % 8];
			} else if (match && slope >= match.slopeMin) {
				if (matches(rules, aspect, grid[(r + 1) * stride + c + 1])) col = matchRgb;
			}
			if (col) {
				const j = (r * size + c) * 4;
				out[j] = col[0];
				out[j + 1] = col[1];
				out[j + 2] = col[2];
				out[j + 3] = 255;
				any = true;
			}
		}
	}
	return any ? out : null;
}
