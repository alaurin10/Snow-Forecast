// What the page and the terrain worker say to each other.
import type { MatchParams, TerrainMode } from './analysis';
import type { Bounds } from './grid';
import type { ConcernInputs, ConcernParams } from './concern';
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

/** The concern index for a view (see concern.ts). */
export interface ConcernJob {
	inputs: ConcernInputs;
	params: ConcernParams;
	/** The nearest location's loading by wind sector and its transport, when wind counts. */
	windSectors: number[] | null;
	windScale: number;
	/** Today at the place, when sunny slopes count. */
	sunDate: Ymd | null;
	/** The forecast zone's polygons ([lon, lat] rings): nothing is drawn outside it. */
	zone: number[][][][];
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
			/** Draw only inside this zone (registered with a `zone` message first). */
			zone?: string;
	  }
	| { id: number; type: 'zone'; zone: string; polys: number[][][][] }
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
	| ({ id: number; type: 'concern'; bounds: Bounds; maxPx: number } & ConcernJob)
	| { id: number; type: 'sunpoint'; lat: number; lon: number; date: Ymd }
	| { id: number; type: 'windpoint'; lat: number; lon: number; sectors: number[] }
	/** Elevation and ground slope at each [lon, lat] along a line, from tiles at `z`. */
	| { id: number; type: 'profile'; points: [number, number][]; z: number }
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
			/** Along a line: metres above sea level and the ground's slope in degrees. */
			profile?: { elev: number[]; slope: number[] };
	  };
