// The snow total on the map, drawn from numbers on the graphics chip like the radar
// (./layer.ts): every step of the slider (./steps.ts) is held as textures and the time on
// the slider is drawn from the two either side, so the slider moves smoothly and the map
// pans and tilts with nothing to wait for.
//
// Zoomed out it shows the plain total. Zoomed in (from ADJUST_FROM) it shows the snow at
// each pixel's elevation, so peaks get the snow above the snow level and valleys below it
// don't: the elevation comes from the terrain worker, one map tile at a time (the tiles 3D
// and the hill shading use, so they are usually on hand already). That used to be tiles
// the server painted on request, slow to come and fetched again for every window.
//
// Flat, MapLibre calls `render`: zoomed out the box is drawn in one go, zoomed in tile by
// tile (each with its own elevation). With 3D terrain it calls `renderToTerrainTile` once
// for each terrain tile. All work in the map's WebGL context happens inside MapLibre's
// calls to us; what arrives from the workers waits in a queue until the next one.
import type { CustomLayerInterface, CustomRenderMethodInput, Map as MlMap } from 'maplibre-gl';
import { FrameLoader, frameWorker, type Want, type WorkerLike } from './loader';
import type { StepPlanes } from './steps';
import { TotalGl, type Draw, type StepTex } from './totalgl';

/** One step of the slider, as the layer needs it. */
export interface TotalStepRef {
	/** The numbers file's name (it holds a hash of its contents). */
	file: string;
	url: string;
	/** Hours from the totals' start. */
	hours: number;
}

/** A tile's elevation (Terrarium RGBA, `size` px), or null if there is none to be had. */
export type ElevationSource = (
	z: number,
	x: number,
	y: number,
	size: number,
	signal: AbortSignal
) => Promise<Uint8Array | null>;

export interface TotalOptions {
	/** [[south, west], [north, east]] the steps cover, and their box in pixels. */
	bounds: [[number, number], [number, number]];
	width: number;
	height: number;
	beforeId?: string;
	opacity: (zoom: number) => number;
	maxzoom: number;
	/** Elevation tiles for the terrain-adjusted total; none: the plain total throughout. */
	elevation?: ElevationSource;
	onChange?: () => void;
	worker?: WorkerLike;
}

/** From this zoom in, the snow at each pixel's elevation (faded in over a zoom level). */
export const ADJUST_FROM = 8;
const ELEV_PX = 256;
/** Elevation tiles past this zoom are read from their ancestor at it (30 m and 10 m
 *  terrain is plenty for colouring snow). */
const ELEV_MAX_Z = 13;
const ELEV_KEPT = 64;
const ELEV_AT_ONCE = 6;
const UPLOAD_BUDGET = 8_000_000;
/** Tiles drawn flat at most (zoomed in far, a phone sees a handful). */
const FLAT_TILES = 48;
const TERRAIN_MS = 80;

const mercX = (lon: number) => (lon + 180) / 360;
const mercY = (lat: number) =>
	(1 -
		Math.log(Math.tan(Math.PI / 4 + (Math.max(-85, Math.min(85, lat)) * Math.PI) / 360)) /
			Math.PI) /
	2;

/** How much of the terrain adjustment shows at a zoom: none below ADJUST_FROM − ½, all
 *  from ADJUST_FROM + ½. */
export function adjustAt(zoom: number): number {
	const x = Math.min(1, Math.max(0, zoom - (ADJUST_FROM - 0.5)));
	return x * x * (3 - 2 * x);
}

/**
 * The steps either side of `hours` and how far between (0: all `a`). `a` is -1 before the
 * first step: from nothing at the start to the first step.
 */
export function bracketHours(hours: number, steps: number[]): { a: number; b: number; f: number } {
	const n = steps.length;
	if (!n) return { a: -1, b: -1, f: 0 };
	if (hours <= steps[0])
		return { a: -1, b: 0, f: steps[0] > 0 ? Math.max(0, hours) / steps[0] : 1 };
	for (let i = 0; i < n - 1; i++) {
		if (hours < steps[i + 1])
			return { a: i, b: i + 1, f: (hours - steps[i]) / (steps[i + 1] - steps[i]) };
	}
	return { a: n - 1, b: n - 1, f: 0 };
}

/** The elevation tile to read for a map tile, and where the map tile sits inside it. */
export function elevationFor(
	z: number,
	x: number,
	y: number
): { z: number; x: number; y: number; at: [number, number, number] } {
	if (z <= ELEV_MAX_Z) return { z, x, y, at: [0, 0, 1] };
	const d = z - ELEV_MAX_Z;
	const k = 2 ** d;
	const ex = Math.floor(x / k);
	const ey = Math.floor(y / k);
	return { z: ELEV_MAX_Z, x: ex, y: ey, at: [(x - ex * k) / k, (y - ey * k) / k, 1 / k] };
}

export class TotalLayer {
	static readonly ID = 'snowtotal';
	readonly id = TotalLayer.ID;
	private steps: TotalStepRef[] = [];
	private hours = 24;
	private gfx: TotalGl | null = null;
	private tex = new Map<string, StepTex>();
	private queue = new Map<string, StepPlanes>();
	private loader: FrameLoader<StepPlanes>;
	private elev = new Map<string, WebGLTexture>();
	private elevQueue = new Map<string, Uint8Array>();
	private elevAsked = new Map<string, AbortController>();
	/** Elevation tiles with none to be had (open sea at zoom 12 and below, offline). */
	private elevNone = new Set<string>();
	private drawn = '';
	private box: { x0: number; y0: number; dx: number; dy: number };
	private opts: TotalOptions;
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
		opts: TotalOptions
	) {
		this.opts = opts;
		const [[south, west], [north, east]] = opts.bounds;
		this.box = {
			x0: mercX(west),
			y0: mercY(north),
			dx: mercX(east) - mercX(west),
			dy: mercY(south) - mercY(north)
		};
		this.loader = new FrameLoader<StepPlanes>(
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

	setSteps(steps: TotalStepRef[]) {
		this.steps = [...steps].sort((a, b) => a.hours - b.hours);
		const files = new Set(this.steps.map((s) => s.file));
		for (const [key, t] of this.tex) {
			if (files.has(key)) continue;
			this.gfx?.free(t);
			this.tex.delete(key);
		}
		for (const key of [...this.queue.keys()]) if (!files.has(key)) this.queue.delete(key);
		this.rewant();
		this.changed();
	}

	/** The slider: hours from the totals' start. */
	setPosition(hours: number) {
		if (hours === this.hours) return;
		this.hours = hours;
		const { a, b, f } = bracketHours(
			hours,
			this.steps.map((s) => s.hours)
		);
		this.loader.seek(a < 0 ? b * f : a + f);
		this.changed();
	}

	setOpacity(opacity: (zoom: number) => number) {
		this.opts.opacity = opacity;
		this.changed(true);
	}

	setMaxZoom(maxzoom: number) {
		if (maxzoom === this.opts.maxzoom) return;
		this.opts.maxzoom = maxzoom;
		if (this.map.getLayer(this.id)) this.map.setLayerZoomRange(this.id, 0, maxzoom);
	}

	/** Steps ready to draw (by file). */
	ready(): Set<string> {
		return new Set(this.steps.filter((s) => this.tex.has(s.file)).map((s) => s.file));
	}

	/** The steps either side of the slider aren't on hand yet. */
	get waiting(): boolean {
		const p = this.bracket();
		return !p || p.exact === false;
	}

	/** What's on screen is the snow at each pixel's elevation (zoomed in, with bands). */
	adjusted(zoom = this.map.getZoom()): boolean {
		if (!this.opts.elevation || adjustAt(zoom) < 0.5) return false;
		const p = this.bracket();
		return !!p && p.b.bandCount > 0;
	}

	private rewant() {
		const wants: Want[] = this.steps.map((s, i) => ({
			key: s.file,
			url: s.url,
			half: false,
			at: i
		}));
		this.loader.want(wants);
	}

	private arrived(key: string, planes: StepPlanes) {
		this.queue.set(key, planes);
		this.map.triggerRepaint();
	}

	// ---- Drawing ----------------------------------------------------------------------

	private prepare(gl: WebGL2RenderingContext) {
		if (this.gone) return;
		if (this.gfx && !this.gfx.alive()) this.forget();
		if (!this.gfx) {
			try {
				this.gfx = new TotalGl(gl, this.opts.width, this.opts.height);
			} catch (e) {
				console.error(e);
				return;
			}
		}
		let spent = 0;
		for (const [key, planes] of this.queue) {
			if (spent > UPLOAD_BUDGET) break;
			this.queue.delete(key);
			if (!this.steps.some((s) => s.file === key)) continue;
			this.tex.set(key, this.gfx.upload(planes));
			spent += planes.area.length + planes.bands.length;
		}
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

	/** The pair to draw: exact when both are on hand, else the nearest step there is. */
	private bracket(): { a: StepTex | null; b: StepTex; f: number; exact: boolean } | null {
		const hours = this.steps.map((s) => s.hours);
		const { a, b, f } = bracketHours(this.hours, hours);
		if (b < 0) return null;
		const ta = a < 0 ? null : this.tex.get(this.steps[a].file);
		const tb = this.tex.get(this.steps[b].file);
		if (tb && (a < 0 || ta)) return { a: a < 0 ? null : ta!, b: tb, f, exact: true };
		// Something near, until the pair arrives.
		let best: StepTex | null = null;
		let bestD = Infinity;
		this.steps.forEach((s, i) => {
			const t = this.tex.get(s.file);
			const d = Math.abs(i - (a < 0 ? b : a + f));
			if (t && d < bestD) {
				best = t;
				bestD = d;
			}
		});
		return best ? { a: best, b: best, f: 0, exact: false } : null;
	}

	private signature(): string {
		const p = this.bracket();
		if (!p) return '';
		const name = (t: StepTex | null) => (t ? String(t.area) : '-');
		return `${name(p.a)}>${name(p.b)}@${p.f.toFixed(4)}|${this.tex.size}|${this.elev.size}`;
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
			// Most recently used last.
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

	private opacity(): number {
		return this.opts.opacity(this.map.getZoom());
	}

	private renderFlat(gl: WebGL2RenderingContext, args: CustomRenderMethodInput) {
		const p = this.gfx && this.bracket();
		if (!p || !this.gfx) return;
		const m = args.defaultProjectionData.mainMatrix as ArrayLike<number>;
		const zoom = this.map.getZoom();
		const adjust = this.opts.elevation ? adjustAt(zoom) : 0;
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
		const opacity = this.opacity();
		if (adjust <= 0) {
			this.gfx.draw(p.a, p.b, p.f, {
				matrix: place(x0, y0, dx, dy),
				quad: [0, 0, 1, 1],
				adjust: 0,
				opacity
			});
			return;
		}
		for (const t of this.flatTiles(zoom)) {
			const size = 1 / 2 ** t.z;
			const tx = t.x * size;
			const ty = t.y * size;
			this.gfx.draw(p.a, p.b, p.f, {
				matrix: place(tx, ty, size, size),
				quad: [(tx - x0) / dx, (ty - y0) / dy, size / dx, size / dy],
				elev: this.elevation(t.z, t.x, t.y),
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
		const p = this.gfx && this.bracket();
		if (!p || !this.gfx) return;
		const size = 1 / 2 ** tile.z;
		const tx = (tile.x + wrap * 2 ** tile.z) * size;
		const ty = tile.y * size;
		const { x0, y0, dx, dy } = this.box;
		if (x0 + dx <= tx || x0 >= tx + size || y0 + dy <= ty || y0 >= ty + size) return;
		const adjust = this.opts.elevation ? adjustAt(this.map.getZoom()) : 0;
		const draw: Draw = {
			matrix: [2, 0, 0, 0, 0, -2, 0, 0, 0, 0, 1, 0, -1, 1, 0, 1],
			quad: [(tx - x0) / dx, (ty - y0) / dy, size / dx, size / dy],
			elev: adjust > 0 ? this.elevation(tile.z, tile.x, tile.y) : undefined,
			adjust,
			opacity: this.opacity()
		};
		this.gfx.draw(p.a, p.b, p.f, draw);
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
