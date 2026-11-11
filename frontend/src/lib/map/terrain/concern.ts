// The terrain concern index (docs/MAP-PLAN.md, B7.3): the app's own experimental
// estimate, never a forecast. For each spot:
//
//   score = (base + wind + sun) × slope × match
//
//   base   the published danger (1–5) for the spot's elevation band, today
//   slope  0 below 25°, rising to 1 for 30–45°, less again on the steepest ground
//   match  higher where the spot's aspect and band are in a listed avalanche problem
//   wind   more where the wind-effect layer says loaded (when wind or storm slabs are
//          listed, or a lot of snow fell), less where it says scoured
//   sun    more on sunny east-to-west slopes on a day with a wet-snow problem or warming
//
// shown in four classes in a palette that is not the danger scale's. The numbers come
// from the server (config `terrain:`), which also decides who may see it at all.
import { SECTORS, sectorOf, type Sector } from './analysis';

export type Band = 'alpine' | 'treeline' | 'below';
export const BANDS: readonly Band[] = ['alpine', 'treeline', 'below'] as const;

/** Lowest and highest elevations the map deals in, metres. */
const LOW = -500;
const HIGH = 9000;

/** The band a height is in, from the treeline band [bottom, top] in metres. */
export function bandOf(elev: number, treeline: readonly [number, number]): Band {
	if (elev < treeline[0]) return 'below';
	return elev < treeline[1] ? 'treeline' : 'alpine';
}

/** The elevations a band covers, metres. */
export function bandRange(band: Band, treeline: readonly [number, number]): [number, number] {
	if (band === 'below') return [LOW, treeline[0]];
	if (band === 'treeline') return [treeline[0], treeline[1]];
	return [treeline[1], HIGH];
}

/** Bands as elevation ranges, neighbours merged (alpine + treeline is one range). */
export function bandRanges(bands: readonly Band[], treeline: readonly [number, number]) {
	const order: Band[] = ['below', 'treeline', 'alpine'];
	const out: [number, number][] = [];
	for (const b of order) {
		if (!bands.includes(b)) continue;
		const [lo, hi] = bandRange(b, treeline);
		const last = out[out.length - 1];
		if (last && last[1] === lo) last[1] = hi;
		else out.push([lo, hi]);
	}
	return out;
}

/** The server's settings (config `terrain:`), as `GET /api/map/concern` sends them. */
export interface ConcernParams {
	/** [from degrees, factor], rising; 0 below the first. */
	slope: [number, number][];
	matchListed: number;
	matchOther: number;
	matchNone: number;
	windLoaded: number;
	windScoured: number;
	/** Wind effect (−1 to 1, after scaling by the transport) beyond which it counts. */
	windEffect: number;
	sun: number;
	sunHours: number;
	/** Scores at which elevated, high and very high start. */
	classes: [number, number, number];
}

export type ProblemKind = 'wind' | 'storm' | 'wet' | 'other';

/** What kind of problem a center's name describes (both providers' wording). */
export function problemKind(name: string): ProblemKind {
	const n = name.toLowerCase();
	if (n.includes('wind')) return 'wind';
	if (n.includes('storm') || n.includes('new snow')) return 'storm';
	if (n.includes('wet') || n.includes('glide')) return 'wet';
	return 'other';
}

/** One listed problem, as the index uses it. Empty lists mean "all". */
export interface ConcernProblem {
	name: string;
	aspects: Sector[];
	bands: Band[];
}

export interface ConcernInputs {
	/** The published danger for today by band (null: no rating for that band). */
	danger: Record<Band, number | null>;
	/** Bottom and top of the treeline band, metres. */
	treeline: [number, number];
	problems: ConcernProblem[];
	/** Wind effect is known here (a location's wind is near enough and moved snow). */
	wind: boolean;
	/** Loading adds to the score: wind or storm slabs listed, or plenty of new snow. */
	windLoading: boolean;
	/** Sunny slopes add: a wet problem is listed, or warming or rain on snow is flagged. */
	sun: boolean;
}

export interface Spot {
	elev: number;
	slope: number;
	aspect: number;
	/** Wind effect after scaling by the transport, −1 to 1; null when not worked out. */
	wind: number | null;
	/** Hours of direct sun today; null when not worked out. */
	sunHours: number | null;
}

export interface ConcernFactors {
	band: Band;
	/** Published danger for the band; null means the index has nothing to say here. */
	base: number | null;
	slope: number;
	match: number;
	/** The first listed problem the spot matches. */
	problem: string | null;
	wind: number;
	sun: number;
	score: number;
	/** 0 lower, 1 elevated, 2 high, 3 very high; −1 not drawn (gentle ground, no rating). */
	cls: number;
}

const SUNNY: readonly Sector[] = ['E', 'SE', 'S', 'SW', 'W'];

export function slopeFactor(deg: number, table: readonly [number, number][]): number {
	let f = 0;
	for (const [from, factor] of table) if (deg >= from) f = factor;
	return f;
}

export function concernClass(score: number, classes: readonly [number, number, number]): number {
	if (score <= 0) return -1;
	if (score < classes[0]) return 0;
	if (score < classes[1]) return 1;
	return score < classes[2] ? 2 : 3;
}

/** Every factor for one spot. */
export function concernAt(s: Spot, inp: ConcernInputs, p: ConcernParams): ConcernFactors {
	const band = bandOf(s.elev, inp.treeline);
	const base = inp.danger[band];
	const sector = sectorOf(s.aspect);
	const slope = slopeFactor(s.slope, p.slope);
	let problem: string | null = null;
	for (const pr of inp.problems) {
		const aspectOk = !pr.aspects.length || pr.aspects.includes(sector);
		const bandOk = !pr.bands.length || pr.bands.includes(band);
		if (aspectOk && bandOk) {
			problem = pr.name;
			break;
		}
	}
	const match = !inp.problems.length ? p.matchNone : problem ? p.matchListed : p.matchOther;
	let wind = 0;
	if (inp.wind && s.wind != null) {
		if (s.wind >= p.windEffect && inp.windLoading) wind = p.windLoaded;
		else if (s.wind <= -p.windEffect) wind = p.windScoured;
	}
	const sun =
		inp.sun && s.sunHours != null && s.sunHours >= p.sunHours && SUNNY.includes(sector) ? p.sun : 0;
	if (base == null) return { band, base, slope, match, problem, wind, sun, score: 0, cls: -1 };
	const score = (base + wind + sun) * slope * match;
	return {
		band,
		base,
		slope,
		match,
		problem,
		wind,
		sun,
		score,
		cls: concernClass(score, p.classes)
	};
}

/** The classes as drawn. Blues to magenta: nothing like the danger scale's colours. */
export const CONCERN_CLASSES = [
	{ label: 'Lower', color: '#9fc3d9', alpha: 110 },
	{ label: 'Elevated', color: '#4f86d4', alpha: 190 },
	{ label: 'High', color: '#5d33b8', alpha: 220 },
	{ label: 'Very high', color: '#c0177c', alpha: 235 }
] as const;

function rgb(hex: string): [number, number, number] {
	const n = parseInt(hex.slice(1), 16);
	return [n >> 16, (n >> 8) & 255, n & 255];
}

/** One class per pixel (−1 clear) to RGBA. */
export function paintConcern(cls: Int8Array): Uint8ClampedArray<ArrayBuffer> {
	const out = new Uint8ClampedArray(cls.length * 4);
	const cols = CONCERN_CLASSES.map((c) => [...rgb(c.color), c.alpha]);
	for (let i = 0, j = 0; i < cls.length; i++, j += 4) {
		const k = cls[i];
		if (k < 0) continue;
		const c = cols[k];
		out[j] = c[0];
		out[j + 1] = c[1];
		out[j + 2] = c[2];
		out[j + 3] = c[3];
	}
	return out;
}

/** Sectors in their compass order, for validating what a center sent. */
export function sectors(list: readonly string[]): Sector[] {
	return SECTORS.filter((s) => list.includes(s));
}
