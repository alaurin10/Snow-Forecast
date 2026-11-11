// The page's side of the terrain worker, and the two MapLibre protocols it serves:
//   dem://{z}/{x}/{y}                 elevation for 3D, hillshade and elevation bands
//   terrain://{mode}/{z}/{x}/{y}?…    the slope, aspect and matching-terrain overlays
import type { AddProtocolAction } from 'maplibre-gl';
import type { MatchParams, Sector, TerrainMode } from './analysis';
import type { PointFacts, WorkerRequest, WorkerResponse } from './messages';

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

	ask(body: Body, signal?: AbortSignal): Promise<WorkerResponse & { ok: true }> {
		const id = this.next++;
		return new Promise((resolve, reject) => {
			this.waiting.set(id, { resolve, reject });
			this.worker.postMessage({ ...body, id } as WorkerRequest);
			signal?.addEventListener('abort', () => {
				if (!this.waiting.delete(id)) return;
				this.worker.postMessage({ type: 'cancel', id: this.next++, target: id });
				reject(new DOMException('Aborted', 'AbortError'));
			});
		});
	}

	async point(lat: number, lon: number): Promise<PointFacts> {
		const r = await this.ask({ type: 'point', lat, lon });
		return r.point!;
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
