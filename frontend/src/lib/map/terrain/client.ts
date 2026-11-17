// The page's side of the terrain worker, and the two MapLibre protocols it serves:
//   dem://{z}/{x}/{y}                 elevation for 3D, hillshade and elevation bands
//   terrain://{mode}/{z}/{x}/{y}?…    the slope, aspect and matching-terrain overlays
import type { AddProtocolAction } from 'maplibre-gl';
import { SECTORS, type MatchParams, type Sector, type TerrainMode } from './analysis';
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

/** How much a worker keeps (see the `init` message). */
export interface WorkerSizes {
	maxTiles: number;
	maxFiles?: number;
	overlayTiles?: number;
	keepViews?: number;
}

export class TerrainClient {
	private worker: Worker;
	private next = 1;
	private waiting = new Map<number, Pending>();
	/** Zones told to the worker, oldest first, as it keeps them (the newest six). */
	private zones = new Map<string, unknown>();

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

	constructor(sizes: WorkerSizes) {
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
		this.ask({ type: 'init', ...sizes }).catch(() => {});
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
		if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
		const { id, done } = this.post(body);
		if (!signal) return done;
		const off = () => {
			const p = this.waiting.get(id);
			if (!p || !this.waiting.delete(id)) return;
			this.worker.postMessage({ type: 'cancel', id: this.next++, target: id });
			p.reject(new DOMException('Aborted', 'AbortError'));
		};
		signal.addEventListener('abort', off, { once: true });
		// Settled: the listener goes, so a signal shared by many asks doesn't gather them.
		void done.then(
			() => signal.removeEventListener('abort', off),
			() => signal.removeEventListener('abort', off)
		);
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

	/**
	 * Tell the worker a zone's polygons, so tiles and concern jobs that name it are drawn
	 * only inside it. Sent again only when `token` (the zone's geometry, say) changes or
	 * the worker has let it go.
	 */
	setZone(zone: string, polys: number[][][][], token: unknown = polys) {
		if (this.zones.has(zone) && this.zones.get(zone) === token) return;
		this.zones.delete(zone);
		this.zones.set(zone, token);
		while (this.zones.size > 6) this.zones.delete(this.zones.keys().next().value!);
		this.ask({ type: 'zone', zone, polys }).catch(() => {});
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

	/** Stop the worker, freeing its tiles; whatever was still asked for fails as aborted. */
	shutdown() {
		this.worker.terminate();
		const waiting = [...this.waiting.values()];
		this.waiting.clear();
		for (const p of waiting) p.reject(new DOMException('Aborted', 'AbortError'));
	}
}

let client: TerrainClient | null = null;
let jobs: TerrainClient | null = null;
let registered = false;
/** Whether the elevation tiles handed to the map came from the AWS tiles (null: none yet). */
let demFallback: boolean | null = null;
const demSwitch = new Set<() => void>();

/**
 * Call `fn` when the elevation's source changes (the worker gave up on Mapterhorn, or a
 * new worker starts on it again): the tiles the map holds are from the other source, and
 * in 3D the two don't meet (dem.ts), so it should load them all again. Returns the undo.
 */
export function onDemSourceChange(fn: () => void): () => void {
	demSwitch.add(fn);
	return () => demSwitch.delete(fn);
}

/** Note the source of an elevation tile just handed to the map. */
export function noteDemSource(fallback: boolean | undefined) {
	if (fallback === undefined) return;
	const was = demFallback;
	demFallback = fallback;
	if (was !== null && was !== fallback) for (const fn of demSwitch) queueMicrotask(fn);
}
/** Maps using the workers now (see `retainTerrain`). */
let users = 0;

const phone = () => typeof matchMedia !== 'undefined' && matchMedia('(max-width: 700px)').matches;

/**
 * The page's tile worker while a map holds it (created on first use), else null: elevation
 * and overlay tiles, taps and profiles.
 */
export function terrainClient(): TerrainClient | null {
	if (!users || !TerrainClient.supported()) return null;
	client ??= phone()
		? new TerrainClient({ maxTiles: 28, overlayTiles: 8 })
		: new TerrainClient({ maxTiles: 48, overlayTiles: 24 });
	return client;
}

/**
 * The page's job worker while a map holds it, else null: the whole-view layers (shade,
 * sun hours, wind, concern), which can take half a second or more, so tiles never queue
 * behind them. Made the first time one is asked for. It keeps fewer elevation tiles and
 * files: it keeps the views' grids instead.
 */
export function jobsClient(): TerrainClient | null {
	if (!users || !TerrainClient.supported()) return null;
	jobs ??= phone()
		? new TerrainClient({ maxTiles: 16, maxFiles: 24, keepViews: 1 })
		: new TerrainClient({ maxTiles: 32, maxFiles: 48, keepViews: 2 });
	return jobs;
}

/**
 * A zone's polygons to the tile worker, and to the job worker if it's running (see
 * `TerrainClient.setZone`). A concern job tells the job worker itself.
 */
export function sendZone(zone: string, polys: number[][][][], token: unknown) {
	terrainClient()?.setZone(zone, polys, token);
	jobs?.setZone(zone, polys, token);
}

/**
 * A map holds the terrain workers while it's open (from before it's made). Call the
 * function returned when it closes: when no map holds them, the workers stop and their
 * decoded tiles (tens of MB) are freed, rather than lasting the rest of the visit on pages
 * without a map, and anything that finishes late gets no worker. The next map starts
 * fresh ones.
 */
export function retainTerrain(): () => void {
	users++;
	let held = true;
	return () => {
		if (!held) return;
		held = false;
		if (--users > 0) return;
		client?.shutdown();
		jobs?.shutdown();
		client = jobs = null;
	};
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
	// The same terrain however the rules are listed, so the overlay's tiles are asked for
	// again only when what they show changes: aspects in compass order, ranges sorted and
	// joined where they touch, rules sorted and without repeats.
	const rules = [
		...new Set(
			m.rules.map((r) => {
				const aspects = SECTORS.filter((s) => r.aspects.includes(s));
				const ranges = r.ranges
					.map(([lo, hi]) => [Math.round(lo), Math.round(hi)] as [number, number])
					.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
				const merged: [number, number][] = [];
				for (const [lo, hi] of ranges) {
					const last = merged[merged.length - 1];
					if (last && lo <= last[1]) last[1] = Math.max(last[1], hi);
					else merged.push([lo, hi]);
				}
				return `${aspects.join('.')}:${merged.map(([lo, hi]) => `${lo}_${hi}`).join(',')}`;
			})
		)
	]
		.sort()
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

/**
 * A tile's elevation at `size` px each way, Terrarium-encoded RGBA (R × 256 + G + B / 256
 * − 32768 metres), from the tile worker's cache (the tiles 3D and the hill shading use);
 * null without the worker.
 */
export async function elevationTile(
	z: number,
	x: number,
	y: number,
	size: number,
	signal?: AbortSignal
): Promise<Uint8Array | null> {
	const c = terrainClient();
	if (!c) return null;
	const r = await c.ask({ type: 'elev', z, x, y, size }, signal);
	return r.bytes ? new Uint8Array(r.bytes) : null;
}

/** Register dem:// and terrain:// with MapLibre (once per page). */
export function registerProtocols(ml: {
	addProtocol: (id: string, fn: AddProtocolAction) => void;
}) {
	if (!TerrainClient.supported()) return false;
	if (registered) return true;
	registered = true;
	// The worker is looked up per request: it's replaced after a shutdown.
	const worker = () => {
		const c = terrainClient();
		if (!c) throw new Error('no terrain worker');
		return c;
	};
	ml.addProtocol('dem', async (params, abort) => {
		const { z, x, y } = parse(params.url.slice('dem://'.length));
		const r = await worker().ask({ type: 'dem', z, x, y }, abort.signal);
		noteDemSource(r.fallback);
		return { data: r.bytes ?? r.bitmap! };
	});
	ml.addProtocol('terrain', async (params, abort) => {
		const rest = params.url.slice('terrain://'.length);
		const [path, query = ''] = rest.split('?');
		const slash = path.indexOf('/');
		const mode = path.slice(0, slash) as TerrainMode;
		const { z, x, y } = parse(path.slice(slash + 1));
		const zone = new URLSearchParams(query).get('zone') ?? undefined;
		const r = await worker().ask(
			{ type: 'tile', mode, z, x, y, match: parseMatch(query), zone },
			abort.signal
		);
		return { data: r.bitmap ?? (await blank()) };
	});
	return true;
}
