// Canvas layers that repaint other services' tiles in our colours.
//
// radarLayer: observed radar. southLayer: the forecast for the parts of the US the Canadian model doesn't reach, as a Leaflet
// layer. Each 256 px tile is drawn on a canvas:
//
//   1. HRRR simulated radar for the hour (IEM tiles), repainted in our colours; or, if
//      HRRR has nothing for the hour or the tile fails, NWS 6-hour totals in tan.
//   2. The HRDPS domain is cut out, so the Canadian model alone shows where it covers.
//
// Tiles entirely inside the HRDPS domain fetch nothing beyond the (cached) mask.
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

function loadImage(url: string): Promise<HTMLImageElement> {
	return new Promise((resolve, reject) => {
		const img = new Image();
		img.crossOrigin = 'anonymous';
		img.onload = () => resolve(img);
		img.onerror = () => reject(new Error(`image ${url}`));
		img.src = url;
	});
}

/** Mask tiles: the same for every hour, so shared by all frames for the session. */
const masks = new Map<string, Promise<{ img: HTMLImageElement; full: boolean; empty: boolean }>>();

function maskFor(L: typeof Leaflet, map: Leaflet.Map, coords: Leaflet.Coords) {
	const key = `${coords.z}/${coords.x}/${coords.y}`;
	let p = masks.get(key);
	if (!p) {
		const nw = L.CRS.EPSG3857.project(map.unproject(coords.scaleBy(L.point(SIZE, SIZE)), coords.z));
		const se = L.CRS.EPSG3857.project(
			map.unproject(coords.add(L.point(1, 1)).scaleBy(L.point(SIZE, SIZE)), coords.z)
		);
		const q = new URLSearchParams({
			service: 'WMS',
			version: '1.3.0',
			request: 'GetMap',
			crs: 'EPSG:3857',
			bbox: `${nw.x},${se.y},${se.x},${nw.y}`,
			width: String(SIZE),
			height: String(SIZE),
			format: 'image/png',
			transparent: 'true',
			layers: DOMAIN_LAYER,
			styles: '',
			sld_body: domainSld()
		});
		p = loadImage(`${GEOMET}?${q}`).then((img) => {
			const c = document.createElement('canvas');
			c.width = c.height = SIZE;
			const ctx = c.getContext('2d', { willReadFrequently: true })!;
			ctx.drawImage(img, 0, 0);
			const a = ctx.getImageData(0, 0, SIZE, SIZE).data;
			let solid = 0;
			for (let i = 3; i < a.length; i += 4) if (a[i] > 0) solid++;
			return { img, full: solid === SIZE * SIZE, empty: solid === 0 };
		});
		// A failed mask is retried on the next tile that needs it.
		p.catch(() => masks.delete(key));
		masks.set(key, p);
	}
	return p;
}

type Recolor = (r: number, g: number, b: number) => string | null;
const caches = new Map<Recolor, Map<number, [number, number, number] | null>>();

/** Repaint a tile's pixels from a source palette into ours. */
function recolor(ctx: CanvasRenderingContext2D, fn: Recolor) {
	let cache = caches.get(fn);
	if (!cache) caches.set(fn, (cache = new Map()));
	const im = ctx.getImageData(0, 0, SIZE, SIZE);
	const d = im.data;
	for (let i = 0; i < d.length; i += 4) {
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

type Ctor = new (o: Leaflet.GridLayerOptions) => Leaflet.GridLayer;

/** Observed radar (RainViewer) tiles, repainted in our colours. */
export function radarLayer(
	L: typeof Leaflet,
	url: string,
	options: Leaflet.GridLayerOptions
): Leaflet.GridLayer {
	const Layer = L.GridLayer.extend({
		createTile(coords: Leaflet.Coords, done: Leaflet.DoneCallback) {
			const canvas = document.createElement('canvas');
			canvas.width = canvas.height = SIZE;
			loadImage(L.Util.template(url, coords))
				.then((img) => {
					const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
					ctx.drawImage(img, 0, 0);
					recolor(ctx, radarRecolor);
				})
				.then(
					() => done(undefined, canvas),
					() => done(undefined, canvas)
				);
			return canvas;
		}
	}) as unknown as Ctor;
	return new Layer({ tileSize: SIZE, ...options });
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
			const canvas = document.createElement('canvas');
			canvas.width = canvas.height = SIZE;
			const map = (this as unknown as { _map: Leaflet.Map })._map;
			draw(canvas, coords, map).then(
				() => done(undefined, canvas),
				() => done(undefined, canvas)
			);
			return canvas;
		}
	});

	async function draw(canvas: HTMLCanvasElement, coords: Leaflet.Coords, map: Leaflet.Map) {
		const mask = await maskFor(L, map, coords).catch(() => null);
		if (mask?.full) return;
		const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
		let drawn = false;
		const minute = await source.hrrr;
		if (minute !== null) {
			const url = L.Util.template(hrrrTileUrl(minute), coords);
			try {
				ctx.drawImage(await loadImage(url), 0, 0);
				recolor(ctx, hrrrRecolor);
				drawn = true;
			} catch {
				ctx.clearRect(0, 0, SIZE, SIZE);
			}
		}
		if (!drawn) {
			const fc = await source.wpc();
			if (fc) drawWpc(ctx, fc, map, L, coords);
		}
		if (mask && !mask.empty) {
			ctx.globalCompositeOperation = 'destination-out';
			ctx.drawImage(mask.img, 0, 0);
			ctx.globalCompositeOperation = 'source-over';
		}
	}

	return new (Layer as unknown as Ctor)({ tileSize: SIZE, ...options });
}
