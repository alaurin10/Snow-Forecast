// Which way the service worker answers a GET (src/service-worker.ts), kept here as a pure
// function so it can be tested.

/** Owner endpoints: they depend on who is signed in, so never cached. */
export const PRIVATE = ['/api/me', '/api/auth/', '/api/admin/', '/api/push/'];
/** A tap on the map asks for its own spot each time: not worth keeping for offline use. */
export const UNCACHED = ['/api/map/point'];
/** Elevation tiles: Mapterhorn, and AWS (older saved areas, and the fallback). */
export const DEM_HOSTS: Record<string, string> = {
	'tiles.mapterhorn.com': '/',
	's3.amazonaws.com': '/elevation-tiles-prod/terrarium/'
};

export type Route =
	/** Not answered by the service worker: straight to the network. */
	| 'network'
	/** Saved for offline use first, then the network. */
	| 'saved'
	/** The network first, the saved copy when offline. */
	| 'network-then-saved'
	/** The network first, the last good answer when offline. */
	| 'api'
	/** A spot's forecast (a point on the map): like 'api', keeping only the last few. */
	| 'spot'
	| 'page'
	| 'shell';

/**
 * @param saved whether any map area is saved for offline use: false lets map tiles skip
 *   the service worker altogether (most visitors save none); null when not known yet.
 */
export function route(
	url: URL,
	origin: string,
	opts: { navigate: boolean; shell: boolean; saved: boolean | null }
): Route {
	const demPath = DEM_HOSTS[url.host];
	if (demPath && url.pathname.startsWith(demPath))
		return opts.saved === false ? 'network' : 'saved';
	if (url.origin !== origin) return 'network';
	const p = url.pathname;
	if (p.startsWith('/api/tiles/') || p.startsWith('/api/glyphs/'))
		return opts.saved === false ? 'network' : 'saved';
	if (p.startsWith('/api/osm/')) return 'network-then-saved';
	if ([...PRIVATE, ...UNCACHED].some((x) => p.startsWith(x))) return 'network';
	// A spot started early by the map isn't kept: the spot page's own request is.
	if (p === '/api/spot' && url.searchParams.has('early')) return 'network';
	if (p === '/api/spot' || p === '/api/spot/nearby') return 'spot';
	if (p.startsWith('/api/')) return 'api';
	if (opts.navigate) return 'page';
	if (opts.shell) return 'shell';
	return 'network';
}

/** The files the precipitation index names (`/api/precip/<file>`: pictures, and frames
 *  as numbers), for pruning. */
export function precipFiles(index: unknown): Set<string> {
	const out = new Set<string>();
	type Named = { file?: unknown; data?: unknown };
	const ix = index as {
		frames?: Named[];
		totals?: Named[];
		layers?: Record<string, { frames?: Named[] }>;
		steps?: { steps?: Named[] } | null;
	} | null;
	const add = (list: Named[] | undefined) => {
		for (const f of list ?? []) {
			if (typeof f?.file === 'string') out.add(f.file);
			if (typeof f?.data === 'string') out.add(f.data);
		}
	};
	add(ix?.frames);
	add(ix?.totals);
	for (const layer of Object.values(ix?.layers ?? {})) add(layer?.frames);
	add(ix?.steps?.steps);
	return out;
}

/** Spots kept for offline use: the newest few of each kind (the forecast, what's nearby). */
export const SPOTS_KEPT = 10;

/** The saved spot answers to drop: all but the newest `keep` per path. */
export function spotsToDrop(entries: { url: string; at: number }[], keep = SPOTS_KEPT): string[] {
	const byPath = new Map<string, { url: string; at: number }[]>();
	for (const e of entries) {
		const path = new URL(e.url).pathname;
		if (path !== '/api/spot' && path !== '/api/spot/nearby') continue;
		byPath.set(path, [...(byPath.get(path) ?? []), e]);
	}
	const out: string[] = [];
	for (const list of byPath.values())
		out.push(
			...list
				.sort((a, b) => b.at - a.at)
				.slice(keep)
				.map((e) => e.url)
		);
	return out;
}
