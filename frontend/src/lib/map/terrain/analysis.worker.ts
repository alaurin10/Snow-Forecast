// The terrain worker: fetches and decodes elevation tiles, fills the gaps, paints the
// slope and aspect overlays and answers point questions, all off the main thread.
/// <reference lib="webworker" />
import { ANALYSIS_ZOOM, hornAt, paint, type MatchParams, type TerrainMode } from './analysis';
import { DemCache, encodeTerrarium, locate, metresPerPixel, sample, type Pixels } from './dem';
import {
	around,
	bilinear,
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

async function area(
	msg: Area
): Promise<{ rgba: Uint8ClampedArray<ArrayBuffer>; grid: Grid } | null> {
	if (msg.type === 'wind') {
		const rect = rectFor(pad(msg.bounds, FAR_M), msg.maxPx, WIND_ZOOM);
		const key = rectKey(rect);
		if (windView?.key !== key) {
			const grid = await mosaic(dem, rect, () => !cancelled.has(msg.id));
			if (!grid) return null;
			windView = { key, grid, sectors: '', effect: null };
		}
		const view = windView;
		const sectors = msg.sectors.join();
		if (!view.effect || view.sectors !== sectors) {
			const effect = await windEffect(view.grid, msg.sectors, pause(msg.id));
			if (!effect) return null;
			view.effect = effect;
			view.sectors = sectors;
		}
		return { rgba: paintWind(view.effect, msg.scale), grid: view.grid };
	}
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
			const rgba = paint(
				msg.mode as TerrainMode,
				grid,
				elev.size,
				msg.z,
				msg.y,
				msg.match as MatchParams | undefined
			);
			if (!rgba) return { res: { id, ok: true, empty: true }, transfer: [] };
			const bmp = await bitmap(rgba, elev.size);
			return { res: { id, ok: true, bitmap: bmp }, transfer: [bmp] };
		}
		case 'point':
			return { res: { id, ok: true, point: await point(msg.lat, msg.lon) }, transfer: [] };
		case 'shade':
		case 'sunhours':
		case 'wind': {
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
		case 'init':
			sunView = null;
			windView = null;
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
