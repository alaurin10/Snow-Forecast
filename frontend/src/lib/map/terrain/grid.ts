// Elevation over an area as one grid, stitched from tiles: what the sun, shade and wind
// layers work on. A grid is a rectangle of Web Mercator pixels at one zoom (512 px
// tiles), so it lines up exactly with the map and with a canvas laid over it.

import { EARTH, TILE, type DemCache } from './dem';

/** [west, south, east, north] in degrees. */
export type Bounds = [number, number, number, number];

export interface Rect {
	/** Zoom of the pixel grid. */
	z: number;
	/** World pixel of the top-left corner at that zoom. */
	x0: number;
	y0: number;
	width: number;
	height: number;
}

export interface Grid extends Rect {
	/** Metres above sea level, row by row from the north-west corner. */
	data: Float32Array;
	/** Ground metres per pixel at the middle row. */
	m: number;
}

const RAD = Math.PI / 180;

/** World pixel of a longitude and latitude at a zoom. */
export function worldX(lon: number, z: number): number {
	return ((lon + 180) / 360) * TILE * 2 ** z;
}
export function worldY(lat: number, z: number): number {
	const s = Math.asinh(Math.tan(Math.max(-85, Math.min(85, lat)) * RAD));
	return ((1 - s / Math.PI) / 2) * TILE * 2 ** z;
}
export function lonOf(x: number, z: number): number {
	return (x / (TILE * 2 ** z)) * 360 - 180;
}
export function latOf(y: number, z: number): number {
	const n = Math.PI * (1 - (2 * y) / (TILE * 2 ** z));
	return Math.atan(Math.sinh(n)) / RAD;
}

export function rectBounds(r: Rect): Bounds {
	return [
		lonOf(r.x0, r.z),
		latOf(r.y0 + r.height, r.z),
		lonOf(r.x0 + r.width, r.z),
		latOf(r.y0, r.z)
	];
}

/** Ground metres per pixel at the middle of a rectangle. */
export function rectMetres(r: Rect): number {
	const lat = latOf(r.y0 + r.height / 2, r.z);
	return (EARTH * Math.cos(lat * RAD)) / (TILE * 2 ** r.z);
}

/** Bounds grown by a distance on every side. */
export function pad([w, s, e, n]: Bounds, metres: number): Bounds {
	const lat = (s + n) / 2;
	const dLat = metres / 111320;
	const dLon = metres / (111320 * Math.cos(lat * RAD));
	return [w - dLon, s - dLat, e + dLon, n + dLat];
}

/** A box of a given half-size around a point. */
export function around(lat: number, lon: number, metres: number): Bounds {
	return pad([lon, lat, lon, lat], metres);
}

/**
 * The pixel rectangle covering some bounds: the deepest zoom, up to `maxZoom`, at which
 * it is at most `maxPx` on its longer side.
 */
export function rectFor(b: Bounds, maxPx: number, maxZoom: number): Rect {
	let z = maxZoom;
	for (; z > 0; z--) {
		const w = worldX(b[2], z) - worldX(b[0], z);
		const h = worldY(b[1], z) - worldY(b[3], z);
		if (Math.max(w, h) <= maxPx) break;
	}
	const x0 = Math.floor(worldX(b[0], z));
	const y0 = Math.floor(worldY(b[3], z));
	const x1 = Math.ceil(worldX(b[2], z));
	const y1 = Math.ceil(worldY(b[1], z));
	return { z, x0, y0, width: Math.max(1, x1 - x0), height: Math.max(1, y1 - y0) };
}

export const rectKey = (r: Rect) => `${r.z}/${r.x0}/${r.y0}/${r.width}/${r.height}`;

/** Fetch and stitch the elevation for a rectangle. `alive` is asked between tiles. */
export async function mosaic(
	dem: Pick<DemCache, 'elev'>,
	rect: Rect,
	alive: () => boolean = () => true
): Promise<Grid | null> {
	const { z, x0, y0, width, height } = rect;
	const data = new Float32Array(width * height);
	const n = 2 ** z;
	const tx0 = Math.floor(x0 / TILE);
	const tx1 = Math.floor((x0 + width - 1) / TILE);
	const ty0 = Math.max(0, Math.floor(y0 / TILE));
	const ty1 = Math.min(n - 1, Math.floor((y0 + height - 1) / TILE));
	const jobs: Promise<void>[] = [];
	for (let ty = ty0; ty <= ty1; ty++) {
		for (let tx = tx0; tx <= tx1; tx++) {
			jobs.push(
				dem.elev(z, ((tx % n) + n) % n, ty).then((e) => {
					if (e.sea) return;
					// Tiles are TILE px here whatever size the source sent.
					const k = e.size / TILE;
					const c0 = Math.max(x0, tx * TILE);
					const c1 = Math.min(x0 + width, (tx + 1) * TILE);
					const r0 = Math.max(y0, ty * TILE);
					const r1 = Math.min(y0 + height, (ty + 1) * TILE);
					for (let r = r0; r < r1; r++) {
						const sr = Math.floor((r - ty * TILE) * k) * e.size;
						const dr = (r - y0) * width - x0;
						if (k === 1) {
							const from = sr + c0 - tx * TILE;
							data.set(e.data.subarray(from, from + c1 - c0), dr + c0);
						} else
							for (let c = c0; c < c1; c++)
								data[dr + c] = e.data[sr + Math.floor((c - tx * TILE) * k)];
					}
				})
			);
		}
	}
	await Promise.all(jobs);
	if (!alive()) return null;
	return { ...rect, data, m: rectMetres(rect) };
}

/** A grid at half the detail: each pixel the mean of four. */
export function halve(g: Grid): Grid {
	const width = g.width >> 1;
	const height = g.height >> 1;
	const data = new Float32Array(width * height);
	for (let r = 0; r < height; r++) {
		const a = 2 * r * g.width;
		const b = a + g.width;
		for (let c = 0; c < width; c++) {
			const i = 2 * c;
			data[r * width + c] =
				(g.data[a + i] + g.data[a + i + 1] + g.data[b + i] + g.data[b + i + 1]) / 4;
		}
	}
	return { z: g.z - 1, x0: g.x0 / 2, y0: g.y0 / 2, width, height, data, m: g.m * 2 };
}

/**
 * A value between pixels. (px, py) is measured from the grid's corner in its own
 * pixels, with pixel centres at halves; outside the grid the edge repeats.
 */
export function bilinear(
	data: Float32Array,
	width: number,
	height: number,
	px: number,
	py: number
): number {
	const fx = Math.min(width - 1, Math.max(0, px - 0.5));
	const fy = Math.min(height - 1, Math.max(0, py - 0.5));
	const c0 = Math.floor(fx);
	const r0 = Math.floor(fy);
	const c1 = Math.min(width - 1, c0 + 1);
	const r1 = Math.min(height - 1, r0 + 1);
	const tx = fx - c0;
	const ty = fy - r0;
	const a = r0 * width;
	const b = r1 * width;
	return (
		(data[a + c0] * (1 - tx) + data[a + c1] * tx) * (1 - ty) +
		(data[b + c0] * (1 - tx) + data[b + c1] * tx) * ty
	);
}

/** Where a pixel position of one grid falls in another, in that grid's pixels. */
export function into(from: Rect, to: Rect, px: number, py: number): [number, number] {
	const k = 2 ** (to.z - from.z);
	return [(from.x0 + px) * k - to.x0, (from.y0 + py) * k - to.y0];
}
