// The precipitation pictures on the map.
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
				const res = await fetch(frameUrl(f));
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
		const blob = await this.blob(f, true);
		if (!blob) return null;
		const again = this.decoded.get(f.file);
		if (again) return again;
		const bmp = await createImageBitmap(blob);
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

	clear() {
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
 * The precipitation as one canvas laid over the pictures' box, in a MapLibre canvas
 * source. It drapes over 3D terrain like the base map. Drawing a frame uploads the
 * canvas to the GPU once (play then pause), rather than every frame of an animation.
 */
export class PrecipLayer {
	readonly canvas: HTMLCanvasElement;
	private ctx: CanvasRenderingContext2D;
	private shown: string | null = null;
	static readonly ID = 'precip';

	constructor(
		private map: MlMap,
		bounds: [[number, number], [number, number]],
		width: number,
		height: number,
		opacity: unknown,
		beforeId?: string
	) {
		this.canvas = document.createElement('canvas');
		this.canvas.width = width;
		this.canvas.height = height;
		this.ctx = this.canvas.getContext('2d')!;
		const [[south, west], [north, east]] = bounds;
		map.addSource(PrecipLayer.ID, {
			type: 'canvas',
			canvas: this.canvas,
			animate: false,
			coordinates: [
				[west, north],
				[east, north],
				[east, south],
				[west, south]
			]
		});
		map.addLayer(
			{
				id: PrecipLayer.ID,
				type: 'raster',
				source: PrecipLayer.ID,
				paint: {
					'raster-opacity': opacity as number,
					'raster-fade-duration': 0,
					'raster-resampling': 'linear'
				}
			},
			beforeId
		);
	}

	get showing() {
		return this.shown;
	}

	draw(file: string | null, bmp: ImageBitmap | null) {
		this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
		if (bmp) this.ctx.drawImage(bmp, 0, 0, this.canvas.width, this.canvas.height);
		this.shown = file;
		const src = this.map.getSource(PrecipLayer.ID) as CanvasSource | undefined;
		// play() marks it changed and asks for a repaint; pause() uploads it right away.
		src?.play();
		src?.pause();
	}

	remove() {
		if (this.map.getLayer(PrecipLayer.ID)) this.map.removeLayer(PrecipLayer.ID);
		if (this.map.getSource(PrecipLayer.ID)) this.map.removeSource(PrecipLayer.ID);
	}
}
