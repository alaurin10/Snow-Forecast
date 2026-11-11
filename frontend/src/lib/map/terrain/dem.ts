// Elevation tiles for the map and for terrain analysis.
//
// Mapterhorn serves Terrarium-encoded 512 px WebP tiles: 1 m US lidar (zoom 16) and 2 m
// Canadian lidar (zoom 15) where it has been flown, 10 m (US) or 30 m (Canada) elsewhere
// to zoom 12. It answers 404 over open sea and beyond each area's finest zoom, so a
// missing tile is filled from its parent (bilinear), or is sea level at zoom 12 and
// below. If Mapterhorn keeps failing, the AWS terrain tiles (256 px, to zoom 15) take
// over for the rest of the session.
//
// Everything here is plain code with the image decoder passed in, so it runs in the
// terrain worker and in tests.

export const MAPTERHORN = 'https://tiles.mapterhorn.com';
export const AWS_DEM = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium';
export const TILE = 512;
/** Mapterhorn has every land tile to this zoom; a 404 at or below it is open water. */
export const BASE_ZOOM = 12;
/** The finest zoom any area has (US lidar). */
export const MAX_ZOOM = 16;
/** Network failures in a row before switching to the AWS tiles. */
const FAILS_BEFORE_FALLBACK = 4;
export const EARTH = 40075016.686;

export const mapterhornUrl = (z: number, x: number, y: number) =>
	`${MAPTERHORN}/${z}/${x}/${y}.webp`;
export const awsUrl = (z: number, x: number, y: number) => `${AWS_DEM}/${z}/${x}/${y}.png`;

/** RGBA pixels, as a canvas gives them. */
export interface Pixels {
	data: Uint8ClampedArray;
	width: number;
	height: number;
}
export type Decode = (blob: Blob) => Promise<Pixels>;

/** Elevations in metres, row by row from the north-west corner. */
export interface Elev {
	data: Float32Array;
	size: number;
	/** The zoom the numbers really came from (lower than the tile's when filled in). */
	srcZ: number;
	/** Open water: every value is 0. */
	sea?: boolean;
}

export function decodeTerrarium(px: Pixels): Float32Array {
	const n = px.width * px.height;
	const out = new Float32Array(n);
	const d = px.data;
	for (let i = 0, j = 0; i < n; i++, j += 4)
		out[i] = d[j] * 256 + d[j + 1] + d[j + 2] / 256 - 32768;
	return out;
}

export function encodeTerrarium(elev: Float32Array): Uint8ClampedArray<ArrayBuffer> {
	const out = new Uint8ClampedArray(elev.length * 4);
	for (let i = 0, j = 0; i < elev.length; i++, j += 4) {
		const v = Math.min(65535.99, Math.max(0, elev[i] + 32768));
		const whole = Math.floor(v);
		out[j] = whole >> 8;
		out[j + 1] = whole & 255;
		out[j + 2] = Math.floor((v - whole) * 256);
		out[j + 3] = 255;
	}
	return out;
}

/**
 * One child tile's worth of a parent tile, `levels` zooms down, resampled bilinearly
 * to the full tile size. (qx, qy) is the child's position inside the parent, in
 * 0 … 2^levels − 1.
 */
export function upsample(
	parent: Float32Array,
	size: number,
	qx: number,
	qy: number,
	levels = 1
): Float32Array {
	const k = 2 ** levels;
	const out = new Float32Array(size * size);
	const span = size / k;
	const x0 = qx * span;
	const y0 = qy * span;
	const last = size - 1;
	for (let r = 0; r < size; r++) {
		// Pixel centres: child pixel r covers parent rows y0 + (r + 0.5) / k.
		const fy = Math.min(last, Math.max(0, y0 + (r + 0.5) / k - 0.5));
		const r0 = Math.floor(fy);
		const r1 = Math.min(last, r0 + 1);
		const ty = fy - r0;
		for (let c = 0; c < size; c++) {
			const fx = Math.min(last, Math.max(0, x0 + (c + 0.5) / k - 0.5));
			const c0 = Math.floor(fx);
			const c1 = Math.min(last, c0 + 1);
			const tx = fx - c0;
			const a = parent[r0 * size + c0];
			const b = parent[r0 * size + c1];
			const cc = parent[r1 * size + c0];
			const d = parent[r1 * size + c1];
			out[r * size + c] = (a * (1 - tx) + b * tx) * (1 - ty) + (cc * (1 - tx) + d * tx) * ty;
		}
	}
	return out;
}

/** Four 256 px tiles (NW, NE, SW, SE) side by side as one 512 px tile. */
export function stitch(quads: Float32Array[], half: number): Float32Array {
	const size = half * 2;
	const out = new Float32Array(size * size);
	quads.forEach((q, i) => {
		const ox = (i % 2) * half;
		const oy = Math.floor(i / 2) * half;
		for (let r = 0; r < half; r++)
			out.set(q.subarray(r * half, (r + 1) * half), (oy + r) * size + ox);
	});
	return out;
}

// ---- Tile and ground geometry ------------------------------------------------

export function tileLat(y: number, z: number): number {
	const n = Math.PI - (2 * Math.PI * y) / 2 ** z;
	return (180 / Math.PI) * Math.atan(Math.sinh(n));
}

/** Ground metres per pixel of a TILE-px tile at this latitude and zoom. */
export function metresPerPixel(lat: number, z: number, size = TILE): number {
	return (EARTH * Math.cos((lat * Math.PI) / 180)) / (2 ** z * size);
}

/** The tile and the fractional pixel inside it that hold a point. */
export function locate(lat: number, lon: number, z: number, size = TILE) {
	const n = 2 ** z;
	const fx = ((lon + 180) / 360) * n;
	const r = (lat * Math.PI) / 180;
	const fy = ((1 - Math.asinh(Math.tan(r)) / Math.PI) / 2) * n;
	const x = Math.floor(fx);
	const y = Math.floor(fy);
	return { x, y, px: (fx - x) * size, py: (fy - y) * size };
}

/**
 * A tile with a one-pixel border from its eight neighbours, so slope at the tile's
 * edge sees the terrain beyond it. `around` is the 3×3 block, row by row, centre at 4;
 * a missing neighbour repeats the tile's own edge.
 */
export function bordered(around: (Float32Array | null)[], size: number): Float32Array {
	const s = size + 2;
	const out = new Float32Array(s * s);
	const mid = around[4]!;
	const at = (t: Float32Array | null, r: number, c: number, fr: number, fc: number) =>
		t ? t[r * size + c] : mid[fr * size + fc];
	for (let r = 0; r < size; r++) out.set(mid.subarray(r * size, (r + 1) * size), (r + 1) * s + 1);
	const L = size - 1;
	for (let i = 0; i < size; i++) {
		out[i + 1] = at(around[1], L, i, 0, i); // north
		out[(s - 1) * s + i + 1] = at(around[7], 0, i, L, i); // south
		out[(i + 1) * s] = at(around[3], i, L, i, 0); // west
		out[(i + 1) * s + s - 1] = at(around[5], i, 0, i, L); // east
	}
	out[0] = at(around[0], L, L, 0, 0);
	out[s - 1] = at(around[2], L, 0, 0, L);
	out[(s - 1) * s] = at(around[6], 0, L, L, 0);
	out[s * s - 1] = at(around[8], 0, 0, L, L);
	return out;
}

/** Bilinear elevation at a fractional pixel. */
export function sample(e: Float32Array, size: number, px: number, py: number): number {
	const fx = Math.min(size - 1, Math.max(0, px - 0.5));
	const fy = Math.min(size - 1, Math.max(0, py - 0.5));
	const c0 = Math.floor(fx);
	const r0 = Math.floor(fy);
	const c1 = Math.min(size - 1, c0 + 1);
	const r1 = Math.min(size - 1, r0 + 1);
	const tx = fx - c0;
	const ty = fy - r0;
	return (
		(e[r0 * size + c0] * (1 - tx) + e[r0 * size + c1] * tx) * (1 - ty) +
		(e[r1 * size + c0] * (1 - tx) + e[r1 * size + c1] * tx) * ty
	);
}

// ---- Fetching and caching --------------------------------------------------------

/** What the source had for a tile: the original file, decoded numbers, or nothing. */
interface Got {
	bytes?: ArrayBuffer;
	elev?: Float32Array;
	size?: number;
	sea?: boolean;
	missing?: boolean;
}

class Lru<V> {
	private m = new Map<string, V>();
	constructor(private max: number) {}
	get(k: string): V | undefined {
		const v = this.m.get(k);
		if (v !== undefined) {
			this.m.delete(k);
			this.m.set(k, v);
		}
		return v;
	}
	set(k: string, v: V) {
		this.m.delete(k);
		this.m.set(k, v);
		while (this.m.size > this.max) this.m.delete(this.m.keys().next().value!);
	}
	get size() {
		return this.m.size;
	}
}

export interface DemOptions {
	decode: Decode;
	fetch?: typeof fetch;
	/** Decoded tiles kept (about 1 MB each). */
	maxTiles?: number;
	online?: () => boolean;
}

export class DemCache {
	private got = new Lru<Got>(96);
	private elevs: Lru<Elev>;
	private pending = new Map<string, Promise<unknown>>();
	private fails = 0;
	/** Using the AWS tiles instead of Mapterhorn. */
	fallback = false;
	private decode: Decode;
	private fetcher: typeof fetch;
	private online: () => boolean;

	constructor(o: DemOptions) {
		this.decode = o.decode;
		this.fetcher = o.fetch ?? ((...a) => fetch(...a));
		this.elevs = new Lru<Elev>(o.maxTiles ?? 40);
		this.online = o.online ?? (() => true);
	}

	private once<T>(key: string, make: () => Promise<T>): Promise<T> {
		let p = this.pending.get(key) as Promise<T> | undefined;
		if (!p) {
			p = make().finally(() => this.pending.delete(key));
			this.pending.set(key, p);
		}
		return p;
	}

	private failed() {
		if (this.online() && ++this.fails >= FAILS_BEFORE_FALLBACK) this.fallback = true;
	}

	/** One tile as the upstream has it. */
	private source(z: number, x: number, y: number): Promise<Got> {
		const key = `${this.fallback ? 'a' : 'm'}${z}/${x}/${y}`;
		const have = this.got.get(key);
		if (have) return Promise.resolve(have);
		return this.once(`g${key}`, async () => {
			const got = this.fallback ? await this.fromAws(z, x, y) : await this.fromMapterhorn(z, x, y);
			this.got.set(key, got);
			return got;
		});
	}

	private async fromMapterhorn(z: number, x: number, y: number): Promise<Got> {
		let res: Response;
		try {
			res = await this.fetcher(mapterhornUrl(z, x, y), { mode: 'cors' });
		} catch {
			this.failed();
			return { missing: true };
		}
		if (res.status === 404) {
			this.fails = 0;
			return z <= BASE_ZOOM ? { sea: true } : { missing: true };
		}
		if (!res.ok) {
			// A saved-maps miss while offline also lands here (504): fill from the parent.
			if (res.status !== 504) this.failed();
			return { missing: true };
		}
		this.fails = 0;
		return { bytes: await res.arrayBuffer() };
	}

	/** The same tile from four AWS 256 px tiles one zoom deeper. */
	private async fromAws(z: number, x: number, y: number): Promise<Got> {
		if (z + 1 > 15) return { missing: true };
		try {
			const quads = await Promise.all(
				[0, 1, 2, 3].map(async (i) => {
					const res = await this.fetcher(awsUrl(z + 1, 2 * x + (i % 2), 2 * y + (i >> 1)), {
						mode: 'cors'
					});
					if (!res.ok) throw new Error(String(res.status));
					const px = await this.decode(await res.blob());
					return { e: decodeTerrarium(px), w: px.width };
				})
			);
			return {
				elev: stitch(
					quads.map((q) => q.e),
					quads[0].w
				),
				size: quads[0].w * 2
			};
		} catch {
			return { missing: true };
		}
	}

	/** Elevations for a tile, filled in from coarser tiles where it doesn't exist. */
	elev(z: number, x: number, y: number): Promise<Elev> {
		const key = `${z}/${x}/${y}`;
		const have = this.elevs.get(key);
		if (have) return Promise.resolve(have);
		return this.once(`e${key}`, async () => {
			const e = await this.build(z, x, y);
			this.elevs.set(key, e);
			return e;
		});
	}

	private async build(z: number, x: number, y: number): Promise<Elev> {
		const got = await this.source(z, x, y);
		if (got.bytes) {
			const px = await this.decode(new Blob([got.bytes]));
			return { data: decodeTerrarium(px), size: px.width, srcZ: z };
		}
		if (got.elev) return { data: got.elev, size: got.size!, srcZ: z };
		if (got.sea) return seaTile(z);
		if (z === 0) throw new Error('no elevation');
		const parent = await this.elev(z - 1, x >> 1, y >> 1);
		if (parent.sea) return seaTile(parent.srcZ);
		return {
			data: upsample(parent.data, parent.size, x & 1, y & 1),
			size: parent.size,
			srcZ: parent.srcZ
		};
	}

	/**
	 * A tile for MapLibre's raster-dem source: the original file when the upstream has
	 * it (MapLibre decodes it), otherwise filled-in numbers to encode.
	 */
	async demTile(z: number, x: number, y: number): Promise<{ bytes: ArrayBuffer } | Elev> {
		const got = await this.source(z, x, y);
		if (got.bytes) return { bytes: got.bytes };
		return this.elev(z, x, y);
	}

	/** The tile and its eight neighbours, for edge-aware analysis. */
	async around(z: number, x: number, y: number): Promise<{ grid: Float32Array; elev: Elev }> {
		const n = 2 ** z;
		const tiles = await Promise.all(
			[-1, 0, 1].flatMap((dy) =>
				[-1, 0, 1].map((dx) => {
					const ty = y + dy;
					if (ty < 0 || ty >= n) return Promise.resolve(null);
					return this.elev(z, (x + dx + n) % n, ty).catch(() => null);
				})
			)
		);
		const mid = tiles[4];
		if (!mid) throw new Error('no elevation');
		const size = mid.size;
		const same = tiles.map((t) => (t && t.size === size ? t.data : null));
		return { grid: bordered(same, size), elev: mid };
	}
}

const seas = new Map<number, Float32Array>();
function seaTile(srcZ: number, size = TILE): Elev {
	let data = seas.get(size);
	if (!data) seas.set(size, (data = new Float32Array(size * size)));
	return { data, size, srcZ, sea: true };
}
