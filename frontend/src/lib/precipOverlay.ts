// The weather pictures on the map: snow totals, snow level, wind, snow on the ground,
// observed snowfall and clouds, and the radar on a browser that can't draw it from numbers
// (./map/precip/layer.ts draws it everywhere else).
//
// The server draws each frame as one picture over the locations' region (see
// ../radar.ts). Here we download them all once, keep them compressed (a couple of MB for
// the whole timeline), and decode only the frame on screen and its neighbours. Showing a
// frame is a single draw into one canvas, so scrubbing is instant and memory stays flat.
import type { CanvasSource, Map as MlMap } from 'maplibre-gl';
import { frameUrl } from './radar';

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
		const bmp = await createImageBitmap(blob);
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

	/** Free the decoded pictures (they're decoded again from the downloads when next
	 *  asked for): after the app was in the background, where the browser may have
	 *  dropped the memory behind them. */
	forgetDecoded() {
		for (const bmp of this.decoded.values()) bmp.close();
		this.decoded.clear();
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

/**
 * The precipitation laid over the pictures' box in two MapLibre canvas sources, one over
 * the other. A new frame is drawn into the one not showing, which then fades in over
 * `fade` ms while the other fades out: one upload per frame, and the GPU does the fade
 * (a paint transition). It drapes over 3D terrain like the base map.
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
	/** Zoomed in this far the pictures are hidden (they've faded out, or tiles replace them). */
	private maxzoom: number;
	/** When the fade under way ends (performance.now()), or 0. */
	private fadeEnds = 0;
	private onRender: (() => void) | null = null;

	constructor(
		private map: MlMap,
		bounds: [[number, number], [number, number]],
		width: number,
		height: number,
		opacity: unknown,
		beforeId?: string,
		maxzoom = 24
	) {
		this.opacity = opacity;
		this.maxzoom = maxzoom;
		const [[south, west], [north, east]] = bounds;
		const coordinates: [[number, number], [number, number], [number, number], [number, number]] = [
			[west, north],
			[east, north],
			[east, south],
			[west, south]
		];
		PrecipLayer.IDS.forEach((id, i) => {
			const canvas = document.createElement('canvas');
			canvas.width = width;
			canvas.height = height;
			this.canvases.push(canvas);
			this.ctxs.push(canvas.getContext('2d')!);
			map.addSource(id, { type: 'canvas', canvas, animate: false, coordinates });
			map.addLayer(
				{
					id,
					type: 'raster',
					source: id,
					maxzoom,
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

	/** Hide the pictures from this zoom in. */
	setMaxZoom(maxzoom: number) {
		if (maxzoom === this.maxzoom) return;
		this.maxzoom = maxzoom;
		for (const id of PrecipLayer.IDS)
			if (this.map.getLayer(id)) this.map.setLayerZoomRange(id, 0, maxzoom);
	}

	/** Show a picture (null: nothing), fading from the one on screen over `fade` ms. */
	draw(file: string | null, bmp: ImageBitmap | null, fade = 0) {
		const t0 = performance.now();
		const back = 1 - this.front;
		const [idFront, idBack] = [PrecipLayer.IDS[this.front], PrecipLayer.IDS[back]];
		if (!this.map.getLayer(idFront) || !this.map.getLayer(idBack)) return;
		// A fade still under way: the layer it fades out is about to be drawn into, so it
		// goes at once rather than showing the new picture before its turn.
		this.setFade(idBack, 0, 0);
		const ctx = this.ctxs[back];
		const canvas = this.canvases[back];
		ctx.clearRect(0, 0, canvas.width, canvas.height);
		if (bmp) ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
		this.shown = file;
		const src = this.map.getSource(idBack) as CanvasSource | undefined;
		// play() marks it changed and asks for a repaint; pause() uploads it right away.
		src?.play();
		src?.pause();
		this.setFade(idBack, this.opacity, fade);
		this.setFade(idFront, 0, fade);
		this.front = back;
		this.redrape(fade);
		// A frame's cost on the main thread (read by e2e/perf.spec.ts, and in DevTools).
		performance.measure?.('map:draw', { start: t0 });
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
		for (const id of PrecipLayer.IDS) {
			if (this.map.getLayer(id)) this.map.removeLayer(id);
			if (this.map.getSource(id)) this.map.removeSource(id);
		}
		for (const c of this.canvases) c.width = c.height = 0;
	}
}
