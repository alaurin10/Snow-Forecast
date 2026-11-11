// What the page and the terrain worker say to each other.
import type { MatchParams, TerrainMode } from './analysis';
import type { Bounds } from './grid';
import type { SunFacts } from './shade';
import type { Ymd } from './sun';

export interface PointFacts {
	/** Metres above sea level. */
	elevation: number;
	/** Degrees. */
	slope: number;
	/** Compass degrees: the way the slope faces. */
	aspect: number;
	sea: boolean;
	/** The zoom the elevation came from (16 is 1 m lidar, 12 is 10–30 m). */
	srcZ: number;
	/** Ground size of the grid the slope was measured on. */
	metresPerPixel: number;
	/** Elevation came from the AWS tiles because Mapterhorn wasn't answering. */
	fallback: boolean;
}

export type WorkerRequest =
	| { id: number; type: 'init'; maxTiles: number }
	| { id: number; type: 'dem'; z: number; x: number; y: number }
	| {
			id: number;
			type: 'tile';
			mode: TerrainMode;
			z: number;
			x: number;
			y: number;
			match?: MatchParams;
	  }
	| { id: number; type: 'point'; lat: number; lon: number }
	// Whole-view layers: one picture over `bounds`, at most `maxPx` on its longer side.
	| { id: number; type: 'shade'; bounds: Bounds; maxPx: number; time: number }
	| { id: number; type: 'sunhours'; bounds: Bounds; maxPx: number; date: Ymd }
	| {
			id: number;
			type: 'wind';
			bounds: Bounds;
			maxPx: number;
			/** Share of the loading by wind sector, north first. */
			sectors: number[];
			/** How much snow the wind could move, 0 to 1. */
			scale: number;
	  }
	| { id: number; type: 'sunpoint'; lat: number; lon: number; date: Ymd }
	| { id: number; type: 'windpoint'; lat: number; lon: number; sectors: number[] }
	| { id: number; type: 'cancel'; target: number };

export type WorkerResponse =
	| { id: number; ok: false; error: string }
	| {
			id: number;
			ok: true;
			bytes?: ArrayBuffer;
			bitmap?: ImageBitmap;
			empty?: boolean;
			point?: PointFacts;
			/** The box a whole-view picture covers. */
			bounds?: Bounds;
			sun?: SunFacts;
			/** Wind effect at a spot, −1 (stripped) to 1 (loaded), before scaling. */
			wind?: number;
	  };
