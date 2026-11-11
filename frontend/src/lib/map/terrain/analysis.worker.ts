// The terrain worker: fetches and decodes elevation tiles, fills the gaps, paints the
// slope and aspect overlays and answers point questions, all off the main thread.
/// <reference lib="webworker" />
import { ANALYSIS_ZOOM, hornAt, paint, type MatchParams, type TerrainMode } from './analysis';
import { DemCache, encodeTerrarium, locate, metresPerPixel, sample, type Pixels } from './dem';
import type { PointFacts, WorkerRequest, WorkerResponse } from './messages';

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
		case 'init':
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
