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
	if (p.startsWith('/api/')) return 'api';
	if (opts.navigate) return 'page';
	if (opts.shell) return 'shell';
	return 'network';
}

/** The pictures the precipitation index names (`/api/precip/<file>`), for pruning. */
export function precipFiles(index: unknown): Set<string> {
	const out = new Set<string>();
	const ix = index as {
		frames?: { file?: unknown }[];
		totals?: { file?: unknown }[];
		layers?: Record<string, { frames?: { file?: unknown }[] }>;
	} | null;
	const add = (list: { file?: unknown }[] | undefined) => {
		for (const f of list ?? []) if (typeof f?.file === 'string') out.add(f.file);
	};
	add(ix?.frames);
	add(ix?.totals);
	for (const layer of Object.values(ix?.layers ?? {})) add(layer?.frames);
	return out;
}
