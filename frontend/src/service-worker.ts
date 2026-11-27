// Offline support.
// - App files (hashed JS/CSS, icons) are cached at install and served from cache.
// - /api/* is network-first, falling back to the last good response (up to 2 days
//   old) when offline. Owner endpoints (/api/me, /api/auth, /api/admin) are never
//   cached: they depend on who is signed in. Nor are the map's tap-for-numbers answers
//   (/api/map/point): every tap is a new spot. A spot's full forecast (/api/spot, a point
//   tapped on the map) is network-first too, keeping only the last 10.
//   The copy is written in the background, so the page never waits for it; entries past
//   2 days, and precipitation pictures the newest index no longer names, are pruned.
// - Map tiles, terrain, label fonts and ski runs saved for offline use (Map → offline
//   maps; see lib/offlineMaps.ts) are answered from that cache first. Other map tiles
//   go straight to the network: they are many and big, and the server caches them. With
//   no area saved (most visitors), tiles don't pass through the service worker at all.
// - Page loads go to the network first (so a new version shows up) and fall back to
//   the cached app shell only when the network is unreachable.
/// <reference lib="webworker" />
import { self } from '$app/service-worker';
import { assets, immutable } from '$app/manifest';
import { precipFiles, route, spotsToDrop } from './lib/swRoute';

const shellFiles = [
	'/',
	'/index.html',
	...immutable.map((f) => `/${f.path}`),
	...assets.map((f) => `/${f.path}`)
];
const SHELL = `shell-${hash(shellFiles.join('|'))}`;
const API = 'api-v2'; // v1 also held map tiles; dropped on activate
const API_MAX_AGE_MS = 2 * 24 * 3600 * 1000;
// Keep in step with OFFLINE_CACHE in lib/offlineMaps.ts.
const OFFLINE = 'offline-maps-v1';
/** Prune the API cache by age at most this often. */
const PRUNE_EVERY_MS = 3600 * 1000;

/** Whether any map area is saved for offline use; null until the first check. */
let saved: boolean | null = null;
const checkSaved = () =>
	caches.has(OFFLINE).then(
		(has) => (saved = has),
		() => (saved = null)
	);
void checkSaved();
let prunedAt = 0;

function hash(s: string): string {
	let h = 0;
	for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
	return (h >>> 0).toString(36);
}

self.addEventListener('install', (event: ExtendableEvent) => {
	event.waitUntil(
		// A new version waits until the page says to take over (its "Reload" button), so
		// nobody's open page swaps code underneath them.
		caches.open(SHELL).then((c) => c.addAll(shellFiles))
	);
});

self.addEventListener('message', (event: ExtendableMessageEvent) => {
	const type = (event.data as { type?: string } | null)?.type;
	if (type === 'skip-waiting') void self.skipWaiting();
	// An area was saved or removed (lib/offlineMaps.ts).
	if (type === 'offline-maps') event.waitUntil(checkSaved());
});

self.addEventListener('activate', (event: ExtendableEvent) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) =>
				Promise.all(
					keys.filter((k) => k !== SHELL && k !== API && k !== OFFLINE).map((k) => caches.delete(k))
				)
			)
			.then(() => self.clients.claim())
			.then(() => pruneOld())
	);
});

/** Drop API answers older than the 2 days they may be used for offline. */
async function pruneOld() {
	prunedAt = Date.now();
	const cache = await caches.open(API);
	for (const req of await cache.keys()) {
		const res = await cache.match(req);
		const at = Number(res?.headers.get('x-sw-cached-at') ?? 0);
		if (Date.now() - at > API_MAX_AGE_MS) await cache.delete(req);
	}
}

/** Drop precipitation pictures the newest index no longer names: frame names change
 *  with every rebuild, so they would otherwise pile up for two days. */
async function prunePrecip(index: Response) {
	const keep = precipFiles(await index.json());
	if (!keep.size) return;
	const cache = await caches.open(API);
	for (const req of await cache.keys()) {
		const path = new URL(req.url).pathname;
		// The wide radar's frames are listed in an index of their own (they go after two
		// days, like everything else here).
		if (path.startsWith('/api/precip/wide')) continue;
		if (path.startsWith('/api/precip/') && !keep.has(path.slice('/api/precip/'.length)))
			await cache.delete(req);
	}
}

/** Keep only the newest few spots (each is a forecast for one tapped point). */
async function pruneSpots() {
	const cache = await caches.open(API);
	const entries = [];
	for (const req of await cache.keys()) {
		if (!new URL(req.url).pathname.startsWith('/api/spot')) continue;
		const res = await cache.match(req);
		entries.push({ url: req.url, at: Number(res?.headers.get('x-sw-cached-at') ?? 0) });
	}
	for (const url of spotsToDrop(entries)) await cache.delete(url);
}

/** Keep a copy of a good answer for offline use, without holding up the page. */
async function keep(request: Request, copy: Response) {
	const headers = new Headers(copy.headers);
	headers.set('x-sw-cached-at', String(Date.now()));
	const body = await copy.blob();
	const cache = await caches.open(API);
	await cache.put(request, new Response(body, { status: copy.status, headers }));
	const path = new URL(request.url).pathname;
	if (path === '/api/precip') await prunePrecip(new Response(body));
	if (path.startsWith('/api/spot')) await pruneSpots();
	if (Date.now() - prunedAt > PRUNE_EVERY_MS) await pruneOld();
}

async function apiFirst(event: FetchEvent): Promise<Response> {
	const { request } = event;
	try {
		const res = await fetch(request);
		if (res.ok && res.type === 'basic') event.waitUntil(keep(request, res.clone()).catch(() => {}));
		return res;
	} catch {
		const cached = await caches.match(request, { cacheName: API });
		const at = Number(cached?.headers.get('x-sw-cached-at') ?? 0);
		if (cached && Date.now() - at < API_MAX_AGE_MS) return cached;
		return new Response(JSON.stringify({ detail: 'offline' }), {
			status: 503,
			headers: { 'content-type': 'application/json' }
		});
	}
}

/** Saved map files first (they don't change), then the network. */
async function savedFirst(request: Request): Promise<Response> {
	const saved = await caches.match(request.url, { cacheName: OFFLINE, ignoreVary: true });
	if (saved) return saved;
	try {
		return await fetch(request);
	} catch {
		return new Response(null, { status: 504 });
	}
}

/** Ski runs change weekly: the network first, the saved copy when offline. */
async function networkThenSaved(request: Request): Promise<Response> {
	try {
		return await fetch(request);
	} catch {
		const saved = await caches.match(request.url, { cacheName: OFFLINE, ignoreVary: true });
		return saved ?? new Response(null, { status: 504 });
	}
}

async function pageNetworkFirst(request: Request): Promise<Response> {
	try {
		return await fetch(request);
	} catch {
		return (await caches.match('/index.html', { cacheName: SHELL })) ?? Response.error();
	}
}

self.addEventListener('fetch', (event: FetchEvent) => {
	const { request } = event;
	if (request.method !== 'GET') return;
	const url = new URL(request.url);
	const how = route(url, self.location.origin, {
		navigate: request.mode === 'navigate',
		shell: shellFiles.includes(url.pathname),
		saved
	});
	if (how === 'saved') event.respondWith(savedFirst(request));
	else if (how === 'network-then-saved') event.respondWith(networkThenSaved(request));
	else if (how === 'api' || how === 'spot') event.respondWith(apiFirst(event));
	else if (how === 'page') event.respondWith(pageNetworkFirst(request));
	else if (how === 'shell')
		event.respondWith(caches.match(request, { cacheName: SHELL }).then((r) => r ?? fetch(request)));
	// 'network': not answered here, so the browser goes straight to the network.
});

// Push alerts (W3C Web Push). The server sends {title, body, url, tag}. Each run's
// digest has the same tag, so it replaces the last one; `renotify` still alerts.
interface PushPayload {
	title?: string;
	body?: string;
	url?: string;
	tag?: string;
}

self.addEventListener('push', (event: PushEvent) => {
	let data: PushPayload;
	try {
		data = (event.data?.json() as PushPayload) ?? {};
	} catch {
		data = { title: event.data?.text() };
	}
	// `renotify` is in the spec but not in TypeScript's NotificationOptions.
	const options: NotificationOptions & { renotify?: boolean } = {
		body: data.body ?? '',
		tag: data.tag,
		renotify: !!data.tag,
		icon: '/icons/icon-192.png',
		badge: '/icons/icon-192.png',
		data: { url: data.url ?? '/' }
	};
	event.waitUntil(self.registration.showNotification(data.title ?? 'Snow Watch', options));
});

self.addEventListener('notificationclick', (event: NotificationEvent) => {
	event.notification.close();
	const target = new URL(
		(event.notification.data as { url?: string } | null)?.url ?? '/',
		self.location.origin
	);
	if (target.origin !== self.location.origin) return; // only open our own pages
	event.waitUntil(
		self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
			const open = wins.find((w) => new URL(w.url).origin === target.origin);
			if (open) {
				return open.focus().then((w) => w.navigate(target.href));
			}
			return self.clients.openWindow(target.href);
		})
	);
});
