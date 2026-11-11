// Shadows cast by terrain, for a sun position or summed over a day.
//
// A shadow map for one sun position is a single sweep across the grid, starting at the
// side the sun is on: each pixel takes the height of the shadow's upper surface from
// the pixel next to it on the sun's side (between two pixels when the sun isn't square
// to the grid), lowered by the sun's slope over that step, or its own ground if that is
// higher. Ground below that surface is in shade. One pass, a few milliseconds, so a
// whole day of them is cheap enough to do while the map is being looked at.
//
// Mountains shade ground many kilometres away when the sun is low, as it is all winter
// here. So the sweep runs twice: on a coarse grid reaching 15 km beyond the view, then
// on the fine grid of the view itself, which starts from the coarse result at its edges.

import { bilinear, into, worldX, worldY, type Grid } from './grid';
import { daySteps, sunDay, sunPosition, type Ymd } from './sun';

const RAD = Math.PI / 180;
/** How far away terrain can shade the view, metres. */
export const SHADE_REACH_M = 15000;
/** Shadow this deep over the ground counts as full shade; shallower fades out (a soft edge). */
export const SOFT_M = 1.5;
/** The sun this low is treated as set: its light is skimming and mostly lost in haze. */
const MIN_ALTITUDE = 0.25;
const DARK = 1e4;

/**
 * The height of the shadow's upper surface over every pixel, written to `out`: equal
 * to the ground where the sun reaches it. `edge(r, c)` gives the depth of shadow
 * arriving from beyond the grid.
 */
export function cast(
	g: Grid,
	azimuth: number,
	altitude: number,
	out: Float32Array,
	edge: (r: number, c: number) => number = () => 0
): Float32Array {
	const { data: e, width: W, height: H, m } = g;
	if (altitude <= MIN_ALTITUDE) {
		for (let i = 0; i < e.length; i++) out[i] = e[i] + DARK;
		return out;
	}
	const t = Math.tan(Math.min(89.9, altitude) * RAD);
	// Toward the sun, in pixels: east is +column, south is +row.
	const sx = Math.sin(azimuth * RAD);
	const sy = -Math.cos(azimuth * RAD);
	if (Math.abs(sx) >= Math.abs(sy)) {
		const dir = sx > 0 ? 1 : -1;
		const k = sy / Math.abs(sx);
		const drop = m * Math.hypot(1, k) * t;
		const first = dir > 0 ? W - 1 : 0;
		for (let r = 0; r < H; r++) out[r * W + first] = e[r * W + first] + edge(r, first);
		for (let c = first - dir; c >= 0 && c < W; c -= dir) {
			const u = c + dir;
			for (let r = 0; r < H; r++) {
				const i = r * W + c;
				const fr = r + k;
				if (fr < 0 || fr > H - 1) {
					out[i] = e[i] + edge(r, c);
					continue;
				}
				const r0 = Math.floor(fr);
				const f = fr - r0;
				const r1 = r0 + 1 < H ? r0 + 1 : r0;
				const h = out[r0 * W + u] * (1 - f) + out[r1 * W + u] * f - drop;
				out[i] = h > e[i] ? h : e[i];
			}
		}
	} else {
		const dir = sy > 0 ? 1 : -1;
		const k = sx / Math.abs(sy);
		const drop = m * Math.hypot(1, k) * t;
		const first = dir > 0 ? H - 1 : 0;
		for (let c = 0; c < W; c++) out[first * W + c] = e[first * W + c] + edge(first, c);
		for (let r = first - dir; r >= 0 && r < H; r -= dir) {
			const u = (r + dir) * W;
			for (let c = 0; c < W; c++) {
				const i = r * W + c;
				const fc = c + k;
				if (fc < 0 || fc > W - 1) {
					out[i] = e[i] + edge(r, c);
					continue;
				}
				const c0 = Math.floor(fc);
				const f = fc - c0;
				const c1 = c0 + 1 < W ? c0 + 1 : c0;
				const h = out[u + c0] * (1 - f) + out[u + c1] * f - drop;
				out[i] = h > e[i] ? h : e[i];
			}
		}
	}
	return out;
}

/** Shadows over a fine grid, with far terrain from a coarse one around it. */
export class Shader {
	private ceilFine: Float32Array;
	private ceilCoarse: Float32Array | null;

	constructor(
		readonly fine: Grid,
		readonly coarse: Grid | null = null
	) {
		this.ceilFine = new Float32Array(fine.data.length);
		this.ceilCoarse = coarse ? new Float32Array(coarse.data.length) : null;
	}

	/**
	 * The shadow surface over the fine grid for a sun position (valid until the next
	 * call). Depth of shade at a pixel is this minus the ground.
	 */
	run(azimuth: number, altitude: number): Float32Array {
		const { fine, coarse } = this;
		if (!coarse || !this.ceilCoarse) return cast(fine, azimuth, altitude, this.ceilFine);
		const cc = cast(coarse, azimuth, altitude, this.ceilCoarse);
		const ce = coarse.data;
		const edge = (r: number, c: number) => {
			const [px, py] = into(fine, coarse, c + 0.5, r + 0.5);
			const d =
				bilinear(cc, coarse.width, coarse.height, px, py) -
				bilinear(ce, coarse.width, coarse.height, px, py);
			return d > 0 ? d : 0;
		};
		return cast(fine, azimuth, altitude, this.ceilFine, edge);
	}
}

/**
 * Hours of direct sun on each pixel of the shader's fine grid through one day, from
 * sweeps about every half hour. `pause` lets other work in between sweeps and says
 * whether to carry on.
 */
export async function sunHours(
	shader: Shader,
	date: Ymd,
	lat: number,
	lon: number,
	pause: () => Promise<boolean> = async () => true,
	minutes = 30
): Promise<Float32Array | null> {
	const { times, hours } = daySteps(sunDay(date, lat, lon), minutes);
	const e = shader.fine.data;
	const out = new Float32Array(e.length);
	for (const t of times) {
		const { azimuth, altitude } = sunPosition(t, lat, lon);
		const ceil = shader.run(azimuth, altitude);
		for (let i = 0; i < out.length; i++) if (ceil[i] - e[i] < SOFT_M / 2) out[i] += hours;
		if (!(await pause())) return null;
	}
	return out;
}

// ---- Painting ----------------------------------------------------------------------

function rgb(hex: string): [number, number, number] {
	const n = parseInt(hex.slice(1), 16);
	return [n >> 16, (n >> 8) & 255, n & 255];
}

export const SHADE_COLOR = '#0b1430';

/** Shade as a dark veil; sunlit ground stays clear. */
export function paintShade(g: Grid, ceil: Float32Array): Uint8ClampedArray<ArrayBuffer> {
	const out = new Uint8ClampedArray(g.data.length * 4);
	const [cr, cg, cb] = rgb(SHADE_COLOR);
	const e = g.data;
	for (let i = 0, j = 0; i < e.length; i++, j += 4) {
		const d = ceil[i] - e[i];
		if (d <= 0) continue;
		out[j] = cr;
		out[j + 1] = cg;
		out[j + 2] = cb;
		out[j + 3] = d >= SOFT_M ? 255 : Math.round((d / SOFT_M) * 255);
	}
	return out;
}

/** Hours of direct sun in a day, as drawn. `from` is the least hours in the class. */
export const SUN_CLASSES = [
	{ from: 0, label: 'Under 1 h', color: '#1d1b4b' },
	{ from: 1, label: '1–2 h', color: '#4a2f7a' },
	{ from: 2, label: '2–4 h', color: '#8a3f86' },
	{ from: 4, label: '4–6 h', color: '#c9566f' },
	{ from: 6, label: '6–8 h', color: '#ef8a4c' },
	{ from: 8, label: '8 h or more', color: '#f9d057' }
] as const;

export function sunClass(hours: number): number {
	for (let k = SUN_CLASSES.length - 1; k > 0; k--) if (hours >= SUN_CLASSES[k].from) return k;
	return 0;
}

export function paintHours(hours: Float32Array): Uint8ClampedArray<ArrayBuffer> {
	const out = new Uint8ClampedArray(hours.length * 4);
	const cols = SUN_CLASSES.map((c) => rgb(c.color));
	for (let i = 0, j = 0; i < hours.length; i++, j += 4) {
		const c = cols[sunClass(hours[i])];
		out[j] = c[0];
		out[j + 1] = c[1];
		out[j + 2] = c[2];
		out[j + 3] = 255;
	}
	return out;
}

// ---- One spot: its horizon, and when the sun clears it ----------------------------------

/** Degrees between the directions the horizon is measured in. */
export const HORIZON_STEP = 2;

/**
 * How high the terrain stands above the level in each direction from a spot, in
 * degrees (negative where the ground only falls away), every HORIZON_STEP degrees
 * clockwise from north. `grids` are finest first; each is used where it reaches.
 */
export function horizon(grids: Grid[], lat: number, lon: number, reach = SHADE_REACH_M) {
	const fine = grids[0];
	const at = (g: Grid, east: number, south: number): number | null => {
		const px = worldX(lon, g.z) - g.x0 + east / g.m;
		const py = worldY(lat, g.z) - g.y0 + south / g.m;
		if (px < 0.5 || py < 0.5 || px > g.width - 0.5 || py > g.height - 0.5) return null;
		return bilinear(g.data, g.width, g.height, px, py);
	};
	const z0 = at(fine, 0, 0) ?? 0;
	const n = Math.round(360 / HORIZON_STEP);
	const out = new Float32Array(n);
	for (let k = 0; k < n; k++) {
		const a = k * HORIZON_STEP * RAD;
		const sx = Math.sin(a);
		const sy = -Math.cos(a);
		let best = -Infinity;
		let gi = 0;
		for (let d = fine.m; d <= reach;) {
			let z = at(grids[gi], d * sx, d * sy);
			while (z === null && gi < grids.length - 1) z = at(grids[++gi], d * sx, d * sy);
			if (z === null) break;
			const tan = (z - z0) / d;
			if (tan > best) best = tan;
			d += grids[gi].m;
		}
		out[k] = best === -Infinity ? 0 : Math.atan(best) / RAD;
	}
	return out;
}

/** The horizon's height in one direction, between the measured ones. */
export function horizonAt(h: Float32Array, azimuth: number): number {
	const f = ((((azimuth % 360) + 360) % 360) / 360) * h.length;
	const i = Math.floor(f) % h.length;
	const t = f - Math.floor(f);
	return h[i] * (1 - t) + h[(i + 1) % h.length] * t;
}

export interface SunFacts {
	date: Ymd;
	/** Unix milliseconds of the first and last direct sun; null when there is none. */
	first: number | null;
	last: number | null;
	/** Hours of direct sun in the day. */
	hours: number;
	/** The day's sunrise and sunset on a flat horizon. */
	sunrise: number | null;
	sunset: number | null;
}

/** When the sun clears a spot's horizon through a day, minute by minute. */
export function sunTimes(h: Float32Array, date: Ymd, lat: number, lon: number): SunFacts {
	const day = sunDay(date, lat, lon);
	const out: SunFacts = {
		date,
		first: null,
		last: null,
		hours: 0,
		sunrise: day.sunrise,
		sunset: day.sunset
	};
	if (day.sunrise == null || day.sunset == null) return out;
	let lit = 0;
	const start = Math.ceil(day.sunrise / 60000) * 60000;
	for (let t = start; t <= day.sunset; t += 60000) {
		const { azimuth, altitude } = sunPosition(t, lat, lon);
		if (altitude <= MIN_ALTITUDE || altitude <= horizonAt(h, azimuth)) continue;
		lit++;
		out.first ??= t;
		out.last = t;
	}
	out.hours = lit / 60;
	return out;
}
