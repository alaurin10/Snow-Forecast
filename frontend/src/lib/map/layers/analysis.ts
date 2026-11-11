// The whole-view terrain layers (shade at a time, sun hours in a day, wind effect):
// worked out by the terrain worker for what's on screen and laid over the map as one
// picture, like the precipitation frames.
import type { CanvasSource, Map as MlMap } from 'maplibre-gl';
import type { AreaJob, TerrainClient } from '../terrain/client';
import { EARTH, TILE } from '../terrain/dem';
import { around, type Bounds } from '../terrain/grid';

/**
 * The part of the map worth working on: what's on screen, but in a tilted view (which
 * reaches to the horizon) no further than a couple of screens from its centre.
 */
export function viewBounds(map: MlMap): Bounds {
	const b = map.getBounds();
	const c = map.getCenter();
	const el = map.getContainer();
	const metres = (EARTH * Math.cos((c.lat * Math.PI) / 180)) / (TILE * 2 ** map.getZoom());
	const reach =
		(Math.hypot(el.clientWidth, el.clientHeight) / 2) * metres * (1.1 + map.getPitch() / 60);
	const cap = around(c.lat, c.lng, reach);
	return [
		Math.max(b.getWest(), cap[0]),
		Math.max(b.getSouth(), cap[1]),
		Math.min(b.getEast(), cap[2]),
		Math.min(b.getNorth(), cap[3])
	];
}

/** One canvas over the box the picture covers; it drapes over 3D terrain like the base map. */
export class AnalysisLayer {
	static readonly ID = 'analysis';
	private canvas: HTMLCanvasElement;
	private ctx: CanvasRenderingContext2D;
	private empty = true;

	constructor(
		private map: MlMap,
		beforeId?: string
	) {
		this.canvas = document.createElement('canvas');
		this.canvas.width = this.canvas.height = 2;
		this.ctx = this.canvas.getContext('2d')!;
		map.addSource(AnalysisLayer.ID, {
			type: 'canvas',
			canvas: this.canvas,
			animate: false,
			coordinates: [
				[-1, 1],
				[1, 1],
				[1, -1],
				[-1, -1]
			]
		});
		map.addLayer(
			{
				id: AnalysisLayer.ID,
				type: 'raster',
				source: AnalysisLayer.ID,
				layout: { visibility: 'none' },
				paint: { 'raster-opacity': 0.5, 'raster-fade-duration': 0, 'raster-resampling': 'linear' }
			},
			beforeId
		);
	}

	/** Show a picture over its box, or nothing. The picture is closed once drawn. */
	draw(pic: { bitmap: ImageBitmap; bounds: Bounds } | null, opacity = 0.5) {
		const { map, canvas } = this;
		if (!map.getLayer(AnalysisLayer.ID)) return;
		if (!pic) {
			if (this.empty) return;
			this.empty = true;
			map.setLayoutProperty(AnalysisLayer.ID, 'visibility', 'none');
			this.refresh();
			return;
		}
		const { bitmap, bounds } = pic;
		if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
			canvas.width = bitmap.width;
			canvas.height = bitmap.height;
		} else this.ctx.clearRect(0, 0, canvas.width, canvas.height);
		this.ctx.drawImage(bitmap, 0, 0);
		bitmap.close();
		const [w, s, e, n] = bounds;
		const src = map.getSource(AnalysisLayer.ID) as CanvasSource | undefined;
		src?.setCoordinates([
			[w, n],
			[e, n],
			[e, s],
			[w, s]
		]);
		map.setPaintProperty(AnalysisLayer.ID, 'raster-opacity', opacity);
		map.setLayoutProperty(AnalysisLayer.ID, 'visibility', 'visible');
		this.empty = false;
		// play() marks the canvas changed and asks for a repaint; pause() uploads it now.
		src?.play();
		src?.pause();
		this.refresh();
	}

	/** In 3D the draped map is cached per terrain tile and a canvas change doesn't clear it. */
	private refresh() {
		if (this.map.terrain) {
			this.map.terrain.tileManager.releaseAllRTT();
			this.map.triggerRepaint();
		}
	}
}

export type AreaState = 'idle' | 'working' | 'failed';

/**
 * Keeps the layer showing the latest thing asked for. One job runs at a time; asking
 * again while one runs calls it off and starts the newest as soon as the worker lets go,
 * so dragging a slider never queues up work.
 */
export class AreaRunner {
	private want: { job: AreaJob; bounds: Bounds; maxPx: number; opacity: number } | null = null;
	private running: { cancel: () => void } | null = null;
	private stale = false;
	onstate: (s: AreaState) => void = () => {};

	constructor(
		private client: TerrainClient,
		private layer: AnalysisLayer
	) {}

	/** Ask for a picture, or for none. */
	request(job: AreaJob | null, bounds?: Bounds, maxPx = 768, opacity = 0.5) {
		this.want = job && bounds ? { job, bounds, maxPx, opacity } : null;
		if (!this.want) {
			this.layer.draw(null);
			this.onstate('idle');
		}
		if (this.running) {
			this.stale = true;
			this.running.cancel();
		} else this.next();
	}

	private next() {
		const want = this.want;
		if (!want) return;
		this.stale = false;
		this.onstate('working');
		const run = this.client.area(want.job, want.bounds, want.maxPx);
		this.running = run;
		run.done
			.then(
				(pic) => {
					if (this.stale || this.want !== want) return void pic?.bitmap.close();
					this.layer.draw(pic, want.opacity);
					this.onstate('idle');
				},
				() => {
					if (!this.stale && this.want === want) this.onstate('failed');
				}
			)
			.finally(() => {
				this.running = null;
				if (this.stale) this.next();
			});
	}

	stop() {
		this.want = null;
		this.running?.cancel();
	}
}
