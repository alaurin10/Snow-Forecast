// The page's side of the terrain worker, and the two MapLibre protocols it serves:
//   dem://{z}/{x}/{y}                 elevation for 3D, hillshade and elevation bands
//   terrain://{mode}/{z}/{x}/{y}?…    the slope, aspect and matching-terrain overlays
import type { AddProtocolAction } from 'maplibre-gl';
import type { MatchParams, Sector, TerrainMode } from './analysis';
import type { Bounds } from './grid';
import type { PointFacts, WorkerRequest, WorkerResponse } from './messages';
import type { SunFacts } from './shade';
import type { Ymd } from './sun';

/** A whole-view picture: shade at a time, sun hours in a day, or the wind effect. */
export type AreaJob =
	| { type: 'shade'; time: number }
	| { type: 'sunhours'; date: Ymd }
	| { type: 'wind'; sectors: number[]; scale: number };

type Pending = { resolve: (r: WorkerResponse & { ok: true }) => void; reject: (e: Error) => void };
type Body = WorkerRequest extends infer R
	? R extends { id: number }
		? Omit<R, 'id'>
		: never
	: never;

export class TerrainClient {
	private worker: Worker;
	private next = 1;
	private waiting = new Map<number, Pending>();

	/** Workers, OffscreenCanvas and ImageBitmap: every browser from 2023 on. */
	static supported(): boolean {
		try {
			return (
				typeof Worker !== 'undefined' &&
				typeof OffscreenCanvas !== 'undefined' &&
				typeof createImageBitmap === 'function' &&
				!!new OffscreenCanvas(1, 1).getContext('2d')
			);
		} catch {
			return false;
		}
	}

	constructor(maxTiles: number) {
		this.worker = new Worker(new URL('./analysis.worker.ts', import.meta.url), { type: 'module' });
		this.worker.onmessage = (ev: MessageEvent<WorkerResponse>) => {
			const r = ev.data;
			const p = this.waiting.get(r.id);
			if (!p) {
				// Its asker gave up: free what came back.
				if (r.ok && r.bitmap) r.bitmap.close();
				return;
			}
			this.waiting.delete(r.id);
			if (r.ok) p.resolve(r);
			else p.reject(new Error(r.error));
		};
		void this.ask({ type: 'init', maxTiles });
	}

	private post(body: Body): { id: number; done: Promise<WorkerResponse & { ok: true }> } {
		const id = this.next++;
		const done = new Promise<WorkerResponse & { ok: true }>((resolve, reject) => {
			this.waiting.set(id, { resolve, reject });
			this.worker.postMessage({ ...body, id } as WorkerRequest);
		});
		return { id, done };
	}

	ask(body: Body, signal?: AbortSignal): Promise<WorkerResponse & { ok: true }> {
		const { id, done } = this.post(body);
		signal?.addEventListener('abort', () => {
			const p = this.waiting.get(id);
			if (!p || !this.waiting.delete(id)) return;
			this.worker.postMessage({ type: 'cancel', id: this.next++, target: id });
			p.reject(new DOMException('Aborted', 'AbortError'));
		});
		return done;
	}

	async point(lat: number, lon: number): Promise<PointFacts> {
		const r = await this.ask({ type: 'point', lat, lon });
		return r.point!;
	}

	/**
	 * The picture for a view and the box it covers. `cancel` tells the worker to stop;
	 * `done` then settles with null as soon as it has, so the next job can follow it.
	 */
	area(
		job: AreaJob,
		bounds: Bounds,
		maxPx: number
	): { done: Promise<{ bitmap: ImageBitmap; bounds: Bounds } | null>; cancel: () => void } {
		const { id, done } = this.post({ ...job, bounds, maxPx });
		return {
			done: done.then((r) =>
				r.bitmap && r.bounds ? { bitmap: r.bitmap, bounds: r.bounds } : null
			),
			cancel: () => this.worker.postMessage({ type: 'cancel', id: this.next++, target: id })
		};
	}

	/** First and last direct sun at a spot on a date. */
	async sunPoint(lat: number, lon: number, date: Ymd): Promise<SunFacts> {
		return (await this.ask({ type: 'sunpoint', lat, lon, date })).sun!;
	}

	/** Wind effect at a spot, −1 (stripped) to 1 (loaded), before scaling by the transport. */
	async windPoint(lat: number, lon: number, sectors: number[]): Promise<number> {
		return (await this.ask({ type: 'windpoint', lat, lon, sectors })).wind!;
	}
}

let client: TerrainClient | null = null;
let registered = false;

/** The one terrain worker for the page (created on first use). */
export function terrainClient(): TerrainClient | null {
	if (!TerrainClient.supported()) return null;
	if (!client) {
		const phone = typeof matchMedia !== 'undefined' && matchMedia('(max-width: 700px)').matches;
		client = new TerrainClient(phone ? 28 : 48);
	}
	return client;
}

const TILE_RE = /^(\d+)\/(\d+)\/(\d+)/;

function parse(path: string) {
	const m = TILE_RE.exec(path);
	if (!m) throw new Error(`bad tile ${path}`);
	return { z: +m[1], x: +m[2], y: +m[3] };
}

async function blank(): Promise<ImageBitmap> {
	return createImageBitmap(new ImageData(1, 1));
}

/** Overlay parameters in a terrain:// URL's query. */
export function matchQuery(m: MatchParams): string {
	const q = new URLSearchParams({ s: String(m.slopeMin), a: m.aspects.join(',') });
	if (m.minM != null) q.set('lo', String(Math.round(m.minM)));
	if (m.maxM != null) q.set('hi', String(Math.round(m.maxM)));
	return q.toString();
}

export function parseMatch(query: string): MatchParams | undefined {
	if (!query) return undefined;
	const q = new URLSearchParams(query);
	const lo = q.get('lo');
	const hi = q.get('hi');
	return {
		slopeMin: Number(q.get('s') ?? 30),
		aspects: (q.get('a') ?? '').split(',').filter(Boolean) as Sector[],
		minM: lo == null ? undefined : Number(lo),
		maxM: hi == null ? undefined : Number(hi)
	};
}

/** Register dem:// and terrain:// with MapLibre (once per page). */
export function registerProtocols(ml: {
	addProtocol: (id: string, fn: AddProtocolAction) => void;
}) {
	const c = terrainClient();
	if (!c || registered) return !!c;
	registered = true;
	ml.addProtocol('dem', async (params, abort) => {
		const { z, x, y } = parse(params.url.slice('dem://'.length));
		const r = await c.ask({ type: 'dem', z, x, y }, abort.signal);
		return { data: r.bytes ?? r.bitmap! };
	});
	ml.addProtocol('terrain', async (params, abort) => {
		const rest = params.url.slice('terrain://'.length);
		const [path, query = ''] = rest.split('?');
		const slash = path.indexOf('/');
		const mode = path.slice(0, slash) as TerrainMode;
		const { z, x, y } = parse(path.slice(slash + 1));
		const r = await c.ask({ type: 'tile', mode, z, x, y, match: parseMatch(query) }, abort.signal);
		return { data: r.bitmap ?? (await blank()) };
	});
	return true;
}
