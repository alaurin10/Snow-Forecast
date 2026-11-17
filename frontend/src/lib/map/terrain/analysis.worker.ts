// The terrain worker: fetches and decodes elevation tiles, fills the gaps, paints the
// slope and aspect overlays and answers point questions, all off the main thread.
//
// The page runs two of these (client.ts): one for tiles, taps and profiles, one for the
// whole-view layers, so map tiles never wait behind a sun-hours job. Each request can be
// called off (`cancel`), which also stops its downloads once nobody else wants them.
/// <reference lib="webworker" />
import {
	ANALYSIS_ZOOM,
	classify,
	hornAt,
	paintClasses,
	type Classes,
	type MatchParams,
	type TerrainMode
} from './analysis';
import {
	aborted,
	DemCache,
	encodeTerrarium,
	Lru,
	locate,
	metresPerPixel,
	sample,
	TILE,
	type Pixels
} from './dem';
import {
	around,
	bilinear,
	contains,
	into,
	latOf,
	mosaic,
	pad,
	rectBounds,
	rectFor,
	rectKey,
	snap,
	worldX,
	worldY,
	type Bounds,
	type Grid,
	type Rect
} from './grid';
import type { PointFacts, WorkerRequest, WorkerResponse } from './messages';
import {
	horizon,
	paintHours,
	paintShade,
	Shader,
	SHADE_REACH_M,
	sunHours,
	sunTimes
} from './shade';
import { sunPosition, type Ymd } from './sun';
import { FAR_M, paintWind, WIND_ZOOM, windEffect } from './wind';
import { concernCls, paintConcern } from './concern';

declare const self: DedicatedWorkerGlobalScope;

let canvas: OffscreenCanvas | null = null;
async function decode(blob: Blob): Promise<Pixels> {
	const bmp = await createImageBitmap(blob, {
		premultiplyAlpha: 'none',
		colorSpaceConversion: 'none'
	});
	const { width, height } = bmp;
	if (!canvas || canvas.width !== width || canvas.height !== height)
		canvas = new OffscreenCanvas(width, height);
	const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
	ctx.clearRect(0, 0, width, height);
	ctx.drawImage(bmp, 0, 0);
	bmp.close();
	return ctx.getImageData(0, 0, width, height);
}

let dem = new DemCache({ decode, online: () => self.navigator.onLine !== false });

/** Requests under way, each with its own way to call it off. */
const running = new Map<number, AbortController>();

function bitmap(rgba: Uint8ClampedArray<ArrayBuffer>, size: number): Promise<ImageBitmap> {
	return createImageBitmap(new ImageData(rgba, size, size), { premultiplyAlpha: 'none' });
}

/**
 * Let queued messages (a cancel, say) in. A message to ourselves rather than
 * setTimeout(0), which browsers stretch to 4 ms once nested: a sun-hours job yields
 * some thirty times.
 */
const yielder = new MessageChannel();
const yielded: (() => void)[] = [];
yielder.port1.onmessage = () => yielded.shift()?.();
const yieldNow = () =>
	new Promise<void>((done) => {
		yielded.push(done);
		yielder.port2.postMessage(0);
	});

/** Yield, then say whether the job is still wanted. */
const pause = (signal: AbortSignal) => async () => {
	await yieldNow();
	return !signal.aborted;
};

async function point(lat: number, lon: number, signal: AbortSignal): Promise<PointFacts> {
	// Elevation from the finest tile there is, slope and aspect at the overlays' scale.
	const fine = locate(lat, lon, 15);
	const e = await dem.elev(15, fine.x, fine.y, signal);
	const elevation = e.sea ? 0 : sample(e.data, e.size, fine.px, fine.py);
	const at = locate(lat, lon, ANALYSIS_ZOOM);
	const { grid, elev } = await dem.around(ANALYSIS_ZOOM, at.x, at.y, signal);
	const size = elev.size;
	const r = Math.min(size - 1, Math.floor(at.py));
	const c = Math.min(size - 1, Math.floor(at.px));
	const m = metresPerPixel(lat, ANALYSIS_ZOOM, size);
	const { slope, aspect } = hornAt(grid, size + 2, r + 1, c + 1, m, m);
	return {
		elevation,
		slope,
		aspect,
		sea: !!e.sea,
		srcZ: e.srcZ,
		metresPerPixel: m,
		fallback: dem.fallback
	};
}

/**
 * Elevation and ground slope along a line. Elevation from tiles at `z` (chosen by the
 * page from the spacing of the points), slope on the overlays' grid (zoom 12 at most):
 * finer slope is noise at the scale that matters for avalanches.
 */
async function profile(
	points: [number, number][],
	z: number,
	signal: AbortSignal
): Promise<{ elev: number[]; slope: number[] } | null> {
	const elev: number[] = [];
	const slope: number[] = [];
	const sz = Math.min(z, ANALYSIS_ZOOM);
	for (let i = 0; i < points.length; i++) {
		if (signal.aborted) return null;
		const [lon, lat] = points[i];
		const at = locate(lat, lon, z);
		const e = await dem.elev(z, at.x, at.y, signal);
		elev.push(e.sea ? 0 : sample(e.data, e.size, at.px, at.py));
		const sa = locate(lat, lon, sz);
		const { grid, elev: tile } = await dem.around(sz, sa.x, sa.y, signal);
		const size = tile.size;
		const r = Math.min(size - 1, Math.floor(sa.py));
		const c = Math.min(size - 1, Math.floor(sa.px));
		const m = metresPerPixel(lat, sz, size);
		slope.push(tile.sea ? 0 : hornAt(grid, size + 2, r + 1, c + 1, m, m).slope);
	}
	return { elev, slope };
}

// ---- Overlay tiles ----------------------------------------------------------------
// A tile's slope and aspect are kept, so a new mode or problem query only recolours,
// and so is where a zone's outline cuts it.

/** Tiles whose slope and aspect are kept (about 0.75 MB each). */
let classes = new Lru<{ k: Classes; size: number } | { sea: true }>(8);

/** Inside a zone: all of a tile, none of it, or these pixels. */
type Mask = 'in' | 'out' | Uint8Array;
const tileMasks = new Lru<Mask>(32);

/**
 * Which pixels of a rectangle (world pixels at zoom z, drawn `scale` times finer) lie
 * inside a zone's polygons: drawn on a canvas, even-odd so holes stay out.
 */
function zoneMask(
	r: { z: number; x0: number; y0: number; width: number; height: number },
	polys: number[][][][],
	scale = 1
): Uint8Array {
	const c = new OffscreenCanvas(r.width, r.height);
	const ctx = c.getContext('2d', { willReadFrequently: true })!;
	ctx.beginPath();
	for (const poly of polys)
		for (const ring of poly)
			ring.forEach(([lon, lat], i) => {
				const x = (worldX(lon, r.z) - r.x0) * scale;
				const y = (worldY(lat, r.z) - r.y0) * scale;
				if (i === 0) ctx.moveTo(x, y);
				else ctx.lineTo(x, y);
			});
	ctx.fillStyle = '#000';
	ctx.fill('evenodd');
	const a = ctx.getImageData(0, 0, r.width, r.height).data;
	const out = new Uint8Array(r.width * r.height);
	for (let i = 0; i < out.length; i++) out[i] = a[i * 4 + 3] >= 128 ? 1 : 0;
	return out;
}

function tileMask(
	zone: string,
	polys: number[][][][],
	z: number,
	x: number,
	y: number,
	size: number
): Mask {
	const key = `${zone}|${z}/${x}/${y}`;
	const have = tileMasks.get(key);
	if (have) return have;
	const m = zoneMask(
		{ z, x0: x * TILE, y0: y * TILE, width: size, height: size },
		polys,
		size / TILE
	);
	let n = 0;
	for (let i = 0; i < m.length; i++) n += m[i];
	const mask: Mask = n === m.length ? 'in' : n === 0 ? 'out' : m;
	tileMasks.set(key, mask);
	return mask;
}

/** Zones the page has told us about, for clipping tiles and the concern index (the newest few). */
const zonePolys = new Map<string, number[][][][]>();

async function overlayTile(
	msg: Extract<WorkerRequest, { type: 'tile' }>,
	signal: AbortSignal
): Promise<Uint8ClampedArray<ArrayBuffer> | null> {
	const { z, x, y } = msg;
	// A tile clipped to a zone the page hasn't described yet stays clear.
	const polys = msg.zone ? zonePolys.get(msg.zone) : undefined;
	if (msg.zone && !polys) return null;
	const key = `${z}/${x}/${y}`;
	let got = classes.get(key);
	let elev: Float32Array | null = null;
	if (!got) {
		const { grid, elev: e } = await dem.around(z, x, y, signal);
		got = e.sea ? { sea: true } : { k: classify(grid, e.size, z, y), size: e.size };
		classes.set(key, got);
		elev = e.data;
	}
	if ('sea' in got || signal.aborted) return null;
	const { k, size } = got;
	const mask = polys ? tileMask(msg.zone!, polys, z, x, y, size) : 'in';
	if (mask === 'out') return null;
	// Only matching reads the heights (the tile is usually still in the cache).
	if (msg.mode === 'match' && !elev) elev = (await dem.elev(z, x, y, signal)).data;
	const rgba = paintClasses(
		msg.mode as TerrainMode,
		k,
		elev ?? new Float32Array(0),
		size,
		msg.match as MatchParams | undefined
	);
	if (!rgba || mask === 'in') return rgba;
	let any = false;
	for (let i = 0; i < mask.length; i++)
		if (!mask[i]) rgba[i * 4 + 3] = 0;
		else if (rgba[i * 4 + 3]) any = true;
	return any ? rgba : null;
}

// ---- Whole-view layers: shade, sun hours, wind effect, concern ---------------------
// Each view's rectangle is snapped outward to whole SNAP_PX steps, and its grids and
// results are kept for a few views: a view still inside one (a nudge, panning back, a
// layer switched off and on, the date or wind set back) reuses it, and its picture
// covers the whole kept rectangle.

/** Views kept for each layer (set by `init`: 1 on phones, 2 on desktop). */
let keepViews = 2;

interface SunView {
	rect: Rect;
	shader: Shader;
	/** Sun hours by date. */
	hours: Lru<Float32Array>;
}
let suns = new Lru<SunView>(keepViews);

async function sunFor(bounds: Bounds, maxPx: number, signal: AbortSignal): Promise<SunView | null> {
	const view = rectFor(bounds, maxPx, ANALYSIS_ZOOM);
	const have = suns.find((v) => contains(v.rect, view));
	if (have) return have;
	const fineRect = snap(view);
	const coarseRect = rectFor(pad(rectBounds(fineRect), SHADE_REACH_M), maxPx / 2, fineRect.z);
	const alive = () => !signal.aborted;
	const [fine, coarse] = await Promise.all([
		mosaic(dem, fineRect, alive, signal),
		mosaic(dem, coarseRect, alive, signal)
	]);
	if (!fine || !coarse) return null;
	const v = { rect: fineRect, shader: new Shader(fine, coarse), hours: new Lru<Float32Array>(2) };
	suns.set(rectKey(fineRect), v);
	return v;
}

async function hoursFor(v: SunView, date: Ymd, signal: AbortSignal): Promise<Float32Array | null> {
	const key = date.join('-');
	const have = v.hours.get(key);
	if (have) return have;
	const { lat, lon } = centre(v.shader.fine);
	const h = await sunHours(v.shader, date, lat, lon, pause(signal));
	if (h) v.hours.set(key, h);
	return h;
}

/** The middle of a grid, where the sun's position is taken for the whole view. */
function centre(g: Grid): { lat: number; lon: number } {
	const [w, s, e, n] = rectBounds(g);
	return { lat: (s + n) / 2, lon: (w + e) / 2 };
}

type Area = Extract<WorkerRequest, { bounds: Bounds }>;

interface WindView {
	rect: Rect;
	grid: Grid;
	/** The effect by wind sectors. */
	effects: Lru<Float32Array>;
}
let winds = new Lru<WindView>(keepViews);

/** The wind effect over a view (padded so the upwind search has terrain), kept for reuse. */
async function windFor(
	bounds: Bounds,
	maxPx: number,
	sectors: number[],
	signal: AbortSignal
): Promise<{ grid: Grid; effect: Float32Array } | null> {
	const need = rectFor(pad(bounds, FAR_M), maxPx, WIND_ZOOM);
	let view = winds.find((v) => contains(v.rect, need));
	if (!view) {
		const rect = snap(need);
		const grid = await mosaic(dem, rect, () => !signal.aborted, signal);
		if (!grid) return null;
		view = { rect, grid, effects: new Lru<Float32Array>(2) };
		winds.set(rectKey(rect), view);
	}
	const key = sectors.join();
	let effect = view.effects.get(key) ?? null;
	if (!effect) {
		effect = await windEffect(view.grid, sectors, pause(signal));
		if (!effect) return null;
		view.effects.set(key, effect);
	}
	return { grid: view.grid, effect };
}

/** Plain elevation grids for the concern index when sun hours don't count. */
let plains = new Lru<{ rect: Rect; grid: Grid }>(keepViews);
/** The last concern zone mask: [grid key + zone, pixels]. */
let concernMask: [string, Uint8Array] | null = null;

/**
 * The concern index for a view: slope and aspect from the view's own grid, the wind
 * effect and the day's sun hours only when they count, inside the forecast zone only.
 */
async function concern(
	msg: Extract<WorkerRequest, { type: 'concern' }>,
	signal: AbortSignal
): Promise<{ rgba: Uint8ClampedArray<ArrayBuffer>; grid: Grid } | null> {
	const { bounds, maxPx, inputs, params } = msg;
	const polys = zonePolys.get(msg.zone);
	if (!polys) throw new Error(`zone ${msg.zone} not sent`);
	let grid: Grid;
	let hours: Float32Array | null = null;
	if (msg.sunDate && inputs.sun) {
		const v = await sunFor(bounds, maxPx, signal);
		if (!v) return null;
		grid = v.shader.fine;
		hours = await hoursFor(v, msg.sunDate, signal);
		if (!hours) return null;
	} else {
		const view = rectFor(bounds, maxPx, ANALYSIS_ZOOM);
		let plain = plains.find((p) => contains(p.rect, view));
		if (!plain) {
			const rect = snap(view);
			const g = await mosaic(dem, rect, () => !signal.aborted, signal);
			if (!g) return null;
			plain = { rect, grid: g };
			plains.set(rectKey(rect), plain);
		}
		grid = plain.grid;
	}
	const wind =
		inputs.wind && msg.windSectors && msg.windScale > 0
			? await windFor(bounds, maxPx, msg.windSectors, signal)
			: null;
	if (signal.aborted) return null;
	const maskKey = `${rectKey(grid)}|${msg.zone}`;
	if (concernMask?.[0] !== maskKey) concernMask = [maskKey, zoneMask(grid, polys)];
	const inside = concernMask[1];
	const { width: W, height: H, data } = grid;
	const cls = new Int8Array(W * H).fill(-1);
	const minSlope = params.slope[0][0];
	const DEG = 180 / Math.PI;
	for (let r = 1; r < H - 1; r++) {
		const m8 = 8 * metresPerPixel(latOf(grid.y0 + r + 0.5, grid.z), grid.z);
		for (let c = 1; c < W - 1; c++) {
			const i = r * W + c;
			if (!inside[i] || data[i] === 0) continue;
			// hornAt, written out: no object per pixel.
			const a = data[i - W - 1];
			const b = data[i - W];
			const cc = data[i - W + 1];
			const d = data[i - 1];
			const f = data[i + 1];
			const gg = data[i + W - 1];
			const h = data[i + W];
			const ii = data[i + W + 1];
			const dzdx = (cc + 2 * f + ii - (a + 2 * d + gg)) / m8;
			const dzdy = (gg + 2 * h + ii - (a + 2 * b + cc)) / m8;
			const slope = Math.atan(Math.hypot(dzdx, dzdy)) * DEG;
			if (slope < minSlope) continue;
			let aspect = Math.atan2(-dzdx, dzdy) * DEG;
			if (aspect < 0) aspect += 360;
			let w: number | null = null;
			if (wind) {
				const [px, py] = into(grid, wind.grid, c + 0.5, r + 0.5);
				w = bilinear(wind.effect, wind.grid.width, wind.grid.height, px, py) * msg.windScale;
			}
			cls[i] = concernCls(
				data[i],
				slope,
				Math.round(aspect / 45) % 8,
				w,
				hours ? hours[i] : null,
				inputs,
				params
			);
		}
	}
	return { rgba: paintConcern(cls), grid };
}

async function area(
	msg: Area,
	signal: AbortSignal
): Promise<{ rgba: Uint8ClampedArray<ArrayBuffer>; grid: Grid } | null> {
	if (msg.type === 'wind') {
		const w = await windFor(msg.bounds, msg.maxPx, msg.sectors, signal);
		return w && { rgba: paintWind(w.effect, msg.scale), grid: w.grid };
	}
	if (msg.type === 'concern') return concern(msg, signal);
	const v = await sunFor(msg.bounds, msg.maxPx, signal);
	if (!v) return null;
	if (msg.type === 'shade') {
		const { lat, lon } = centre(v.shader.fine);
		const { azimuth, altitude } = sunPosition(msg.time, lat, lon);
		return {
			rgba: paintShade(v.shader.fine, v.shader.run(azimuth, altitude), altitude),
			grid: v.shader.fine
		};
	}
	const hours = await hoursFor(v, msg.date, signal);
	return hours && { rgba: paintHours(hours), grid: v.shader.fine };
}

async function handle(
	msg: Exclude<WorkerRequest, { type: 'cancel' }>,
	signal: AbortSignal
): Promise<{ res: WorkerResponse; transfer: Transferable[] }> {
	const { id } = msg;
	const empty = { res: { id, ok: true, empty: true } as WorkerResponse, transfer: [] };
	switch (msg.type) {
		case 'dem': {
			const t = await dem.demTile(msg.z, msg.x, msg.y, signal);
			if (signal.aborted) throw aborted();
			const fallback = dem.fallback;
			if ('bytes' in t) {
				// A copy: the cache keeps the original for analysis and the next request.
				const bytes = t.bytes.slice(0);
				return { res: { id, ok: true, bytes, fallback }, transfer: [bytes] };
			}
			const bmp = await bitmap(encodeTerrarium(t.data), t.size);
			return { res: { id, ok: true, bitmap: bmp, fallback }, transfer: [bmp] };
		}
		case 'tile': {
			const rgba = await overlayTile(msg, signal);
			if (!rgba || signal.aborted) return empty;
			const bmp = await bitmap(rgba, Math.sqrt(rgba.length / 4));
			return { res: { id, ok: true, bitmap: bmp }, transfer: [bmp] };
		}
		case 'point':
			return { res: { id, ok: true, point: await point(msg.lat, msg.lon, signal) }, transfer: [] };
		case 'shade':
		case 'sunhours':
		case 'wind':
		case 'concern': {
			const done = await area(msg, signal);
			if (!done || signal.aborted) return empty;
			const bmp = await createImageBitmap(
				new ImageData(done.rgba, done.grid.width, done.grid.height),
				{ premultiplyAlpha: 'none' }
			);
			return { res: { id, ok: true, bitmap: bmp, bounds: rectBounds(done.grid) }, transfer: [bmp] };
		}
		case 'sunpoint': {
			// Fine terrain close by, coarse out to where mountains still matter.
			const [fine, coarse] = await Promise.all([
				mosaic(dem, rectFor(around(msg.lat, msg.lon, 2500), 512, ANALYSIS_ZOOM), undefined, signal),
				mosaic(dem, rectFor(around(msg.lat, msg.lon, SHADE_REACH_M), 640, 10), undefined, signal)
			]);
			if (!fine || !coarse) throw aborted();
			const h = horizon([fine, coarse], msg.lat, msg.lon);
			return { res: { id, ok: true, sun: sunTimes(h, msg.date, msg.lat, msg.lon) }, transfer: [] };
		}
		case 'windpoint': {
			const g = await mosaic(
				dem,
				rectFor(around(msg.lat, msg.lon, FAR_M + 100), 512, WIND_ZOOM),
				undefined,
				signal
			);
			if (!g) throw aborted();
			const effect = await windEffect(g, msg.sectors, pause(signal));
			if (!effect) throw aborted();
			const wind = bilinear(
				effect,
				g.width,
				g.height,
				worldX(msg.lon, g.z) - g.x0,
				worldY(msg.lat, g.z) - g.y0
			);
			return { res: { id, ok: true, wind }, transfer: [] };
		}
		case 'profile': {
			const p = await profile(msg.points, msg.z, signal);
			return p ? { res: { id, ok: true, profile: p }, transfer: [] } : empty;
		}
		case 'zone':
			zonePolys.delete(msg.zone);
			zonePolys.set(msg.zone, msg.polys);
			while (zonePolys.size > 6) zonePolys.delete(zonePolys.keys().next().value!);
			return { res: { id, ok: true }, transfer: [] };
		case 'init':
			keepViews = msg.keepViews ?? 2;
			suns = new Lru<SunView>(keepViews);
			winds = new Lru<WindView>(keepViews);
			plains = new Lru<{ rect: Rect; grid: Grid }>(keepViews);
			concernMask = null;
			classes = new Lru(msg.overlayTiles ?? 8);
			dem = new DemCache({
				decode,
				maxTiles: msg.maxTiles,
				maxFiles: msg.maxFiles,
				online: () => self.navigator.onLine !== false
			});
			return { res: { id, ok: true }, transfer: [] };
	}
}

self.onmessage = (ev: MessageEvent<WorkerRequest>) => {
	const msg = ev.data;
	if (msg.type === 'cancel') {
		// Only a request still under way: a late cancel leaves nothing behind.
		running.get(msg.target)?.abort();
		self.postMessage({ id: msg.id, ok: true });
		return;
	}
	const ctl = new AbortController();
	running.set(msg.id, ctl);
	handle(msg, ctl.signal).then(
		({ res, transfer }) => {
			running.delete(msg.id);
			self.postMessage(res, transfer);
		},
		(e: unknown) => {
			running.delete(msg.id);
			self.postMessage({
				id: msg.id,
				ok: false,
				error: e instanceof Error ? e.message : String(e)
			});
		}
	);
};
