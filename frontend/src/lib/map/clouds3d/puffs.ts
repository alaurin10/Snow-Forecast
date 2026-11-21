// The map's 3D clouds: where each puff of cloud goes around a location, for a time.
//
// Each location has its cloud layers hour by hour (backend analysis/clouds.py: base and
// top above sea level, and cover). Around it, within RADIUS_M, a fixed set of places for
// puffs is laid out once per layer (seeded by the location, so they don't jump about),
// each with a rank from a smooth noise field: a layer with 30% cover shows the 30% of
// places ranked lowest, so partial cloud comes in clumps with clear sky between, and an
// overcast layer shows them all, puffs grown to merge into a deck. Clear sky: none.
//
// Puffs sit between the layer's base and top (a deep layer shows its lower part: what
// the mountains meet), lit white on top and greyer beneath, greyer still for a thick
// deck. It's a picture of the forecast, not a measurement.
import type { CloudsOut } from '../../types.gen';

/** A location's cloud layers, as the map has them. */
export interface CloudSite {
	id: string;
	lat: number;
	lon: number;
	clouds: Pick<CloudsOut, 'start' | 'step_h' | 'layers'>;
}

/** One puff: where (Web Mercator 0..1 and metres above sea level), how big and how it
 *  looks. */
export interface Puff {
	x: number;
	y: number;
	/** Its middle's height above sea level, metres. */
	z: number;
	/** Half its width, metres. */
	r: number;
	/** Its height over its width (thin layers are flat). */
	squash: number;
	/** 0: bright fair-weather cloud, 1: a dark grey deck. */
	dark: number;
	/** How solid (0..1): puffs at the edge of the cover fade in and out. */
	alpha: number;
	/** A per-puff number for its shape. */
	seed: number;
	/** Web Mercator units per metre where it is. */
	per: number;
}

export const RADIUS_M = 14_000;
/** Places for puffs per layer around a location. */
export const SLOTS = 110;
/** A layer with less cover shows nothing (clear sky). */
export const MIN_COVER = 8;
/** At or above this, the layer is a deck: every place filled, puffs grown to merge. */
export const DECK_COVER = 85;
/** The deepest part of a layer drawn above its base, metres. */
const MAX_DEPTH_M = 2500;
/** Nothing drawn above this, metres above sea level. */
const CEILING_M = 7000;
const EARTH_M = 40_075_016.686;

/** A small seeded random number generator (mulberry32). */
export function rng(seed: number): () => number {
	let a = seed >>> 0;
	return () => {
		a = (a + 0x6d2b79f5) >>> 0;
		let t = a;
		t = Math.imul(t ^ (t >>> 15), t | 1);
		t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

function hash(s: string): number {
	let h = 2166136261;
	for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
	return h >>> 0;
}

/** Smooth noise in about 0..1: a few sine waves at odd angles, phase-shifted per seed. */
function smooth(x: number, y: number, seed: number): number {
	const r = rng(seed);
	let v = 0;
	for (let k = 0; k < 4; k++) {
		const a = r() * Math.PI * 2;
		const f = (0.8 + r() * 0.8) * (k + 1);
		v += Math.sin((x * Math.cos(a) + y * Math.sin(a)) * f + r() * 6.28) / (k + 1);
	}
	return v;
}

interface Slot {
	/** Metres east and north of the location. */
	dx: number;
	dy: number;
	/** 0..1: the share of cover at which this place fills (lowest first). */
	rank: number;
	size: number;
	height: number;
	seed: number;
}

const slotCache = new Map<string, Slot[]>();

/** A location's places for one layer's puffs (laid out once). */
export function slots(id: string, layer: number): Slot[] {
	const key = `${id}|${layer}`;
	const have = slotCache.get(key);
	if (have) return have;
	const seed = hash(key);
	const r = rng(seed);
	const raw: (Omit<Slot, 'rank'> & { noise: number })[] = [];
	for (let i = 0; i < SLOTS; i++) {
		// Evenly over the disc, a little jittered (a sunflower spiral).
		const t = (i + 0.5) / SLOTS;
		const ang = i * 2.399963 + r() * 0.6;
		const dist = Math.sqrt(t) * RADIUS_M * (0.92 + r() * 0.16);
		const dx = Math.cos(ang) * dist;
		const dy = Math.sin(ang) * dist;
		raw.push({
			dx,
			dy,
			noise: smooth(dx / 6000, dy / 6000, seed) + r() * 0.35,
			size: 0.75 + r() * 0.5,
			height: r(),
			seed: r()
		});
	}
	// Rank by the noise: an even spread of ranks, so cover maps to the share shown.
	const order = raw.map((_, i) => i).sort((a, b) => raw[a].noise - raw[b].noise);
	const out: Slot[] = new Array(SLOTS);
	order.forEach((i, k) => {
		const { noise: _n, ...rest } = raw[i];
		void _n;
		out[i] = { ...rest, rank: (k + 0.5) / SLOTS };
	});
	slotCache.set(key, out);
	return out;
}

/** A site's layers at a time (the nearest hour it has), or [] outside its hours. */
export function layersAt(site: CloudSite, t: number): number[][] {
	const c = site.clouds;
	const step = (c.step_h || 1) * 3600;
	const k = Math.round((t - c.start) / step);
	if (k < 0 || k >= c.layers.length) return [];
	return c.layers[k] as number[][];
}

const smoothstep = (a: number, b: number, x: number) => {
	const u = Math.min(1, Math.max(0, (x - a) / (b - a)));
	return u * u * (3 - 2 * u);
};

/** Every puff around the sites at time `t` (Unix seconds). */
export function puffsAt(sites: CloudSite[], t: number): Puff[] {
	const out: Puff[] = [];
	for (const site of sites) {
		const mx = (site.lon + 180) / 360;
		const s = Math.sin((site.lat * Math.PI) / 180);
		const my = 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
		// Mercator units per metre here.
		const per = 1 / (EARTH_M * Math.cos((site.lat * Math.PI) / 180));
		layersAt(site, t).forEach(([base, top, cover], li) => {
			if (cover < MIN_COVER || base >= CEILING_M) return;
			const share = cover / 100;
			const deck = smoothstep(DECK_COVER - 25, DECK_COVER, cover);
			const depth = Math.max(150, Math.min(top, base + MAX_DEPTH_M, CEILING_M) - base);
			// Fair-weather puffs ~1 km across; a deck's grow past the places' spacing (~2.4
			// km) to overlap into one sheet.
			const across = Math.min(1500, Math.max(550, depth * 0.7)) * (1 + 1.3 * deck);
			// A deck gets a second set of places between the first, to close the gaps.
			const places =
				deck > 0.5 ? [...slots(site.id, li), ...slots(site.id, li + 10)] : slots(site.id, li);
			for (const p of places) {
				const show = deck >= 1 ? 1 : smoothstep(p.rank - 0.06, p.rank + 0.02, share);
				// Thinning out towards the edge, so the clouds have no hard rim.
				const edge = 1 - smoothstep(0.7, 1.05, Math.hypot(p.dx, p.dy) / RADIUS_M);
				if (show * edge <= 0.02) continue;
				const r = across * p.size * (0.75 + 0.25 * edge);
				const squash = Math.min(1, Math.max(0.3, depth / (2 * r)));
				const half = r * squash;
				// The lower edge at the base, puffs reaching up through the layer.
				const z = base + half * 0.6 + p.height * Math.max(0, depth - 2 * half);
				out.push({
					x: mx + p.dx * per,
					y: my - p.dy * per,
					z,
					r,
					squash,
					dark: Math.min(1, 0.15 + 0.6 * deck + 0.25 * Math.min(1, depth / 3000)),
					alpha: show * edge,
					seed: p.seed,
					per
				});
			}
		});
	}
	return out;
}

/** "Clear", "Partly cloudy" or "Cloudy" for a site's layers at a time, and the lowest
 *  base (m), for words beside the picture. */
export function skyAt(
	site: CloudSite,
	t: number
): { sky: 'clear' | 'partly' | 'cloudy'; base: number | null } {
	const lays = layersAt(site, t).filter(([, , c]) => c >= MIN_COVER);
	let clear = 1;
	for (const [, , c] of lays) clear *= 1 - c / 100;
	const cover = 100 * (1 - clear);
	return {
		sky: cover < 20 ? 'clear' : cover < 70 ? 'partly' : 'cloudy',
		base: lays.length ? lays[0][0] : null
	};
}
