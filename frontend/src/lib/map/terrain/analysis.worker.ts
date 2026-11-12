// The terrain worker: fetches and decodes elevation tiles, fills the gaps, paints the
// slope and aspect overlays and answers point questions, all off the main thread.
/// <reference lib="webworker" />
import { ANALYSIS_ZOOM, hornAt, paint, type MatchParams, type TerrainMode } from './analysis';
import {
	DemCache,
	encodeTerrarium,
	locate,
	metresPerPixel,
	sample,
	TILE,
	type Pixels
} from './dem';
import {
	around,
	bilinear,
	into,
	latOf,
	mosaic,
	pad,
	rectBounds,
	rectFor,
	rectKey,
	worldX,
	worldY,
	type Bounds,
	type Grid
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
import { sunPosition } from './sun';
import { FAR_M, paintWind, WIND_ZOOM, windEffect } from './wind';
import { concernAt, paintConcern } from './concern';

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
const cancelled = new Set<number>();

function bitmap(rgba: Uint8ClampedArray<ArrayBuffer>, size: number): Promise<ImageBitmap> {
	return createImageBitmap(new ImageData(rgba, size, size), { premultiplyAlpha: 'none' });
}

async function point(lat: number, lon: number): Promise<PointFacts> {
	// Elevation from the finest tile there is, slope and aspect at the overlays' scale.
	const fine = locate(lat, lon, 15);
	const e = await dem.elev(15, fine.x, fine.y);
	const elevation = e.sea ? 0 : sample(e.data, e.size, fine.px, fine.py);
	const at = locate(lat, lon, ANALYSIS_ZOOM);
	const { grid, elev } = await dem.around(ANALYSIS_ZOOM, at.x, at.y);
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
	id: number,
	points: [number, number][],
	z: number
): Promise<{ elev: number[]; slope: number[] } | null> {
	const elev: number[] = [];
	const slope: number[] = [];
	const sz = Math.min(z, ANALYSIS_ZOOM);
	for (let i = 0; i < points.length; i++) {
		if (i % 50 === 0 && cancelled.has(id)) return null;
		const [lon, lat] = points[i];
		const at = locate(lat, lon, z);
		const e = await dem.elev(z, at.x, at.y);
		elev.push(e.sea ? 0 : sample(e.data, e.size, at.px, at.py));
		const sa = locate(lat, lon, sz);
		const { grid, elev: tile } = await dem.around(sz, sa.x, sa.y);
		const size = tile.size;
		const r = Math.min(size - 1, Math.floor(sa.py));
		const c = Math.min(size - 1, Math.floor(sa.px));
		const m = metresPerPixel(lat, sz, size);
		slope.push(tile.sea ? 0 : hornAt(grid, size + 2, r + 1, c + 1, m, m).slope);
	}
	return { elev, slope };
}

// ---- Whole-view layers: shade, sun hours, wind effect -------------------------------
// The grids of the last view are kept, so moving the time slider or changing the wind
// window only repeats the arithmetic, not the downloads.

/** Let queued messages (a cancel, say) in, then say whether this job is still wanted. */
const pause = (id: number) => () =>
	new Promise<boolean>((done) => setTimeout(() => done(!cancelled.has(id))));

let sunView: { key: string; shader: Shader } | null = null;
let windView: { key: string; grid: Grid; sectors: string; effect: Float32Array | null } | null =
	null;

async function shaderFor(id: number, bounds: Bounds, maxPx: number): Promise<Shader | null> {
	const fineRect = rectFor(bounds, maxPx, ANALYSIS_ZOOM);
	const coarseRect = rectFor(pad(rectBounds(fineRect), SHADE_REACH_M), maxPx / 2, fineRect.z);
	const key = `${rectKey(fineRect)}|${rectKey(coarseRect)}`;
	if (sunView?.key === key) return sunView.shader;
	const alive = () => !cancelled.has(id);
	const [fine, coarse] = await Promise.all([
		mosaic(dem, fineRect, alive),
		mosaic(dem, coarseRect, alive)
	]);
	if (!fine || !coarse) return null;
	sunView = { key, shader: new Shader(fine, coarse) };
	return sunView.shader;
}

/** The middle of a grid, where the sun's position is taken for the whole view. */
function centre(g: Grid): { lat: number; lon: number } {
	const [w, s, e, n] = rectBounds(g);
	return { lat: (s + n) / 2, lon: (w + e) / 2 };
}

type Area = Extract<WorkerRequest, { bounds: Bounds }>;

/** The wind effect over a view (padded so the upwind search has terrain), kept for reuse. */
async function windFor(
	id: number,
	bounds: Bounds,
	maxPx: number,
	sectors: number[]
): Promise<{ grid: Grid; effect: Float32Array } | null> {
	const rect = rectFor(pad(bounds, FAR_M), maxPx, WIND_ZOOM);
	const key = rectKey(rect);
	if (windView?.key !== key) {
		const grid = await mosaic(dem, rect, () => !cancelled.has(id));
		if (!grid) return null;
		windView = { key, grid, sectors: '', effect: null };
	}
	const view = windView;
	const want = sectors.join();
	if (!view.effect || view.sectors !== want) {
		const effect = await windEffect(view.grid, sectors, pause(id));
		if (!effect) return null;
		view.effect = effect;
		view.sectors = want;
	}
	return { grid: view.grid, effect: view.effect };
}

let concernView: { key: string; grid: Grid } | null = null;

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

/** Zones the page has told us about, for clipping tiles (the newest few). */
const zonePolys = new Map<string, number[][][][]>();

/**
 * The concern index for a view: slope and aspect from the view's own grid, the wind
 * effect and the day's sun hours only when they count, inside the forecast zone only.
 */
async function concern(
	msg: Extract<WorkerRequest, { type: 'concern' }>
): Promise<{ rgba: Uint8ClampedArray<ArrayBuffer>; grid: Grid } | null> {
	const { id, bounds, maxPx, inputs, params } = msg;
	let grid: Grid | null;
	let hours: Float32Array | null = null;
	if (msg.sunDate && inputs.sun) {
		const shader = await shaderFor(id, bounds, maxPx);
		if (!shader) return null;
		grid = shader.fine;
		const { lat, lon } = centre(grid);
		hours = await sunHours(shader, msg.sunDate, lat, lon, pause(id));
		if (!hours) return null;
	} else {
		const rect = rectFor(bounds, maxPx, ANALYSIS_ZOOM);
		const key = rectKey(rect);
		if (concernView?.key !== key) {
			const g = await mosaic(dem, rect, () => !cancelled.has(id));
			if (!g) return null;
			concernView = { key, grid: g };
		}
		grid = concernView.grid;
	}
	const wind =
		inputs.wind && msg.windSectors && msg.windScale > 0
			? await windFor(id, bounds, maxPx, msg.windSectors)
			: null;
	if (cancelled.has(id)) return null;
	const inside = zoneMask(grid, msg.zone);
	const { width: W, height: H, data } = grid;
	const cls = new Int8Array(W * H).fill(-1);
	for (let r = 1; r < H - 1; r++) {
		const m = metresPerPixel(latOf(grid.y0 + r + 0.5, grid.z), grid.z);
		for (let c = 1; c < W - 1; c++) {
			const i = r * W + c;
			if (!inside[i] || data[i] === 0) continue;
			const { slope, aspect } = hornAt(data, W, r, c, m, m);
			if (slope < params.slope[0][0]) continue;
			let w: number | null = null;
			if (wind) {
				const [px, py] = into(grid, wind.grid, c + 0.5, r + 0.5);
				w = bilinear(wind.effect, wind.grid.width, wind.grid.height, px, py) * msg.windScale;
			}
			const f = concernAt(
				{ elev: data[i], slope, aspect, wind: w, sunHours: hours ? hours[i] : null },
				inputs,
				params
			);
			cls[i] = f.cls;
		}
	}
	return { rgba: paintConcern(cls), grid };
}

async function area(
	msg: Area
): Promise<{ rgba: Uint8ClampedArray<ArrayBuffer>; grid: Grid } | null> {
	if (msg.type === 'wind') {
		const w = await windFor(msg.id, msg.bounds, msg.maxPx, msg.sectors);
		return w && { rgba: paintWind(w.effect, msg.scale), grid: w.grid };
	}
	if (msg.type === 'concern') return concern(msg);
	const shader = await shaderFor(msg.id, msg.bounds, msg.maxPx);
	if (!shader) return null;
	const { lat, lon } = centre(shader.fine);
	if (msg.type === 'shade') {
		const { azimuth, altitude } = sunPosition(msg.time, lat, lon);
		return { rgba: paintShade(shader.fine, shader.run(azimuth, altitude)), grid: shader.fine };
	}
	const hours = await sunHours(shader, msg.date, lat, lon, pause(msg.id));
	return hours && { rgba: paintHours(hours), grid: shader.fine };
}

async function handle(
	msg: WorkerRequest
): Promise<{ res: WorkerResponse; transfer: Transferable[] }> {
	const { id } = msg;
	switch (msg.type) {
		case 'dem': {
			const t = await dem.demTile(msg.z, msg.x, msg.y);
			if ('bytes' in t) {
				// A copy: the cache keeps the original for analysis and the next request.
				const bytes = t.bytes.slice(0);
				return { res: { id, ok: true, bytes }, transfer: [bytes] };
			}
			const bmp = await bitmap(encodeTerrarium(t.data), t.size);
			return { res: { id, ok: true, bitmap: bmp }, transfer: [bmp] };
		}
		case 'tile': {
			const { grid, elev } = await dem.around(msg.z, msg.x, msg.y);
			if (elev.sea || cancelled.has(id))
				return { res: { id, ok: true, empty: true }, transfer: [] };
			// A tile clipped to a zone the page hasn't described yet stays clear.
			const polys = msg.zone ? zonePolys.get(msg.zone) : undefined;
			if (msg.zone && !polys) return { res: { id, ok: true, empty: true }, transfer: [] };
			const rgba = paint(
				msg.mode as TerrainMode,
				grid,
				elev.size,
				msg.z,
				msg.y,
				msg.match as MatchParams | undefined
			);
			if (!rgba) return { res: { id, ok: true, empty: true }, transfer: [] };
			if (polys) {
				const k = elev.size / TILE;
				const inside = zoneMask(
					{ z: msg.z, x0: msg.x * TILE, y0: msg.y * TILE, width: elev.size, height: elev.size },
					polys,
					k
				);
				let any = false;
				for (let i = 0; i < inside.length; i++)
					if (!inside[i]) rgba[i * 4 + 3] = 0;
					else if (rgba[i * 4 + 3]) any = true;
				if (!any) return { res: { id, ok: true, empty: true }, transfer: [] };
			}
			const bmp = await bitmap(rgba, elev.size);
			return { res: { id, ok: true, bitmap: bmp }, transfer: [bmp] };
		}
		case 'point':
			return { res: { id, ok: true, point: await point(msg.lat, msg.lon) }, transfer: [] };
		case 'shade':
		case 'sunhours':
		case 'wind':
		case 'concern': {
			const done = await area(msg);
			if (!done || cancelled.has(id)) return { res: { id, ok: true, empty: true }, transfer: [] };
			const bmp = await createImageBitmap(
				new ImageData(done.rgba, done.grid.width, done.grid.height),
				{ premultiplyAlpha: 'none' }
			);
			return { res: { id, ok: true, bitmap: bmp, bounds: rectBounds(done.grid) }, transfer: [bmp] };
		}
		case 'sunpoint': {
			// Fine terrain close by, coarse out to where mountains still matter.
			const [fine, coarse] = await Promise.all([
				mosaic(dem, rectFor(around(msg.lat, msg.lon, 2500), 512, ANALYSIS_ZOOM)),
				mosaic(dem, rectFor(around(msg.lat, msg.lon, SHADE_REACH_M), 640, 10))
			]);
			const h = horizon([fine!, coarse!], msg.lat, msg.lon);
			return { res: { id, ok: true, sun: sunTimes(h, msg.date, msg.lat, msg.lon) }, transfer: [] };
		}
		case 'windpoint': {
			const g = (await mosaic(
				dem,
				rectFor(around(msg.lat, msg.lon, FAR_M + 100), 512, WIND_ZOOM)
			))!;
			const effect = (await windEffect(g, msg.sectors))!;
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
			const p = await profile(id, msg.points, msg.z);
			return {
				res: p ? { id, ok: true, profile: p } : { id, ok: true, empty: true },
				transfer: []
			};
		}
		case 'zone':
			zonePolys.delete(msg.zone);
			zonePolys.set(msg.zone, msg.polys);
			while (zonePolys.size > 6) zonePolys.delete(zonePolys.keys().next().value!);
			return { res: { id, ok: true }, transfer: [] };
		case 'init':
			sunView = null;
			windView = null;
			concernView = null;
			dem = new DemCache({
				decode,
				maxTiles: msg.maxTiles,
				online: () => self.navigator.onLine !== false
			});
			return { res: { id, ok: true }, transfer: [] };
		case 'cancel':
			cancelled.add(msg.target);
			return { res: { id, ok: true }, transfer: [] };
	}
}

self.onmessage = (ev: MessageEvent<WorkerRequest>) => {
	const msg = ev.data;
	handle(msg).then(
		({ res, transfer }) => {
			cancelled.delete(msg.id);
			self.postMessage(res, transfer);
		},
		(e: unknown) => {
			cancelled.delete(msg.id);
			self.postMessage({
				id: msg.id,
				ok: false,
				error: e instanceof Error ? e.message : String(e)
			});
		}
	);
};
