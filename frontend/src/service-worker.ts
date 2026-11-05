// Offline support that stays out of Cloudflare Access's way.
// - App files (hashed JS/CSS, icons) are cached at install and served from cache.
// - /api/* is network-first, falling back to the last good response (up to 2 days
//   old) when offline. A redirect to the Access login passes straight through, so
//   the app can show "Sign in again" instead of quietly serving old data.
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
const API = 'api-v1';
const API_MAX_AGE_MS = 2 * 24 * 3600 * 1000;

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
				Promise.all(keys.filter((k) => k !== SHELL && k !== API).map((k) => caches.delete(k)))
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
	if (url.origin !== self.location.origin) return;
	if (url.pathname.startsWith('/api/')) {
		event.respondWith(apiFirst(request));
	} else if (request.mode === 'navigate') {
		event.respondWith(pageNetworkFirst(request));
	} else if (shellFiles.includes(url.pathname)) {
		event.respondWith(caches.match(request, { cacheName: SHELL }).then((r) => r ?? fetch(request)));
	}
});
