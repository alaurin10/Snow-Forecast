// A glacier tapped on the map, described from its mapped outline and the terrain under
// it: how high its top and toe are, which way it flows, how steep it is and how long.
// Pure functions: the points to sample (a grid over the ice and its outline), then the
// numbers from the terrain worker's elevation and slope at those points.
import { haversine, type LngLat } from './measure';
import { inPolygon, polygons } from './here';
import type { PointOut } from '../types.gen';

/** At most this many points in the grid over the ice (one worker call). */
export const GLACIER_SAMPLES = 400;
/** Points along the outline, where the top and the toe usually are. */
const EDGE_SAMPLES = 120;
/** Steeper than this, glacier ice is broken and avalanche terrain. */
export const STEEP_DEG = 30;

export interface GlacierGrid {
	/** Every point to sample: the grid's points inside the ice, then the outline's. */
	points: LngLat[];
	/** The grid: for each row (south to north) and column (west to east), the index into
	 *  `points`, or −1 off the ice. */
	cells: number[][];
	/** Metres between grid columns and rows. */
	dx: number;
	dy: number;
	/** How many of `points` are the grid's (the rest are the outline's). */
	inside: number;
}

/** Points over the glacier and along its outline, for the terrain worker. */
export function glacierGrid(g: GeoJSON.Geometry, max = GLACIER_SAMPLES): GlacierGrid | null {
	const polys = polygons(g);
	if (!polys.length) return null;
	let [w, s, e, n] = [Infinity, Infinity, -Infinity, -Infinity];
	for (const p of polys)
		for (const [lon, lat] of p[0]) {
			w = Math.min(w, lon);
			e = Math.max(e, lon);
			s = Math.min(s, lat);
			n = Math.max(n, lat);
		}
	if (!(e > w && n > s)) return null;
	const midLat = (s + n) / 2;
	const mLon = haversine([w, midLat], [e, midLat]);
	const mLat = haversine([w, s], [w, n]);
	// Square cells sized so about `max` of them fall on the box (more land on the ice
	// for a compact glacier; a thin one gets fewer, but always some).
	const step = Math.max(10, Math.sqrt((mLon * mLat) / max));
	const nx = Math.max(2, Math.round(mLon / step));
	const ny = Math.max(2, Math.round(mLat / step));
	const points: LngLat[] = [];
	const cells: number[][] = [];
	for (let j = 0; j < ny; j++) {
		const lat = s + ((j + 0.5) / ny) * (n - s);
		const row: number[] = [];
		for (let i = 0; i < nx; i++) {
			const lon = w + ((i + 0.5) / nx) * (e - w);
			if (polys.some((p) => inPolygon(p, lon, lat))) {
				row.push(points.length);
				points.push([lon, lat]);
			} else row.push(-1);
		}
		cells.push(row);
	}
	const inside = points.length;
	// The outlines, evenly by count, shared among the polygons by their size.
	const rings = polys.map((p) => p[0]);
	const total = rings.reduce((t, r) => t + r.length, 0);
	for (const r of rings) {
		const k = Math.max(4, Math.round((EDGE_SAMPLES * r.length) / total));
		for (let i = 0; i < k; i++) points.push(r[Math.floor((i * (r.length - 1)) / k)]);
	}
	return { points, cells, dx: mLon / nx, dy: mLat / ny, inside };
}

export interface GlacierStats {
	/** Highest and lowest ground on the ice, metres, and where. */
	top: number;
	toe: number;
	topAt: LngLat;
	toeAt: LngLat;
	/** Straight-line metres from the top to the toe. */
	length: number;
	/** The average slope of the ice, degrees, and the share of it steeper than STEEP_DEG. */
	slope: number;
	steep: number;
	/** The way it flows (compass degrees downhill), or null where that isn't clear. */
	flows: number | null;
}

/** The numbers, from the terrain worker's elevation and slope at the grid's points. */
export function glacierStats(
	grid: GlacierGrid,
	elev: number[],
	slope: number[]
): GlacierStats | null {
	const ok = (i: number) => i >= 0 && Number.isFinite(elev[i]);
	let top = -1;
	let toe = -1;
	for (let i = 0; i < grid.points.length; i++) {
		if (!ok(i)) continue;
		if (top < 0 || elev[i] > elev[top]) top = i;
		if (toe < 0 || elev[i] < elev[toe]) toe = i;
	}
	if (top < 0) return null;
	// Slope over the ice itself (the outline's points are half on rock).
	const within = Array.from({ length: grid.inside }, (_, i) => i).filter(
		(i) => ok(i) && Number.isFinite(slope[i])
	);
	const slopes = (within.length ? within : grid.points.map((_, i) => i).filter(ok)).map(
		(i) => slope[i]
	);
	const mean = slopes.reduce((a, b) => a + b, 0) / Math.max(1, slopes.length);
	const steep = slopes.filter((v) => v > STEEP_DEG).length / Math.max(1, slopes.length);
	// Downhill, summed over the grid: each cell's fall to the east and to the north from
	// its neighbours. A consistent direction is the way the ice flows.
	let fe = 0;
	let fn = 0;
	let mag = 0;
	const { cells, dx, dy } = grid;
	for (let j = 0; j < cells.length; j++)
		for (let i = 0; i < cells[j].length; i++) {
			if (!ok(cells[j][i])) continue;
			const at = (jj: number, ii: number) => {
				const k = cells[jj]?.[ii] ?? -1;
				return ok(k) ? elev[k] : null;
			};
			const [we, ea, so, no] = [at(j, i - 1), at(j, i + 1), at(j - 1, i), at(j + 1, i)];
			if (we == null || ea == null || so == null || no == null) continue;
			const gx = (we - ea) / (2 * dx);
			const gy = (so - no) / (2 * dy);
			fe += gx;
			fn += gy;
			mag += Math.hypot(gx, gy);
		}
	let flows: number | null = null;
	// Only when the cells mostly agree (a cirque or an ice cap falls every way).
	if (mag > 0 && Math.hypot(fe, fn) / mag > 0.35)
		flows = ((Math.atan2(fe, fn) * 180) / Math.PI + 360) % 360;
	// With too few cells for that, top to toe.
	if (flows == null && mag === 0 && top !== toe) {
		const [a, b] = [grid.points[top], grid.points[toe]];
		const east = (b[0] - a[0]) * Math.cos((a[1] * Math.PI) / 180);
		flows = ((Math.atan2(east, b[1] - a[1]) * 180) / Math.PI + 360) % 360;
	}
	return {
		top: elev[top],
		toe: elev[toe],
		topAt: grid.points[top],
		toeAt: grid.points[toe],
		length: haversine(grid.points[top], grid.points[toe]),
		slope: mean,
		steep,
		flows
	};
}

/** What the glacier card shows, as it comes in (undefined while loading). */
export interface GlacierInfo {
	/** Square metres; null when the outline couldn't be found. */
	area?: number | null;
	stats?: GlacierStats | null;
	/** The map's weather where it was tapped. */
	point?: PointOut | null;
	pointState: 'loading' | 'ready' | 'failed';
}
