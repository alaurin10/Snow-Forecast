// Leaflet layers for the precipitation timeline, and the background loader.
//
//   wmsLayer:   a GeoMet WMS layer (HRDPS forecast) with our own tile URLs, so the
//               background loader can ask for exactly the same images.
//
// Every image is fetched and decoded by hand (createImageBitmap) and freed once drawn,
// rather than loaded as <img>: browsers keep decoded <img> pixels cached, and on a
// phone that build-up during playback crashes the page.
//   radarLayer: observed radar (RainViewer), repainted in our colours on canvases.
//   southLayer: the forecast for the parts of the US the Canadian model doesn't reach.
//               Each 256 px canvas gets HRRR simulated radar for the hour (IEM tiles,
//               repainted), or NWS 6-hour totals in tan where HRRR has nothing; then
//               the HRDPS domain is cut out so only one model shows in each place.
//   prefetch:   downloads a frame's images into the browser's HTTP cache without
//               decoding or drawing them, so preloading the timeline costs network,
//               not memory. (Phones kill pages that hold many decoded frames.)
//
// Tile canvases are freed (width 0) the moment a tile leaves the map.
import type * as Leaflet from 'leaflet';
import {
	domainSld,
	DOMAIN_LAYER,
	GEOMET,
	hrrrRecolor,
	hrrrTileUrl,
	radarRecolor,
	untypedColor,
	type WpcCollection
} from './radar';

const SIZE = 256;

/** Tiles being loaded for the map right now; background loading waits for them. */
let foreground = 0;
const idle: (() => void)[] = [];
const WORLD = 20037508.342789244;

/**
 * Fetch and decode an image ourselves, so we can free its pixels the moment it's drawn
 * (`close()`). Images loaded as <img> stay decoded in the browser's cache, and on a
 * phone that pile-up crashes the page. One retry for a busy server.
 */
async function bitmap(url: string): Promise<ImageBitmap> {
	foreground++;
	try {
		return await fetchBitmap(url);
	} finally {
		if (--foreground === 0) for (const r of idle.splice(0)) r();
	}
}

async function fetchBitmap(url: string): Promise<ImageBitmap> {
	for (let attempt = 0; ; attempt++) {
		const r = await fetch(url, { mode: 'cors', credentials: 'same-origin' });
		if (r.ok) return createImageBitmap(await r.blob());
		if (attempt >= 1 || (r.status !== 429 && r.status < 500)) throw new Error(`${r.status} ${url}`);
		await new Promise((res) => setTimeout(res, 1200 + Math.random() * 1200));
	}
}

// ---- Tile canvases ----------------------------------------------------------------------
// Each tile is a canvas. When Leaflet lets a tile go, its pixels are freed at once
// (width 0) rather than left for the garbage collector: iOS counts canvas memory until
// collection and kills the page past its limit. A tile's draw checks `alive()` after
// every wait, so a tile that has gone isn't drawn into.

interface Tile {
	canvas: HTMLCanvasElement;
	ctx: CanvasRenderingContext2D;
	alive: () => boolean;
}
const gone = new WeakSet<HTMLCanvasElement>();

/** `read`: the tile's pixels get repainted, so keep them where the CPU can reach them. */
function takeTile(size: number, read = true): Tile {
	const canvas = document.createElement('canvas');
	canvas.width = canvas.height = size;
	const ctx = canvas.getContext('2d', { willReadFrequently: read })!;
	return { canvas, ctx, alive: () => !gone.has(canvas) };
}

function giveBack(canvas: HTMLCanvasElement) {
	gone.add(canvas);
	canvas.width = canvas.height = 0;
}

/** Draw a fetched image into a tile and free it. */
async function drawUrl(t: Tile, url: string, size = SIZE) {
	const bmp = await bitmap(url);
	if (t.alive()) t.ctx.drawImage(bmp, 0, 0, size, size);
	bmp.close();
}

/** A tile's bounds in Web Mercator metres: minx, miny, maxx, maxy. */
export function tileBbox(x: number, y: number, z: number, size: number): number[] {
	const span = (2 * WORLD * size) / (256 * 2 ** z);
	return [-WORLD + x * span, WORLD - (y + 1) * span, -WORLD + (x + 1) * span, WORLD - y * span];
}

/** A GeoMet GetMap URL for one tile. Same inputs, same URL, so the cache can match it. */
export function wmsTileUrl(
	layer: string,
	sld: string,
	time: string | null,
	x: number,
	y: number,
	z: number,
	size: number
): string {
	const q = new URLSearchParams({
		service: 'WMS',
		version: '1.3.0',
		request: 'GetMap',
		crs: 'EPSG:3857',
		bbox: tileBbox(x, y, z, size).join(','),
		width: String(size),
		height: String(size),
		format: 'image/png',
		transparent: 'true',
		layers: layer,
		styles: '',
		sld_body: sld
	});
	if (time) q.set('time', time);
	return `${GEOMET}?${q}`;
}

type Ctor<O> = new (o: O) => Leaflet.GridLayer;

function releaseCanvases(layer: Leaflet.GridLayer) {
	layer.on('tileunload', (e) => {
		const c = (e as Leaflet.TileEvent).tile as unknown;
		if (c instanceof HTMLCanvasElement) giveBack(c);
	});
	return layer;
}

export interface WmsSpec {
	layer: string;
	sld: string;
	/** ISO time, or null for the layer's default. */
	time: string | null;
	tileSize: number;
}

export function wmsLayer(
	L: typeof Leaflet,
	spec: WmsSpec,
	options: Leaflet.GridLayerOptions
): Leaflet.GridLayer {
	const Layer = L.GridLayer.extend({
		createTile(coords: Leaflet.Coords, done: Leaflet.DoneCallback) {
			const t = takeTile(spec.tileSize, false);
			const url = wmsTileUrl(
				spec.layer,
				spec.sld,
				spec.time,
				coords.x,
				coords.y,
				coords.z,
				spec.tileSize
			);
			drawUrl(t, url, spec.tileSize).then(
				() => done(undefined, t.canvas),
				(e) => done(e, t.canvas)
			);
			return t.canvas;
		}
	}) as unknown as Ctor<Leaflet.GridLayerOptions>;
	return releaseCanvases(new Layer({ ...options, tileSize: spec.tileSize }));
}

// ---- Mask of the HRDPS domain, per 256 px tile ----------------------------------

/** 1 where the Canadian model covers the pixel. Kept for the most recent tiles only. */
interface Mask {
	cover: Uint8Array | null;
	full: boolean;
}
const MASKS_KEPT = 300;
const masks = new Map<string, Promise<Mask>>();
let scratch: HTMLCanvasElement | undefined;

function maskFor(coords: Leaflet.Coords): Promise<Mask> {
	const key = `${coords.z}/${coords.x}/${coords.y}`;
	const have = masks.get(key);
	if (have) {
		// Most recently used last.
		masks.delete(key);
		masks.set(key, have);
		return have;
	}
	const url = wmsTileUrl(DOMAIN_LAYER, domainSld(), null, coords.x, coords.y, coords.z, SIZE);
	const p = bitmap(url).then((img) => {
		scratch ??= document.createElement('canvas');
		scratch.width = scratch.height = SIZE;
		const ctx = scratch.getContext('2d', { willReadFrequently: true })!;
		ctx.clearRect(0, 0, SIZE, SIZE);
		ctx.drawImage(img, 0, 0);
		img.close();
		const a = ctx.getImageData(0, 0, SIZE, SIZE).data;
		const cover = new Uint8Array(SIZE * SIZE);
		let solid = 0;
		for (let i = 0; i < cover.length; i++) {
			if (a[i * 4 + 3] > 0) {
				cover[i] = 1;
				solid++;
			}
		}
		return { cover: solid ? cover : null, full: solid === cover.length };
	});
	// A failed mask is asked for again next time.
	p.catch(() => masks.delete(key));
	masks.set(key, p);
	while (masks.size > MASKS_KEPT) masks.delete(masks.keys().next().value!);
	return p;
}

// ---- Repainting ---------------------------------------------------------------------

type Recolor = (r: number, g: number, b: number) => string | null;
const palettes = new Map<Recolor, Map<number, [number, number, number] | null>>();

/** Repaint a tile from a source palette into ours, and cut out `cover` if given. */
function repaint(t: Tile, fn: Recolor | null, cover: Uint8Array | null) {
	if (!t.alive()) return;
	const ctx = t.ctx;
	let cache = fn ? palettes.get(fn) : undefined;
	if (fn && !cache) palettes.set(fn, (cache = new Map()));
	const im = ctx.getImageData(0, 0, SIZE, SIZE);
	const d = im.data;
	for (let i = 0, p = 0; i < d.length; i += 4, p++) {
		if (d[i + 3] === 0) continue;
		if (cover?.[p]) {
			d[i + 3] = 0;
			continue;
		}
		if (!fn || !cache) continue;
		if (d[i + 3] < 24) {
			d[i + 3] = 0;
			continue;
		}
		const key = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2];
		let c = cache.get(key);
		if (c === undefined) {
			const hex = fn(d[i], d[i + 1], d[i + 2]);
			c = hex
				? [
						parseInt(hex.slice(1, 3), 16),
						parseInt(hex.slice(3, 5), 16),
						parseInt(hex.slice(5, 7), 16)
					]
				: null;
			cache.set(key, c);
		}
		if (c) {
			d[i] = c[0];
			d[i + 1] = c[1];
			d[i + 2] = c[2];
			d[i + 3] = 255;
		} else d[i + 3] = 0;
	}
	ctx.putImageData(im, 0, 0);
}

/** Observed radar (RainViewer) tiles, repainted in our colours. */
export function radarLayer(
	L: typeof Leaflet,
	url: string,
	options: Leaflet.GridLayerOptions
): Leaflet.GridLayer {
	const Layer = L.GridLayer.extend({
		createTile(coords: Leaflet.Coords, done: Leaflet.DoneCallback) {
			const t = takeTile(SIZE);
			drawUrl(t, L.Util.template(url, coords))
				.then(() => repaint(t, radarRecolor, null))
				.then(
					() => done(undefined, t.canvas),
					() => done(undefined, t.canvas)
				);
			return t.canvas;
		}
	}) as unknown as Ctor<Leaflet.GridLayerOptions>;
	return releaseCanvases(new Layer({ tileSize: SIZE, ...options }));
}

function drawWpc(
	ctx: CanvasRenderingContext2D,
	fc: WpcCollection,
	map: Leaflet.Map,
	L: typeof Leaflet,
	coords: Leaflet.Coords
) {
	const origin = coords.scaleBy(L.point(SIZE, SIZE));
	const ring = (pts: number[][]) => {
		pts.forEach(([lon, lat], i) => {
			const p = map.project([lat, lon], coords.z).subtract(origin);
			if (i === 0) ctx.moveTo(p.x, p.y);
			else ctx.lineTo(p.x, p.y);
		});
		ctx.closePath();
	};
	for (const f of fc.features) {
		const color = untypedColor(f.properties.qpf);
		if (!color) continue;
		const polys = (
			f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates
		) as number[][][][];
		ctx.beginPath();
		for (const poly of polys) for (const r of poly) ring(r);
		ctx.fillStyle = color;
		ctx.fill('evenodd');
	}
}

export interface SouthSource {
	/** IEM forecast minute for this hour, or null when HRRR doesn't reach it. */
	hrrr: Promise<number | null>;
	/** NWS 6-hour totals for this hour, loaded on first use. */
	wpc: () => Promise<WpcCollection | null>;
}

export function southLayer(
	L: typeof Leaflet,
	source: SouthSource,
	options: Leaflet.GridLayerOptions
): Leaflet.GridLayer {
	const Layer = L.GridLayer.extend({
		createTile(this: Leaflet.GridLayer, coords: Leaflet.Coords, done: Leaflet.DoneCallback) {
			const t = takeTile(SIZE);
			const map = (this as unknown as { _map: Leaflet.Map })._map;
			draw(t, coords, map).then(
				() => done(undefined, t.canvas),
				() => done(undefined, t.canvas)
			);
			return t.canvas;
		}
	});

	async function draw(t: Tile, coords: Leaflet.Coords, map: Leaflet.Map) {
		const mask = await maskFor(coords).catch(() => null);
		// Entirely inside the Canadian model: nothing to draw, so hold no pixels.
		if (mask?.full) return void (t.canvas.width = t.canvas.height = 0);
		const minute = await source.hrrr;
		if (minute !== null) {
			try {
				await drawUrl(t, L.Util.template(hrrrTileUrl(minute), coords));
				return repaint(t, hrrrRecolor, mask?.cover ?? null);
			} catch {
				if (t.alive()) t.ctx.clearRect(0, 0, SIZE, SIZE);
			}
		}
		const fc = await source.wpc();
		if (!fc || !t.alive()) return;
		drawWpc(t.ctx, fc, map, L, coords);
		if (mask?.cover) repaint(t, null, mask.cover);
	}

	return releaseCanvases(
		new (Layer as unknown as Ctor<Leaflet.GridLayerOptions>)({ tileSize: SIZE, ...options })
	);
}

// ---- Background loading -------------------------------------------------------------

/** Tiles covering the map's current view, at `zoom` (capped to the source's native zoom). */
export function visibleTiles(
	map: Leaflet.Map,
	tileSize: number,
	maxNativeZoom = 99
): { x: number; y: number; z: number }[] {
	const z = Math.min(Math.round(map.getZoom()), maxNativeZoom);
	// The view in pixels at zoom z (which can differ from the map's when capped).
	const c = map.project(map.getCenter(), z);
	const half = map
		.getSize()
		.divideBy(2)
		.multiplyBy(2 ** (z - map.getZoom()));
	const n = 2 ** z;
	const out: { x: number; y: number; z: number }[] = [];
	const x0 = Math.floor((c.x - half.x) / tileSize);
	const x1 = Math.floor((c.x + half.x - 1) / tileSize);
	const y0 = Math.max(0, Math.floor((c.y - half.y) / tileSize));
	const y1 = Math.min(
		Math.ceil((256 * n) / tileSize) - 1,
		Math.floor((c.y + half.y - 1) / tileSize)
	);
	for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) out.push({ x, y, z });
	return out;
}

/** At most a few downloads at a time, so the sources aren't flooded (GeoMet answers 429). */
let active = 0;
const queue: (() => void)[] = [];
async function limited<T>(job: () => Promise<T>): Promise<T> {
	// The frame on screen comes first: wait while its tiles are loading.
	while (foreground > 0) await new Promise<void>((r) => idle.push(r));
	if (active >= 4) await new Promise<void>((r) => queue.push(r));
	active++;
	try {
		return await job();
	} finally {
		active--;
		queue.shift()?.();
	}
}

/**
 * Download one URL into the HTTP cache. Every layer asks for its images with CORS and
 * no credentials, the same as this, so the cached copy matches.
 */
export function warmUrl(url: string): Promise<void> {
	return limited(() =>
		fetch(url, { mode: 'cors', credentials: 'same-origin' }).then(
			(r) => void r.arrayBuffer().catch(() => {}),
			() => {}
		)
	);
}
