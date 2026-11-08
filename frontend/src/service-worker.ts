// Offline support that stays out of Cloudflare Access's way.
// - App files (hashed JS/CSS, icons) are cached at install and served from cache.
// - /api/* is network-first, falling back to the last good response (up to 2 days
//   old) when offline. A redirect to the Access login passes straight through, so
//   the app can show "Sign in again" instead of quietly serving old data.
// - Map tiles, terrain, label fonts and ski runs saved for offline use (Map → offline
//   maps; see lib/offlineMaps.ts) are answered from that cache first. Other map tiles
//   go straight to the network: they are many and big, and the mini PC caches them.
// - Page loads always go to the network (so Access can ask for a login) and
//   fall back to the cached app shell only when the network is unreachable.
/// <reference lib="webworker" />
import { self } from '$app/service-worker';
import { assets, immutable } from '$app/manifest';

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
const DEM_HOST = 's3.amazonaws.com';
const DEM_PATH = '/elevation-tiles-prod/terrarium/';

function hash(s: string): string {
	let h = 0;
	for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
	return (h >>> 0).toString(36);
}

self.addEventListener('install', (event: ExtendableEvent) => {
	event.waitUntil(
		caches
			.open(SHELL)
			.then((c) => c.addAll(shellFiles))
			.then(() => self.skipWaiting())
	);
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
	);
});

async function apiFirst(request: Request): Promise<Response> {
	try {
		const res = await fetch(request);
		if (res.ok && res.type === 'basic') {
			const copy = res.clone();
			const headers = new Headers(copy.headers);
			headers.set('x-sw-cached-at', String(Date.now()));
			const body = await copy.blob();
			const cache = await caches.open(API);
			await cache.put(request, new Response(body, { status: copy.status, headers }));
		}
		return res; // includes Access login redirects, untouched
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
	if (url.host === DEM_HOST && url.pathname.startsWith(DEM_PATH)) {
		event.respondWith(savedFirst(request));
		return;
	}
	if (url.origin !== self.location.origin) return;
	if (url.pathname.startsWith('/api/tiles/') || url.pathname.startsWith('/api/glyphs/')) {
		event.respondWith(savedFirst(request));
	} else if (url.pathname.startsWith('/api/osm/')) {
		event.respondWith(networkThenSaved(request));
	} else if (url.pathname.startsWith('/api/')) {
		event.respondWith(apiFirst(request));
	} else if (request.mode === 'navigate') {
		event.respondWith(pageNetworkFirst(request));
	} else if (shellFiles.includes(url.pathname)) {
		event.respondWith(caches.match(request, { cacheName: SHELL }).then((r) => r ?? fetch(request)));
	}
});

// Push alerts (W3C Web Push). The server sends {title, body, url, tag}.
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
	event.waitUntil(
		self.registration.showNotification(data.title ?? 'Snow Watch', {
			body: data.body ?? '',
			tag: data.tag,
			icon: '/icons/icon-192.png',
			badge: '/icons/icon-192.png',
			data: { url: data.url ?? '/' }
		})
	);
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
