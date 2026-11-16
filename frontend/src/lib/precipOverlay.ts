// The precipitation pictures on the map.
//
// The server draws each frame as one picture over the locations' region (see
// ../radar.ts). Here we download them all once, keep them compressed (a couple of MB for
// the whole timeline), and decode only the frame on screen and its neighbours. Showing a
// frame draws the part of it on screen into a view-sized picture: radar, nowcast and
// forecast frames carry numbers, coloured on the GPU at the screen's resolution
// (map/precipGl.ts); the other layers' pictures are cropped and scaled.
import type { CanvasSource, Map as MlMap } from 'maplibre-gl';
import { PrecipGl, type FineSpec, type FrameRect } from './map/precipGl';
import { frameUrl, RAMPS } from './radar';

/** Anything with a picture file under /api/precip/: a frame or a snow total. */
type Pic = { file: string };

/** Decoded frames kept ready: the one on screen and a couple either side. */
const DECODED = 4;

export class FrameStore {
	private blobs = new Map<string, Blob>();
	private loading = new Map<string, Promise<Blob | null>>();
	private decoded = new Map<string, ImageBitmap>();
	/** Decodes under way, so two asks for one frame share one decode (and one bitmap). */
	private decoding = new Map<string, Promise<ImageBitmap | null>>();
	/** Cancels the downloads under way when the map closes. */
	private abort = new AbortController();
	private active = 0;
	private queue: (() => void)[] = [];

	has(f: Pic) {
		return this.blobs.has(f.file);
	}

	/** The frame's compressed picture, downloaded once (a few at a time). */
	blob(f: Pic, urgent = false): Promise<Blob | null> {
		const have = this.blobs.get(f.file);
		if (have) return Promise.resolve(have);
		let p = this.loading.get(f.file);
		if (!p) {
			p = this.limited(urgent, async () => {
				const res = await fetch(frameUrl(f), { signal: this.abort.signal });
				if (!res.ok) throw new Error(`frame ${res.status}`);
				return res.blob();
			}).then(
				(b) => {
					this.blobs.set(f.file, b);
					return b;
				},
				() => null
			);
			p.finally(() => this.loading.delete(f.file));
			this.loading.set(f.file, p);
		}
		return p;
	}

	/** The frame ready to draw. Older decoded frames are freed as new ones come in. */
	async bitmap(f: Pic): Promise<ImageBitmap | null> {
		const have = this.decoded.get(f.file);
		if (have) {
			this.decoded.delete(f.file);
			this.decoded.set(f.file, have);
			return have;
		}
		let p = this.decoding.get(f.file);
		if (!p) {
			p = this.decode(f).finally(() => this.decoding.delete(f.file));
			this.decoding.set(f.file, p);
		}
		return p;
	}

	private async decode(f: Pic): Promise<ImageBitmap | null> {
		const blob = await this.blob(f, true);
		if (!blob || !this.blobs.has(f.file)) return null;
		// No colour management: a fine frame's gray is a number, not a colour.
		const bmp = await createImageBitmap(blob, { colorSpaceConversion: 'none' });
		// Forgotten while it decoded (another timeline, or the map closed).
		if (!this.blobs.has(f.file)) {
			bmp.close();
			return null;
		}
		this.decoded.set(f.file, bmp);
		while (this.decoded.size > DECODED) {
			const [file, old] = this.decoded.entries().next().value!;
			this.decoded.delete(file);
			old.close();
		}
		return bmp;
	}

	/** Forget pictures no longer in the timeline. */
	keepOnly(frames: Pic[]) {
		const keep = new Set(frames.map((f) => f.file));
		for (const file of [...this.blobs.keys()]) if (!keep.has(file)) this.blobs.delete(file);
		for (const [file, bmp] of [...this.decoded]) {
			if (!keep.has(file)) {
				bmp.close();
				this.decoded.delete(file);
			}
		}
	}

	/** Forget everything and cancel the downloads under way (the map is closing). */
	clear() {
		this.abort.abort();
		this.abort = new AbortController();
		this.keepOnly([]);
	}

	/** At most four downloads at once; the frame being looked at jumps the queue. */
	private async limited<T>(urgent: boolean, job: () => Promise<T>): Promise<T> {
		if (this.active >= 4) {
			await new Promise<void>((r) => (urgent ? this.queue.unshift(r) : this.queue.push(r)));
		}
		this.active++;
		try {
			return await job();
		} finally {
			this.active--;
			this.queue.shift()?.();
		}
	}
}

/** A frame drawn over another, partly: the hand-over from the last nowcast frame to the
 *  forecast (radar.ts, `handover`). `weight` is the other frame's share. */
export interface Blend {
	file: string;
	bmp: ImageBitmap;
	weight: number;
}

/** What a picture is: numbers to colour (`fine`), or a picture to show as it is. */
export type PicKind = 'fine' | 'picture';

type Corners = [[number, number], [number, number], [number, number], [number, number]];

const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
const latOf = (y: number) => (360 / Math.PI) * Math.atan(Math.exp(y)) - 90;

/** How far past the view the picture reaches, each way (a share of the view): a short
 *  pan shows no edge before the picture is redrawn for the new view. */
const MARGIN = 0.25;
/** Most picture pixels per frame pixel when zoomed far in (outlines are already smooth). */
const MAX_DENSITY = 8;
/** Most pixels across either way. */
const MAX_SIDE = 4096;

/**
 * The precipitation in two MapLibre canvas sources, one over the other, each a picture of
 * the view (and a margin) rather than of the whole region, redrawn when the map stops
 * moving. A new frame is drawn into the one not showing, which then fades in over `fade`
 * ms while the other fades out: the GPU does the fade (a paint transition). It drapes over
 * 3D terrain like the base map.
 */
export class PrecipLayer {
	/** The two layers' ids; `ID` is the lower one, which other layers are placed by. */
	static readonly ID = 'precip';
	static readonly IDS = ['precip', 'precip-b'] as const;
	private canvases: HTMLCanvasElement[] = [];
	private ctxs: CanvasRenderingContext2D[] = [];
	/** Which of the two shows the frame on screen. */
	private front = 0;
	private shown: string | null = null;
	private opacity: unknown;
	/** When the fade under way ends (performance.now()), or 0. */
	private fadeEnds = 0;
	private onRender: (() => void) | null = null;
	private gl: PrecipGl | null = null;
	private glFailed = false;
	/** What's on screen, to draw again for a new view. */
	private current: {
		file: string | null;
		kind: PicKind;
		bmp: ImageBitmap | null;
		under: Blend | null;
	} = { file: null, kind: 'picture', bmp: null, under: null };
	private onMoveEnd = () => this.redraw();
	private readonly mx0: number;
	private readonly mx1: number;
	private readonly my0: number;
	private readonly my1: number;
	/** Milliseconds the last frame took to draw (for e2e/perf.spec.ts and DevTools). */
	lastDrawMs = 0;

	constructor(
		private map: MlMap,
		bounds: [[number, number], [number, number]],
		private width: number,
		private height: number,
		opacity: unknown,
		beforeId?: string,
		private spec: FineSpec | null = null
	) {
		this.opacity = opacity;
		const [[south, west], [north, east]] = bounds;
		this.mx0 = west;
		this.mx1 = east;
		this.my0 = mercY(north);
		this.my1 = mercY(south);
		const coordinates = this.corners({ x0: 0, y0: 0, x1: width, y1: height });
		PrecipLayer.IDS.forEach((id, i) => {
			const canvas = document.createElement('canvas');
			canvas.width = canvas.height = 1;
			this.canvases.push(canvas);
			this.ctxs.push(canvas.getContext('2d')!);
			map.addSource(id, { type: 'canvas', canvas, animate: false, coordinates });
			map.addLayer(
				{
					id,
					type: 'raster',
					source: id,
					paint: {
						'raster-opacity': (i === this.front ? opacity : 0) as number,
						'raster-opacity-transition': { duration: 0, delay: 0 },
						'raster-fade-duration': 0,
						'raster-resampling': 'linear'
					}
				},
				// Each under `beforeId`, so the second lands just above the first.
				beforeId
			);
		});
		map.on('moveend', this.onMoveEnd);
		map.on('resize', this.onMoveEnd);
	}

	get showing() {
		return this.shown;
	}

	/** The pictures' opacity (by zoom), for whichever layer is showing. */
	setOpacity(opacity: unknown) {
		this.opacity = opacity;
		const id = PrecipLayer.IDS[this.front];
		if (this.map.getLayer(id)) this.map.setPaintProperty(id, 'raster-opacity', opacity as number);
	}

	/** Frame pixels → the corners of that rectangle on the map. */
	private corners(r: FrameRect): Corners {
		const lon = (x: number) => this.mx0 + ((this.mx1 - this.mx0) * x) / this.width;
		const lat = (y: number) => latOf(this.my0 + ((this.my1 - this.my0) * y) / this.height);
		return [
			[lon(r.x0), lat(r.y0)],
			[lon(r.x1), lat(r.y0)],
			[lon(r.x1), lat(r.y1)],
			[lon(r.x0), lat(r.y1)]
		];
	}

	/** The part of the frame in view (and the margin), and the picture's size for it; null
	 *  when none of the frame is in view. */
	private view(): { rect: FrameRect; w: number; h: number } | null {
		const b = this.map.getBounds();
		const fx = (lon: number) => ((lon - this.mx0) / (this.mx1 - this.mx0)) * this.width;
		const fy = (lat: number) => ((mercY(lat) - this.my0) / (this.my1 - this.my0)) * this.height;
		let x0 = fx(b.getWest());
		let x1 = fx(b.getEast());
		let y0 = fy(Math.min(85, b.getNorth()));
		let y1 = fy(Math.max(-85, b.getSouth()));
		const mx = (x1 - x0) * MARGIN;
		const my = (y1 - y0) * MARGIN;
		x0 = Math.max(0, Math.floor(x0 - mx));
		x1 = Math.min(this.width, Math.ceil(x1 + mx));
		y0 = Math.max(0, Math.floor(y0 - my));
		y1 = Math.min(this.height, Math.ceil(y1 + my));
		if (x1 <= x0 || y1 <= y0) return null;
		// As many pixels as the screen shows across the same stretch, no more than
		// MAX_DENSITY a frame pixel.
		const c = this.map.getCanvas();
		const viewW = Math.max(1, fx(b.getEast()) - fx(b.getWest()));
		const perPx = Math.min(MAX_DENSITY, c.width / viewW);
		let w = Math.max(1, Math.round((x1 - x0) * perPx));
		let h = Math.max(1, Math.round((y1 - y0) * perPx));
		const shrink = Math.min(1, MAX_SIDE / Math.max(w, h));
		w = Math.max(1, Math.round(w * shrink));
		h = Math.max(1, Math.round(h * shrink));
		return { rect: { x0, y0, x1, y1 }, w, h };
	}

	/** Paint the current picture into layer `i` for the view; false when nothing to show. */
	private paint(i: number): boolean {
		const { kind, bmp, under, file } = this.current;
		const v = this.view();
		const canvas = this.canvases[i];
		const ctx = this.ctxs[i];
		const t0 = performance.now();
		if (!v || !bmp || !file) {
			canvas.width = canvas.height = 1;
			ctx.clearRect(0, 0, 1, 1);
		} else {
			if (canvas.width !== v.w || canvas.height !== v.h) {
				canvas.width = v.w;
				canvas.height = v.h;
			} else ctx.clearRect(0, 0, v.w, v.h);
			const gl = kind === 'fine' ? this.renderer() : null;
			// A freed bitmap can't be uploaded; one already on the GPU needn't be.
			if (gl && (bmp.width || gl.holds(0) === file)) {
				gl.hold(0, file, bmp);
				if (under && (under.bmp.width || gl.holds(1) === under.file))
					gl.hold(1, under.file, under.bmp);
				gl.render(v.rect, v.w, v.h, under?.weight ?? 0);
				ctx.drawImage(gl.canvas, 0, 0);
			} else if (bmp.width) {
				const { x0, y0, x1, y1 } = v.rect;
				ctx.imageSmoothingQuality = 'high';
				ctx.drawImage(bmp, x0, y0, x1 - x0, y1 - y0, 0, 0, v.w, v.h);
			}
		}
		const src = this.map.getSource(PrecipLayer.IDS[i]) as CanvasSource | undefined;
		if (v) src?.setCoordinates(this.corners(v.rect));
		// play() marks it changed and asks for a repaint; pause() uploads it right away.
		src?.play();
		src?.pause();
		this.lastDrawMs = performance.now() - t0;
		// Read by e2e/perf.spec.ts, and in DevTools on a phone.
		performance.measure?.('map:draw', { start: t0 });
		return !!v;
	}

	private renderer(): PrecipGl | null {
		if (this.gl || this.glFailed || !this.spec) return this.gl;
		this.gl = PrecipGl.create(this.spec, RAMPS, this.width, this.height);
		this.glFailed = !this.gl;
		return this.gl;
	}

	/**
	 * Show a picture (null: nothing), fading from the one on screen over `fade` ms. A fine
	 * frame can have another mixed in under it (the hand-over), at that one's weight.
	 */
	draw(
		file: string | null,
		bmp: ImageBitmap | null,
		fade = 0,
		under: Blend | null = null,
		kind: PicKind = 'picture'
	) {
		const back = 1 - this.front;
		const [idFront, idBack] = [PrecipLayer.IDS[this.front], PrecipLayer.IDS[back]];
		if (!this.map.getLayer(idFront) || !this.map.getLayer(idBack)) return;
		// A fade still under way: the layer it fades out is about to be drawn into, so it
		// goes at once rather than showing the new picture before its turn.
		this.setFade(idBack, 0, 0);
		this.current = { file, kind, bmp, under: under && under.weight > 0 ? under : null };
		this.paint(back);
		this.shown = file;
		this.setFade(idBack, this.opacity, fade);
		this.setFade(idFront, 0, fade);
		this.front = back;
		this.redrape(fade);
	}

	/** The picture on screen, drawn again for the view (the map has stopped moving). */
	redraw() {
		if (!this.current.file) return;
		// A fine frame's numbers are on the GPU; another picture needs its bitmap, which
		// may have been freed (then it stays as it is until the next frame).
		if (this.current.kind === 'picture' && !this.current.bmp?.width) return;
		this.paint(this.front);
		this.redrape(0);
	}

	private setFade(id: string, opacity: unknown, ms: number) {
		this.map.setPaintProperty(id, 'raster-opacity-transition', { duration: ms, delay: 0 });
		this.map.setPaintProperty(id, 'raster-opacity', opacity as number);
	}

	/**
	 * In 3D, MapLibre drapes layers over the terrain from a cached texture per terrain
	 * tile, redrawn when an image source changes but not a canvas source or a fade.
	 * Without this, the frame on screen stays the same while the slider moves: the cache
	 * is dropped now and on every frame drawn until the fade ends.
	 */
	private redrape(fade: number) {
		const terrain = this.map.terrain;
		if (!terrain) return;
		terrain.tileManager.releaseAllRTT();
		this.map.triggerRepaint();
		if (fade <= 0) return;
		this.fadeEnds = performance.now() + fade + 50;
		if (this.onRender) return;
		this.onRender = () => {
			const t = this.map.terrain;
			if (t) t.tileManager.releaseAllRTT();
			if (performance.now() >= this.fadeEnds && this.onRender) {
				this.map.off('render', this.onRender);
				this.onRender = null;
				// One last redraw, at the fade's end.
				if (t) {
					t.tileManager.releaseAllRTT();
					this.map.triggerRepaint();
				}
			}
		};
		this.map.on('render', this.onRender);
	}

	remove() {
		if (this.onRender) this.map.off('render', this.onRender);
		this.onRender = null;
		this.map.off('moveend', this.onMoveEnd);
		this.map.off('resize', this.onMoveEnd);
		for (const id of PrecipLayer.IDS) {
			if (this.map.getLayer(id)) this.map.removeLayer(id);
			if (this.map.getSource(id)) this.map.removeSource(id);
		}
		for (const c of this.canvases) c.width = c.height = 0;
		this.gl?.destroy();
		this.gl = null;
	}
}
