// The precipitation pictures on the map.
//
// The mini PC draws each frame as one picture over the locations' region (see
// ../radar.ts). Here we download them all once, keep them compressed (a couple of MB for
// the whole timeline), and decode only the frame on screen and its neighbours. Showing a
// frame is a single draw into one canvas, so scrubbing is instant and memory stays flat.
import type * as Leaflet from 'leaflet';
import { frameUrl, type Frame } from './radar';

/** Decoded frames kept ready: the one on screen and a couple either side. */
const DECODED = 4;

export class FrameStore {
	private blobs = new Map<string, Blob>();
	private loading = new Map<string, Promise<Blob | null>>();
	private decoded = new Map<string, ImageBitmap>();
	private active = 0;
	private queue: (() => void)[] = [];

	has(f: Frame) {
		return this.blobs.has(f.file);
	}

	/** The frame's compressed picture, downloaded once (a few at a time). */
	blob(f: Frame, urgent = false): Promise<Blob | null> {
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
	async bitmap(f: Frame): Promise<ImageBitmap | null> {
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
	keepOnly(frames: Frame[]) {
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

/** One canvas stretched over the pictures' bounds, in the map's precipitation pane. */
export class PrecipCanvas {
	readonly canvas: HTMLCanvasElement;
	private ctx: CanvasRenderingContext2D;
	private layer: Leaflet.Layer;
	private shown: string | null = null;

	constructor(
		L: typeof Leaflet,
		bounds: Leaflet.LatLngBoundsExpression,
		width: number,
		height: number,
		opacity: number
	) {
		this.canvas = document.createElement('canvas');
		this.canvas.width = width;
		this.canvas.height = height;
		this.ctx = this.canvas.getContext('2d')!;
		// SVGOverlay places any element over a box and keeps it there through pans and zooms.
		this.layer = L.svgOverlay(this.canvas as unknown as SVGElement, bounds, {
			pane: 'precip',
			opacity,
			interactive: false
		});
	}

	addTo(map: Leaflet.Map) {
		this.layer.addTo(map);
		return this;
	}

	remove() {
		this.layer.remove();
	}

	get showing() {
		return this.shown;
	}

	draw(file: string | null, bmp: ImageBitmap | null) {
		this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
		if (bmp) this.ctx.drawImage(bmp, 0, 0, this.canvas.width, this.canvas.height);
		this.shown = file;
	}
}
