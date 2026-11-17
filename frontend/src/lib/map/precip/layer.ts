// The radar on the map: a MapLibre custom layer that keeps every frame of the timeline on
// the graphics chip as numbers and draws the time on the slider from the two frames
// either side of it (./gl.ts). Moving the slider costs one draw: nothing is decoded,
// copied or uploaded, so it follows a finger however fast it goes.
//
// Flat, MapLibre calls `render` and the box is drawn with the map's own matrix. With 3D
// terrain on it calls `renderToTerrainTile` once for each terrain tile, and drapes what
// we draw with the layers round us; `terrainTileRevision` tells it when to ask again.
// Both go through the same shader with a different matrix, so they cannot disagree.
//
// All work in the map's WebGL context happens inside MapLibre's calls to us (`prerender`,
// `render`, `renderToTerrainTile`), where it expects its state to be disturbed; frames
// that arrive from the worker wait in a queue until the next one.
import type { CustomLayerInterface, CustomRenderMethodInput, Map as MlMap } from 'maplibre-gl';
import type { Planes } from './codec';
import { PrecipGl, type FrameTex } from './gl';
import { FrameLoader, frameWorker, type Want, type WorkerLike } from './loader';

/** One frame of the timeline, as the layer needs it. */
export interface RadarFrame {
	/** The numbers file's name (it names the frame: it holds a hash of its contents). */
	file: string;
	url: string;
	/** Kept at the map's full resolution by the server (radar, nowcast): a phone holds the
	 *  loop at half that and only the frame at rest in full. */
	full: boolean;
}

export interface RadarOptions {
	/** [[south, west], [north, east]] the frames cover, and their box in pixels. */
	bounds: [[number, number], [number, number]];
	width: number;
	height: number;
	beforeId?: string;
	/** How strongly the layer covers the map at a zoom. */
	opacity: (zoom: number) => number;
	/** Zoomed in this far the layer is hidden. */
	maxzoom: number;
	/** Hold the radar loop at half resolution (see RadarFrame.full). */
	lean: boolean;
	/** Frames arrived, or what is drawn changed: the controls may want to look again. */
	onChange?: () => void;
	/** For tests. */
	worker?: WorkerLike;
}

/** Bytes of new textures a single map frame may take (a full radar frame is ~3.5 MB). */
const UPLOAD_BUDGET = 8_000_000;
/** Frames kept in full on a lean device: the one at rest and the last few rested on. */
const SHARP_KEPT = 3;
/** In 3D, the radar's picture changes at most this often (ms): each change redraws every
 *  terrain tile under it, base map and all. */
const TERRAIN_MS = 80;
/** The slider must rest this long before a frame is fetched in full. */
const SETTLE_MS = 180;

const mercX = (lon: number) => (lon + 180) / 360;
const mercY = (lat: number) =>
	(1 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / Math.PI) / 2;

/** What the slider's position asks for: the frames either side and how far between. */
export function bracket(pos: number, count: number): { i0: number; i1: number; f: number } {
	const p = Math.min(Math.max(pos, 0), Math.max(0, count - 1));
	let i0 = Math.floor(p);
	let f = p - i0;
	// Within a hair of a frame is that frame (so "at rest" is exact).
	if (f > 0.999) {
		i0 = Math.min(count - 1, i0 + 1);
		f = 0;
	} else if (f < 0.001) f = 0;
	const i1 = f > 0 ? Math.min(count - 1, i0 + 1) : i0;
	return { i0, i1, f };
}

export class RadarLayer {
	static readonly ID = 'radar';
	private frames: RadarFrame[] = [];
	private pos = 0;
	private gfx: PrecipGl | null = null;
	private tex = new Map<string, FrameTex>();
	/** Frames waiting for the map's next frame to be uploaded, oldest first. */
	private queue = new Map<string, Planes>();
	private loader: FrameLoader;
	/** Frames wanted in full on a lean device, most recent last. */
	private sharp: string[] = [];
	private settle: ReturnType<typeof setTimeout> | undefined;
	/** What the last draw showed, to tell when a redraw is needed. */
	private drawn = '';
	private box: { x0: number; y0: number; dx: number; dy: number };
	private opts: RadarOptions;
	private gone = false;
	/** When 3D's terrain tiles were last asked to redraw, and the redraw waiting its turn. */
	private lastTerrain = 0;
	private trailing: ReturnType<typeof setTimeout> | undefined;
	/** For the timings e2e/perf.spec.ts reads (and DevTools shows): the first frame drawn,
	 *  and each new picture's cost on the main thread. */
	private marked = false;
	private timedSig = '';
	private tileMs = 0;
	private tileFrom = 0;
	private readonly layer: CustomLayerInterface;
	private onLost = () => this.forget();
	/** MapLibre rebuilds its style after a lost context without custom layers: we go back
	 *  in, and every frame is fetched (from the browser's cache) and uploaded again. */
	private onRestored = () => {
		this.attach();
		this.rewant();
		this.changed(true);
	};

	constructor(
		private map: MlMap,
		opts: RadarOptions
	) {
		this.opts = opts;
		const [[south, west], [north, east]] = opts.bounds;
		this.box = {
			x0: mercX(west),
			y0: mercY(north),
			dx: mercX(east) - mercX(west),
			dy: mercY(south) - mercY(north)
		};
		this.loader = new FrameLoader(
			opts.worker ?? frameWorker(),
			(key, planes) => this.arrived(key, planes),
			(key) => this.tex.has(key) || this.queue.has(key)
		);
		this.layer = {
			id: RadarLayer.ID,
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

	/** Into the map's style, if it isn't there. */
	private attach() {
		const map = this.map;
		if (this.gone || map.getLayer(RadarLayer.ID)) return;
		const before = this.opts.beforeId;
		try {
			map.addLayer(this.layer, before && map.getLayer(before) ? before : undefined);
		} catch {
			// The style is being rebuilt (after a lost context): once it's loaded.
			map.once('style.load', () => this.attach());
			return;
		}
		map.setLayerZoomRange(RadarLayer.ID, 0, this.opts.maxzoom);
	}

	// ---- What to show ---------------------------------------------------------------

	/** The timeline's frames, in order. Frames no longer in it are freed. */
	setFrames(frames: RadarFrame[]) {
		this.frames = frames;
		const files = new Set(frames.map((f) => f.file));
		this.sharp = this.sharp.filter((f) => files.has(f));
		this.rewant();
		const wanted = new Set(this.wants().map((w) => w.key));
		for (const [key, t] of this.tex) {
			if (wanted.has(key)) continue;
			this.gfx?.free(t);
			this.tex.delete(key);
		}
		for (const key of [...this.queue.keys()]) if (!wanted.has(key)) this.queue.delete(key);
		this.changed();
	}

	/** The slider's position: a frame's index, or between two. */
	setPosition(pos: number) {
		if (pos === this.pos) return;
		this.pos = pos;
		this.loader.seek(pos);
		if (this.opts.lean) {
			clearTimeout(this.settle);
			this.settle = setTimeout(() => this.rest(), SETTLE_MS);
		}
		this.changed();
	}

	setOpacity(opacity: (zoom: number) => number) {
		this.opts.opacity = opacity;
		this.changed(true);
	}

	setMaxZoom(maxzoom: number) {
		if (maxzoom === this.opts.maxzoom) return;
		this.opts.maxzoom = maxzoom;
		if (this.map.getLayer(RadarLayer.ID)) this.map.setLayerZoomRange(RadarLayer.ID, 0, maxzoom);
	}

	/** Frames ready to draw (by file). */
	ready(): Set<string> {
		const out = new Set<string>();
		for (const f of this.frames)
			if (this.tex.has(this.baseKey(f)) || this.tex.has(f.file)) out.add(f.file);
		return out;
	}

	/** The frames either side of the slider aren't both ready: an older picture shows. */
	get waiting(): boolean {
		if (!this.frames.length) return false;
		const { i0, i1 } = bracket(this.pos, this.frames.length);
		return !this.texOf(i0, false) || !this.texOf(i1, false);
	}

	/**
	 * Check the textures survived (call when the app comes back to the front): a phone can
	 * drop them without telling the page. If they're gone, everything is fetched again
	 * (from the browser's cache) and uploaded again.
	 */
	revive() {
		if (this.gfx && !this.gfx.alive()) {
			this.forget();
			this.rewant();
		}
		this.changed(true);
	}

	// ---- Frames in and out ------------------------------------------------------------

	private baseKey(f: RadarFrame): string {
		return this.opts.lean && f.full ? `${f.file}|half` : f.file;
	}

	private wants(): Want[] {
		const out: Want[] = this.frames.map((f, at) => ({
			key: this.baseKey(f),
			url: f.url,
			half: this.opts.lean && f.full,
			at
		}));
		for (const file of this.sharp) {
			const at = this.frames.findIndex((f) => f.file === file);
			if (at >= 0) out.push({ key: file, url: this.frames[at].url, half: false, at, first: true });
		}
		return out;
	}

	private rewant() {
		if (this.gone) return;
		this.loader.want(this.wants());
		this.loader.seek(this.pos);
	}

	/** The slider has rested on a frame: on a lean device, fetch that one in full. */
	private rest() {
		const { i0, f } = bracket(this.pos, this.frames.length);
		const frame = this.frames[i0];
		if (f !== 0 || !frame?.full) return;
		this.sharp = [...this.sharp.filter((x) => x !== frame.file), frame.file];
		for (const old of this.sharp.splice(0, Math.max(0, this.sharp.length - SHARP_KEPT))) {
			const t = this.tex.get(old);
			if (t) this.gfx?.free(t);
			this.tex.delete(old);
			this.queue.delete(old);
		}
		this.rewant();
	}

	private arrived(key: string, planes: Planes) {
		if (this.gone) return;
		this.queue.set(key, planes);
		this.map.triggerRepaint();
	}

	/** The context was lost (or our objects dropped): nothing we hold in it exists now. */
	private forget() {
		this.gfx = null;
		this.tex.clear();
		this.queue.clear();
		this.drawn = '';
	}

	// ---- Drawing ----------------------------------------------------------------------

	private texOf(i: number, sharp: boolean): FrameTex | undefined {
		const f = this.frames[i];
		if (!f) return undefined;
		return (
			(sharp ? this.tex.get(f.file) : undefined) ??
			this.tex.get(this.baseKey(f)) ??
			this.tex.get(f.file)
		);
	}

	/** The two textures to draw and their mix. With a frame missing, the nearest one that
	 *  is ready stands in, so the picture never goes blank while frames arrive. */
	private pick(): { a: FrameTex; b: FrameTex; f: number } | null {
		const n = this.frames.length;
		if (!n) return null;
		const { i0, i1, f } = bracket(this.pos, n);
		const a = this.texOf(i0, f === 0);
		const b = f === 0 ? a : this.texOf(i1, false);
		if (a && b) return { a, b, f };
		if (a || b) return { a: (a ?? b)!, b: (a ?? b)!, f: 0 };
		const at = Math.round(this.pos);
		for (let d = 1; d < n; d++) {
			const t = this.texOf(at - d, false) ?? this.texOf(at + d, false);
			if (t) return { a: t, b: t, f: 0 };
		}
		return null;
	}

	/** What a draw now would show, as a string to compare. */
	private signature(): string {
		const p = this.pick();
		if (!p) return '-';
		const name = (t: FrameTex) => {
			for (const [k, v] of this.tex) if (v === t) return k;
			return '?';
		};
		return `${name(p.a)}>${name(p.b)}@${p.f.toFixed(4)}`;
	}

	/** Ask the map to draw again if what we'd draw has changed (`force`: it has). */
	private changed(force = false) {
		if (this.gone) return;
		const sig = this.signature();
		if (force || sig !== this.drawn) {
			// In 3D a new picture redraws every terrain tile with the layers round it: at
			// most every TERRAIN_MS while the slider moves or plays, and always the last.
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

	/** Called by MapLibre before each map frame: set up, and upload frames that arrived. */
	private prepare(gl: WebGL2RenderingContext) {
		if (this.gone || gl.isContextLost()) return;
		if (this.tileMs > 0) {
			// The last map frame drew a new picture into the terrain tiles: its cost.
			performance.measure?.('map:draw', { start: this.tileFrom, duration: this.tileMs });
			this.tileMs = 0;
		}
		this.gfx ??= new PrecipGl(gl, this.opts.width, this.opts.height);
		if (!this.queue.size) return;
		let spent = 0;
		for (const [key, planes] of this.queue) {
			if (spent && spent + planes.rate.length > UPLOAD_BUDGET) break;
			this.queue.delete(key);
			const old = this.tex.get(key);
			if (old) this.gfx.free(old);
			this.tex.set(key, this.gfx.upload(planes));
			spent += planes.rate.length + planes.type.length;
		}
		if (this.queue.size) this.map.triggerRepaint();
		this.changed();
	}

	private renderFlat(gl: WebGL2RenderingContext, args: CustomRenderMethodInput) {
		const p = this.gfx && this.pick();
		if (!p || !this.gfx) return;
		const t0 = performance.now();
		const m = args.defaultProjectionData.mainMatrix as ArrayLike<number>;
		const { x0, y0, dx, dy } = this.box;
		// The map's matrix (Mercator 0..1 to clip) after "box 0..1 to Mercator".
		const out = new Float32Array(16);
		for (let r = 0; r < 4; r++) {
			out[r] = m[r] * dx;
			out[4 + r] = m[4 + r] * dy;
			out[8 + r] = m[8 + r];
			out[12 + r] = m[r] * x0 + m[4 + r] * y0 + m[12 + r];
		}
		this.gfx.draw(out, p.a, p.b, p.f, this.opts.opacity(this.map.getZoom()));
		this.timed(t0, false);
	}

	/** Draw the part of the box inside one terrain tile: clip space (-1, -1) is the tile's
	 *  south-west corner, (1, 1) its north-east. */
	private renderTile(
		gl: WebGL2RenderingContext,
		tile: { x: number; y: number; z: number },
		wrap: number
	) {
		const p = this.gfx && this.pick();
		if (!p || !this.gfx) return;
		const size = 1 / 2 ** tile.z;
		const tx = (tile.x + wrap * 2 ** tile.z) * size;
		const ty = tile.y * size;
		const { x0, y0, dx, dy } = this.box;
		if (x0 + dx <= tx || x0 >= tx + size || y0 + dy <= ty || y0 >= ty + size) return;
		// prettier-ignore
		const out = new Float32Array([
			(2 * dx) / size, 0, 0, 0,
			0, (-2 * dy) / size, 0, 0,
			0, 0, 1, 0,
			(2 * (x0 - tx)) / size - 1, 1 - (2 * (y0 - ty)) / size, 0, 1
		]);
		const t0 = performance.now();
		this.gfx.draw(out, p.a, p.b, p.f, this.opts.opacity(this.map.getZoom()));
		this.timed(t0, true);
	}

	/** Note a draw's cost when it shows a new picture. */
	private timed(t0: number, tile: boolean) {
		if (!this.marked) {
			this.marked = true;
			performance.mark?.('map:frame');
		}
		const sig = this.drawn;
		if (tile) {
			if (sig !== this.timedSig) {
				this.timedSig = sig;
				this.tileFrom = t0;
				this.tileMs = 0;
			}
			if (this.tileFrom) this.tileMs += performance.now() - t0;
			return;
		}
		if (sig === this.timedSig) return;
		this.timedSig = sig;
		performance.measure?.('map:draw', { start: t0 });
	}

	remove() {
		this.gone = true;
		clearTimeout(this.settle);
		clearTimeout(this.trailing);
		this.map.off('webglcontextlost', this.onLost);
		this.map.off('webglcontextrestored', this.onRestored);
		this.loader.dispose();
		if (this.gfx && !this.gfx.gl.isContextLost()) {
			for (const t of this.tex.values()) this.gfx.free(t);
			this.gfx.dispose();
		}
		this.forget();
		if (this.map.getLayer(RadarLayer.ID)) this.map.removeLayer(RadarLayer.ID);
	}
}

/** Whether this browser can draw the radar this way (else the pictures are used). */
export function radarGlSupported(): boolean {
	return (
		typeof DecompressionStream !== 'undefined' &&
		typeof Worker !== 'undefined' &&
		typeof WebGL2RenderingContext !== 'undefined'
	);
}
