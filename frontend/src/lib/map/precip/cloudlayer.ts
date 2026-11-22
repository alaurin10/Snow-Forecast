// The forecast clouds on the map, drawn from numbers on the graphics chip (./cloudgl.ts):
// the frames the slider passes through are held as textures, so it moves with nothing to
// decode.
//
// Zoomed out it shows the cover, as the server's pictures do. Zoomed in (from
// ADJUST_FROM) it shows the cloud against each pixel's own elevation where the frame has
// heights: the elevation comes from the terrain worker, one map tile at a time (the tiles
// 3D and the hill shading use, so they are usually on hand already).
//
// Flat, MapLibre calls `render`: zoomed out the box is drawn in one go, zoomed in tile by
// tile (each with its own elevation). With 3D terrain it calls `renderToTerrainTile` once
// for each terrain tile. All work in the map's WebGL context happens inside MapLibre's
// calls to us; what arrives from the workers waits in a queue until the next one.
import type { CustomLayerInterface, CustomRenderMethodInput, Map as MlMap } from 'maplibre-gl';
import type { CloudPlanes } from './clouds';
import { CloudGl, type CloudDraw, type CloudTex } from './cloudgl';
import { FrameLoader, frameWorker, type Want, type WorkerLike } from './loader';
import { elevationFor, type ElevationSource } from './totallayer';

/** One frame of the slider, as the layer needs it. */
export interface CloudFrameRef {
	/** The numbers file's name (it holds a hash of its contents). */
	file: string;
	url: string;
}

export interface CloudOptions {
	/** [[south, west], [north, east]] the frames cover, and their box in pixels. */
	bounds: [[number, number], [number, number]];
	width: number;
	height: number;
	beforeId?: string;
	opacity: (zoom: number) => number;
	maxzoom: number;
	/** Elevation tiles for the clouds against the terrain; none: the cover throughout. */
	elevation?: ElevationSource;
	onChange?: () => void;
	worker?: WorkerLike;
}

/** From this zoom in, the clouds against the terrain (faded in over a zoom level). */
export const CLOUD_ADJUST_FROM = 8;
const ELEV_PX = 256;
const ELEV_KEPT = 64;
const ELEV_AT_ONCE = 6;
/** Frames kept as textures (~1.2 MB each on the chip), around the slider: a few behind
 *  it, more ahead (where playing goes). Others are fetched again if the slider comes back
 *  to them (the browser keeps the files). */
const BEHIND = 5;
const AHEAD = 10;
const UPLOAD_BUDGET = 4_000_000;
const FLAT_TILES = 48;
const ELEV_MAX_Z = 13;
const TERRAIN_MS = 80;

const mercX = (lon: number) => (lon + 180) / 360;
const mercY = (lat: number) =>
	(1 -
		Math.log(Math.tan(Math.PI / 4 + (Math.max(-85, Math.min(85, lat)) * Math.PI) / 360)) /
			Math.PI) /
	2;

/** How much of the terrain view shows at a zoom: none below ADJUST_FROM − ½, all from
 *  ADJUST_FROM + ½. */
export function cloudAdjustAt(zoom: number): number {
	const x = Math.min(1, Math.max(0, zoom - (CLOUD_ADJUST_FROM - 0.5)));
	return x * x * (3 - 2 * x);
}

export class CloudLayer {
	static readonly ID = 'cloudnumbers';
	readonly id = CloudLayer.ID;
	private frames: CloudFrameRef[] = [];
	/** The frame on the slider (its file), or null: none of ours (a satellite picture). */
	private current: string | null = null;
	private gfx: CloudGl | null = null;
	private tex = new Map<string, CloudTex>();
	private queue = new Map<string, CloudPlanes>();
	private loader: FrameLoader<CloudPlanes>;
	private elev = new Map<string, WebGLTexture>();
	private elevQueue = new Map<string, Uint8Array>();
	private elevAsked = new Map<string, AbortController>();
	private elevNone = new Set<string>();
	private drawn = '';
	private box: { x0: number; y0: number; dx: number; dy: number };
	private opts: CloudOptions;
	private gone = false;
	private lastTerrain = 0;
	private trailing: ReturnType<typeof setTimeout> | undefined;
	private readonly layer: CustomLayerInterface;
	private onLost = () => this.forget();
	private onRestored = () => {
		this.attach();
		this.rewant();
		this.changed(true);
	};

	constructor(
		private map: MlMap,
		opts: CloudOptions
	) {
		this.opts = opts;
		const [[south, west], [north, east]] = opts.bounds;
		this.box = {
			x0: mercX(west),
			y0: mercY(north),
			dx: mercX(east) - mercX(west),
			dy: mercY(south) - mercY(north)
		};
		this.loader = new FrameLoader<CloudPlanes>(
			opts.worker ?? frameWorker(),
			(key, planes) => this.arrived(key, planes),
			(key) => this.tex.has(key) || this.queue.has(key)
		);
		this.layer = {
			id: this.id,
			type: 'custom',
			renderingMode: '2d',
			terrainTileRevision: 0,
			prerender: (gl) => this.prepare(gl as WebGL2RenderingContext),
			render: (gl, args) => this.renderFlat(gl as WebGL2RenderingContext, args),
			renderToTerrainTile: (gl, tile) =>
				this.renderTile(gl as WebGL2RenderingContext, tile.tileID.canonical, tile.tileID.wrap ?? 0),
			onRemove: () => this.forget()
		};
		this.attach();
		map.on('webglcontextlost', this.onLost);
		map.on('webglcontextrestored', this.onRestored);
	}

	private attach() {
		const map = this.map;
		if (this.gone || map.getLayer(this.id)) return;
		const before = this.opts.beforeId;
		try {
			map.addLayer(this.layer, before && map.getLayer(before) ? before : undefined);
		} catch {
			map.once('style.load', () => this.attach());
			return;
		}
		map.setLayerZoomRange(this.id, 0, this.opts.maxzoom);
	}

	// ---- What to show ---------------------------------------------------------------

	setFrames(frames: CloudFrameRef[]) {
		this.frames = [...frames];
		const files = new Set(this.frames.map((f) => f.file));
		for (const [key, t] of this.tex) {
			if (files.has(key)) continue;
			this.gfx?.free(t);
			this.tex.delete(key);
		}
		for (const key of [...this.queue.keys()]) if (!files.has(key)) this.queue.delete(key);
		this.rewant();
		this.changed();
	}

	/** The frame on the slider (a numbers file), or null to draw nothing. */
	setFrame(file: string | null) {
		if (file === this.current) return;
		this.current = file;
		this.rewant();
		this.changed();
	}

	setOpacity(opacity: (zoom: number) => number) {
		this.opts.opacity = opacity;
		this.changed(true);
	}

	/** Frames ready to draw (by file). */
	ready(): Set<string> {
		return new Set(this.frames.filter((f) => this.tex.has(f.file)).map((f) => f.file));
	}

	/** Whether a frame is on hand (as a texture, or waiting to become one). */
	has(file: string): boolean {
		return this.tex.has(file) || this.queue.has(file);
	}

	/** The frame on the slider isn't on hand yet. */
	get waiting(): boolean {
		return !!this.current && !this.tex.has(this.current);
	}

	/** What's on screen is the cloud against the terrain (zoomed in, with cloud tops). */
	adjusted(zoom = this.map.getZoom()): boolean {
		if (!this.opts.elevation || cloudAdjustAt(zoom) < 0.5 || !this.current) return false;
		const t = this.tex.get(this.current);
		return !!t?.hasHeights && t.tops;
	}

	/** The frames to keep on hand: those around the slider. */
	private around(): Set<string> {
		const at = Math.max(
			0,
			this.frames.findIndex((f) => f.file === this.current)
		);
		return new Set(this.frames.slice(Math.max(0, at - BEHIND), at + AHEAD + 1).map((f) => f.file));
	}

	private rewant() {
		const keep = this.around();
		const wants: Want[] = this.frames
			.map((f, i) => ({ key: f.file, url: f.url, half: false, at: i }))
			.filter((w) => keep.has(w.key));
		const at = this.frames.findIndex((f) => f.file === this.current);
		this.loader.want(wants);
		this.loader.seek(Math.max(0, at));
	}

	private arrived(key: string, planes: CloudPlanes) {
		this.queue.set(key, planes);
		this.map.triggerRepaint();
	}

	// ---- Drawing ----------------------------------------------------------------------

	private prepare(gl: WebGL2RenderingContext) {
		if (this.gone) return;
		if (this.gfx && !this.gfx.alive()) this.forget();
		if (!this.gfx) {
			try {
				this.gfx = new CloudGl(gl, this.opts.width, this.opts.height);
			} catch (e) {
				console.error(e);
				return;
			}
		}
		let spent = 0;
		// The frame on the slider first.
		const order = [...this.queue.keys()].sort(
			(a, b) => +(b === this.current) - +(a === this.current)
		);
		for (const key of order) {
			if (spent > UPLOAD_BUDGET) break;
			const planes = this.queue.get(key)!;
			this.queue.delete(key);
			if (!this.around().has(key)) continue;
			this.tex.set(key, this.gfx.upload(planes));
			spent += planes.shares.length + planes.heights.length;
		}
		this.evict();
		for (const [key, rgba] of this.elevQueue) {
			this.elevQueue.delete(key);
			const old = this.elev.get(key);
			if (old) this.gfx.freeTexture(old);
			this.elev.set(key, this.gfx.elevation(rgba, ELEV_PX));
			while (this.elev.size > ELEV_KEPT) {
				const [k, t] = this.elev.entries().next().value!;
				this.elev.delete(k);
				this.gfx.freeTexture(t);
			}
		}
		if (this.queue.size) this.map.triggerRepaint();
		if (spent) this.changed();
	}

	/** Keep the frames around the slider; the rest go (fetched again if wanted). */
	private evict() {
		if (!this.gfx || this.tex.size <= BEHIND + AHEAD + 1) return;
		const keep = this.around();
		for (const [key, t] of this.tex) {
			if (keep.has(key)) continue;
			this.gfx.free(t);
			this.tex.delete(key);
		}
	}

	private shown(): CloudTex | null {
		return this.current ? (this.tex.get(this.current) ?? null) : null;
	}

	private signature(): string {
		const t = this.shown();
		return t ? `${this.current}|${this.elev.size}` : '';
	}

	private changed(force = false) {
		if (this.gone) return;
		const sig = this.signature();
		if (force || sig !== this.drawn) {
			const wait = this.map.terrain ? this.lastTerrain + TERRAIN_MS - performance.now() : 0;
			if (wait > 0 && !force) {
				if (!this.trailing)
					this.trailing = setTimeout(() => {
						this.trailing = undefined;
						this.changed();
					}, wait);
			} else {
				this.drawn = sig;
				this.lastTerrain = performance.now();
				this.layer.terrainTileRevision = (this.layer.terrainTileRevision ?? 0) + 1;
				this.map.triggerRepaint();
			}
		}
		this.opts.onChange?.();
	}

	/** A map tile's elevation texture, asked for if it isn't on hand. */
	private elevation(z: number, x: number, y: number) {
		const src = this.opts.elevation;
		if (!src) return undefined;
		const e = elevationFor(z, x, y);
		const key = `${e.z}/${e.x}/${e.y}`;
		const tex = this.elev.get(key);
		if (tex) {
			this.elev.delete(key);
			this.elev.set(key, tex);
			return { tex, at: e.at };
		}
		if (!this.elevAsked.has(key) && !this.elevNone.has(key) && this.elevAsked.size < ELEV_AT_ONCE) {
			const ctl = new AbortController();
			this.elevAsked.set(key, ctl);
			src(e.z, e.x, e.y, ELEV_PX, ctl.signal)
				.then(
					(rgba) => {
						if (this.gone) return;
						if (rgba && rgba.length === ELEV_PX * ELEV_PX * 4) this.elevQueue.set(key, rgba);
						else this.elevNone.add(key);
					},
					() => {
						// Tried again the next time the tile is drawn.
					}
				)
				.finally(() => {
					this.elevAsked.delete(key);
					if (!this.gone) this.changed(true);
				});
		}
		return undefined;
	}

	private renderFlat(gl: WebGL2RenderingContext, args: CustomRenderMethodInput) {
		const t = this.gfx && this.shown();
		if (!t || !this.gfx) return;
		const m = args.defaultProjectionData.mainMatrix as ArrayLike<number>;
		const zoom = this.map.getZoom();
		const adjust = this.opts.elevation && t.hasHeights ? cloudAdjustAt(zoom) : 0;
		const place = (x0: number, y0: number, dx: number, dy: number) => {
			const out = new Float32Array(16);
			for (let r = 0; r < 4; r++) {
				out[r] = m[r] * dx;
				out[4 + r] = m[4 + r] * dy;
				out[8 + r] = m[8 + r];
				out[12 + r] = m[r] * x0 + m[4 + r] * y0 + m[12 + r];
			}
			return out;
		};
		const { x0, y0, dx, dy } = this.box;
		const opacity = this.opts.opacity(zoom);
		if (adjust <= 0) {
			this.gfx.draw(t, { matrix: place(x0, y0, dx, dy), quad: [0, 0, 1, 1], adjust: 0, opacity });
			return;
		}
		for (const tile of this.flatTiles(zoom)) {
			const size = 1 / 2 ** tile.z;
			const tx = tile.x * size;
			const ty = tile.y * size;
			this.gfx.draw(t, {
				matrix: place(tx, ty, size, size),
				quad: [(tx - x0) / dx, (ty - y0) / dy, size / dx, size / dy],
				elev: this.elevation(tile.z, tile.x, tile.y),
				adjust,
				opacity
			});
		}
	}

	/** The map tiles that cover the view and the box, at about the screen's resolution. */
	private flatTiles(zoom: number): { z: number; x: number; y: number }[] {
		const z = Math.max(0, Math.min(ELEV_MAX_Z + 3, Math.round(zoom)));
		const n = 2 ** z;
		const b = this.map.getBounds();
		const { x0, y0, dx, dy } = this.box;
		const west = Math.max(mercX(b.getWest()), x0);
		const east = Math.min(mercX(b.getEast()), x0 + dx);
		const north = Math.max(mercY(b.getNorth()), y0);
		const south = Math.min(mercY(b.getSouth()), y0 + dy);
		if (west >= east || north >= south) return [];
		const out = [];
		for (let y = Math.floor(north * n); y <= Math.min(n - 1, Math.floor(south * n)); y++)
			for (let x = Math.floor(west * n); x <= Math.min(n - 1, Math.floor(east * n)); x++) {
				out.push({ z, x, y });
				if (out.length >= FLAT_TILES) return out;
			}
		return out;
	}

	/** Draw the part of the box inside one terrain tile: clip space (-1, -1) is the tile's
	 *  south-west corner, (1, 1) its north-east. */
	private renderTile(
		gl: WebGL2RenderingContext,
		tile: { x: number; y: number; z: number },
		wrap: number
	) {
		const t = this.gfx && this.shown();
		if (!t || !this.gfx) return;
		const size = 1 / 2 ** tile.z;
		const tx = (tile.x + wrap * 2 ** tile.z) * size;
		const ty = tile.y * size;
		const { x0, y0, dx, dy } = this.box;
		if (x0 + dx <= tx || x0 >= tx + size || y0 + dy <= ty || y0 >= ty + size) return;
		const zoom = this.map.getZoom();
		const adjust = this.opts.elevation && t.hasHeights ? cloudAdjustAt(zoom) : 0;
		const draw: CloudDraw = {
			matrix: [2, 0, 0, 0, 0, -2, 0, 0, 0, 0, 1, 0, -1, 1, 0, 1],
			quad: [(tx - x0) / dx, (ty - y0) / dy, size / dx, size / dy],
			elev: adjust > 0 ? this.elevation(tile.z, tile.x, tile.y) : undefined,
			adjust,
			opacity: this.opts.opacity(zoom)
		};
		this.gfx.draw(t, draw);
	}

	/** Drop everything held in the WebGL context (it was lost, or we're leaving). */
	private forget() {
		this.gfx = null;
		this.tex.clear();
		this.queue.clear();
		this.elev.clear();
		this.elevQueue.clear();
		this.drawn = '';
	}

	remove() {
		this.gone = true;
		clearTimeout(this.trailing);
		this.map.off('webglcontextlost', this.onLost);
		this.map.off('webglcontextrestored', this.onRestored);
		this.loader.dispose();
		for (const c of this.elevAsked.values()) c.abort();
		if (this.gfx && !this.gfx.gl.isContextLost()) {
			for (const t of this.tex.values()) this.gfx.free(t);
			for (const t of this.elev.values()) this.gfx.freeTexture(t);
			this.gfx.dispose();
		}
		this.forget();
		if (this.map.getLayer(this.id)) this.map.removeLayer(this.id);
	}
}
