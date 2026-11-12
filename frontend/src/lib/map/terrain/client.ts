// The page's side of the terrain worker, and the two MapLibre protocols it serves:
//   dem://{z}/{x}/{y}                 elevation for 3D, hillshade and elevation bands
//   terrain://{mode}/{z}/{x}/{y}?…    the slope, aspect and matching-terrain overlays
import type { AddProtocolAction } from 'maplibre-gl';
import type { MatchParams, Sector, TerrainMode } from './analysis';
import type { Bounds } from './grid';
import type { ConcernJob, PointFacts, WorkerRequest, WorkerResponse } from './messages';
import type { SunFacts } from './shade';
import type { Ymd } from './sun';

/** A whole-view picture: shade at a time, sun hours in a day, the wind effect, or the concern index. */
export type AreaJob =
	| { type: 'shade'; time: number }
	| { type: 'sunhours'; date: Ymd }
	| { type: 'wind'; sectors: number[]; scale: number }
	| ({ type: 'concern' } & ConcernJob);

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

	/** Tell the worker a zone's polygons, so tiles that name it are drawn only inside it. */
	setZone(zone: string, polys: number[][][][]) {
		void this.ask({ type: 'zone', zone, polys });
	}

	/** First and last direct sun at a spot on a date. */
	async sunPoint(lat: number, lon: number, date: Ymd): Promise<SunFacts> {
		return (await this.ask({ type: 'sunpoint', lat, lon, date })).sun!;
	}

	/** Elevation and ground slope at each [lon, lat] of a line, from tiles at zoom `z`. */
	async profile(
		points: [number, number][],
		z: number,
		signal?: AbortSignal
	): Promise<{ elev: number[]; slope: number[] }> {
		const r = await this.ask({ type: 'profile', points, z }, signal);
		if (!r.profile) throw new Error('cancelled');
		return r.profile;
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

/**
 * Overlay parameters in a terrain:// URL's query: `s=30&r=N.NE:0-1500,1900-9000;S:`,
 * one rule per `;`, its aspects before the colon and its elevation ranges after.
 */
export function matchQuery(m: MatchParams, zone?: string): string {
	const rules = m.rules
		.map(
			(r) =>
				`${r.aspects.join('.')}:${r.ranges.map(([lo, hi]) => `${Math.round(lo)}_${Math.round(hi)}`).join(',')}`
		)
		.join(';');
	const q = new URLSearchParams({ s: String(m.slopeMin), r: rules });
	if (zone) q.set('zone', zone);
	return q.toString();
}

export function parseMatch(query: string): MatchParams | undefined {
	if (!query) return undefined;
	const q = new URLSearchParams(query);
	const rules = (q.get('r') ?? '')
		.split(';')
		.filter(Boolean)
		.map((part) => {
			const [a = '', r = ''] = part.split(':');
			return {
				aspects: a.split('.').filter(Boolean) as Sector[],
				ranges: r
					.split(',')
					.filter(Boolean)
					.map((x) => x.split('_').map(Number) as [number, number])
			};
		});
	return { slopeMin: Number(q.get('s') ?? 30), rules };
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
		const zone = new URLSearchParams(query).get('zone') ?? undefined;
		const r = await c.ask(
			{ type: 'tile', mode, z, x, y, match: parseMatch(query), zone },
			abort.signal
		);
		return { data: r.bitmap ?? (await blank()) };
	});
	return true;
}
