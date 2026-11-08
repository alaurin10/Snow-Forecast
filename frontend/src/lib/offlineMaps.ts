// Offline map areas: the topo map, 3D terrain and ski runs around a location, saved on
// the device so the Map works with no signal. The service worker answers map requests
// from this cache first (see service-worker.ts).
//
// Only sources whose terms allow it are saved: OpenTopoMap (CC-BY-SA, asked not to be
// hammered, so it's capped at zoom 15 and fetched a few at a time through the mini PC's
// cache) and the AWS terrain tiles. Esri's topo and satellite tiles may not be stored
// for offline use outside Esri's own apps, so offline the map uses OpenTopoMap at every
// zoom and satellite isn't available.

export const OFFLINE_CACHE = 'offline-maps-v1';
const KEY = 'offlineMaps';
/** Half-width of a saved area: about 16 x 16 km around the location. */
export const RADIUS_KM = 8;
const TOPO_ZOOMS = [8, 9, 10, 11, 12, 13, 14, 15];
const DEM_ZOOMS = [8, 9, 10, 11, 12, 13, 14];
/** The finest terrain only close in: it's 4x the tiles for each step. */
const DEM_FINE = { zoom: 15, radiusKm: 4 };
const DEM_URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium';
/** Rough sizes from real tiles, for the estimate shown before downloading. */
const AVG_BYTES = { topo: 28_000, dem: 75_000 };
const PARALLEL = 3;

export interface SavedArea {
	id: string;
	name: string;
	lat: number;
	lon: number;
	at: number;
	tiles: number;
	bytes: number;
}

export interface Progress {
	done: number;
	total: number;
	bytes: number;
	failed: number;
}

export function lonToX(lon: number, z: number): number {
	return Math.floor(((lon + 180) / 360) * 2 ** z);
}

export function latToY(lat: number, z: number): number {
	const r = (lat * Math.PI) / 180;
	return Math.floor(((1 - Math.asinh(Math.tan(r)) / Math.PI) / 2) * 2 ** z);
}

/** Tile x/y ranges covering `radiusKm` around a point at zoom `z`. */
export function tileRange(lat: number, lon: number, radiusKm: number, z: number) {
	const dLat = radiusKm / 111.32;
	const dLon = radiusKm / (111.32 * Math.cos((lat * Math.PI) / 180));
	return {
		x0: lonToX(lon - dLon, z),
		x1: lonToX(lon + dLon, z),
		y0: latToY(lat + dLat, z),
		y1: latToY(lat - dLat, z)
	};
}

function urlsAt(
	lat: number,
	lon: number,
	radiusKm: number,
	z: number,
	make: (x: number, y: number) => string
) {
	const { x0, x1, y0, y1 } = tileRange(lat, lon, radiusKm, z);
	const out: string[] = [];
	for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) out.push(make(x, y));
	return out;
}

/** Every URL an area needs, as the map will request them. */
export function areaUrls(
	lat: number,
	lon: number,
	origin: string
): { topo: string[]; dem: string[] } {
	const topo = TOPO_ZOOMS.flatMap((z) =>
		urlsAt(lat, lon, RADIUS_KM, z, (x, y) => `${origin}/api/tiles/otm/${z}/${x}/${y}.png`)
	);
	const dem = [
		...DEM_ZOOMS.flatMap((z) =>
			urlsAt(lat, lon, RADIUS_KM, z, (x, y) => `${DEM_URL}/${z}/${x}/${y}.png`)
		),
		...urlsAt(
			lat,
			lon,
			DEM_FINE.radiusKm,
			DEM_FINE.zoom,
			(x, y) => `${DEM_URL}/${DEM_FINE.zoom}/${x}/${y}.png`
		)
	];
	return { topo, dem };
}

/** The shared files every area needs: ski runs and label fonts. */
export function sharedUrls(origin: string): string[] {
	const fonts = ['Open Sans Semibold', 'Noto Sans Regular'];
	return [
		`${origin}/api/osm/ski.geojson`,
		// Latin and Latin-1 cover the names here.
		...fonts.flatMap((f) =>
			['0-255', '256-511'].map((r) => `${origin}/api/glyphs/${encodeURIComponent(f)}/${r}.pbf`)
		)
	];
}

export function estimateBytes(lat: number, lon: number): number {
	const { topo, dem } = areaUrls(lat, lon, '');
	return topo.length * AVG_BYTES.topo + dem.length * AVG_BYTES.dem;
}

export function available(): boolean {
	return typeof caches !== 'undefined' && 'serviceWorker' in navigator;
}

export function savedAreas(): Record<string, SavedArea> {
	try {
		return JSON.parse(localStorage.getItem(KEY) ?? '{}') as Record<string, SavedArea>;
	} catch {
		return {};
	}
}

function writeAreas(a: Record<string, SavedArea>) {
	try {
		localStorage.setItem(KEY, JSON.stringify(a));
	} catch {
		/* private mode: the tiles are still cached, only the list is lost */
	}
}

/** Download (or top up) an area. Tiles already saved are skipped, so updating is cheap. */
export async function downloadArea(
	area: { id: string; name: string; lat: number; lon: number },
	onProgress: (p: Progress) => void,
	signal?: AbortSignal
): Promise<SavedArea> {
	// Ask the browser not to clear the saved maps when space runs low (iOS honours this
	// for apps on the home screen).
	await navigator.storage?.persist?.().catch(() => false);
	const origin = location.origin;
	const { topo, dem } = areaUrls(area.lat, area.lon, origin);
	const shared = sharedUrls(origin);
	const all = [...shared, ...topo, ...dem];
	const cache = await caches.open(OFFLINE_CACHE);
	const p: Progress = { done: 0, total: all.length, bytes: 0, failed: 0 };
	onProgress({ ...p });
	let next = 0;
	const worker = async () => {
		while (next < all.length) {
			if (signal?.aborted) return;
			const url = all[next++];
			// The ski runs change weekly: always fetch them again. Tiles are kept.
			const refresh = shared.includes(url) && url.endsWith('.geojson');
			try {
				const have = refresh ? undefined : await cache.match(url, { ignoreVary: true });
				if (have) {
					p.bytes += Number(have.headers.get('content-length') ?? 0) || AVG_BYTES.topo;
				} else {
					const res = await fetch(url, {
						mode: url.startsWith(origin) ? 'same-origin' : 'cors',
						signal
					});
					if (!res.ok) throw new Error(String(res.status));
					const body = await res.blob();
					p.bytes += body.size;
					const headers = new Headers(res.headers);
					headers.set('content-length', String(body.size));
					await cache.put(url, new Response(body, { status: 200, headers }));
				}
			} catch {
				if (signal?.aborted) return;
				p.failed++;
			}
			p.done++;
			onProgress({ ...p });
		}
	};
	await Promise.all(Array.from({ length: PARALLEL }, worker));
	if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError');
	const saved: SavedArea = {
		...area,
		at: Date.now(),
		tiles: all.length - p.failed,
		bytes: p.bytes
	};
	const areas = savedAreas();
	areas[area.id] = saved;
	writeAreas(areas);
	return saved;
}

/** Remove an area's tiles, keeping any that another saved area also uses. */
export async function removeArea(id: string): Promise<void> {
	const areas = savedAreas();
	const gone = areas[id];
	delete areas[id];
	writeAreas(areas);
	if (!gone) return;
	const origin = location.origin;
	const keep = new Set<string>();
	for (const a of Object.values(areas)) {
		const { topo, dem } = areaUrls(a.lat, a.lon, origin);
		for (const u of [...topo, ...dem]) keep.add(u);
	}
	const cache = await caches.open(OFFLINE_CACHE);
	const { topo, dem } = areaUrls(gone.lat, gone.lon, origin);
	await Promise.all([...topo, ...dem].filter((u) => !keep.has(u)).map((u) => cache.delete(u)));
	if (!Object.keys(areas).length) await caches.delete(OFFLINE_CACHE);
}

export function formatBytes(n: number): string {
	if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
	if (n >= 1e6) return `${Math.round(n / 1e6)} MB`;
	return `${Math.max(1, Math.round(n / 1e3))} KB`;
}
