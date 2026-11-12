// Measuring a line on the map (docs/MAP-PLAN.md, B8 and B9): a line tapped out, a ski run
// or tour tapped on the map, or a GPX track. Pure functions: the terrain worker samples
// the elevation and slope under the line, and these turn the samples into the numbers,
// the profile and the coloured segments.
import type { UnitSystem } from '../units';
import { mToFt } from '../units';
import { SLOPE_CLASSES, slopeClass } from './terrain/analysis';

/** [lon, lat], as GeoJSON has it. */
export type LngLat = [number, number];

/** One point along the line, with the terrain under it. */
export interface Sample {
	lon: number;
	lat: number;
	/** Metres along the line from its start. */
	d: number;
	/** Metres above sea level. */
	elev: number;
	/** The ground's own slope there, in degrees (not the line's). */
	slope: number;
}

export interface LineStats {
	/** Metres along the ground's plan (as a map measures it). */
	distance: number;
	/** Metres up and down, ignoring wiggles smaller than the elevation data's noise. */
	climb: number;
	descent: number;
	minElev: number;
	maxElev: number;
	/** Average steepness of the line itself, up and down together, in degrees. */
	avgGrade: number;
	/** The steepest stretch of the line over at least `GRADE_RUN_M`, in degrees. */
	steepGrade: number;
	/** The steepest ground the line crosses, in degrees, and where. */
	steepGround: number;
	steepAt: number;
}

const R = 6371008.8;
/** The line's steepest stretch is measured over this much ground: shorter is noise. */
export const GRADE_RUN_M = 50;
/** Elevation changes smaller than this aren't counted as climbing (the data's noise). */
export const CLIMB_NOISE_M = 2;
/** Samples taken along a line, at most; and never closer than this. */
export const MAX_SAMPLES = 400;
export const MIN_STEP_M = 10;
/** GPX points kept for drawing; the profile is sampled separately. */
export const MAX_TRACK_POINTS = 5000;

const rad = (d: number) => (d * Math.PI) / 180;

/** Metres between two points along the ground (haversine). */
export function haversine(a: LngLat, b: LngLat): number {
	const dLat = rad(b[1] - a[1]);
	const dLon = rad(b[0] - a[0]);
	const h =
		Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLon / 2) ** 2;
	return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function lineLength(pts: LngLat[]): number {
	let d = 0;
	for (let i = 1; i < pts.length; i++) d += haversine(pts[i - 1], pts[i]);
	return d;
}

/**
 * Points every few metres along a line (every `MIN_STEP_M`, or further apart so there are
 * at most `MAX_SAMPLES`), with the distance of each from the start. Corners are kept.
 */
export function densify(
	pts: LngLat[],
	maxSamples = MAX_SAMPLES,
	minStep = MIN_STEP_M
): { points: LngLat[]; d: number[] } {
	if (pts.length === 0) return { points: [], d: [] };
	const total = lineLength(pts);
	// A long track (GPX) has more corners than samples: take evenly spaced points instead.
	const even = pts.length * 2 > maxSamples;
	const step = Math.max(
		minStep,
		total / Math.max(1, even ? maxSamples - 1 : maxSamples - pts.length)
	);
	const points: LngLat[] = [pts[0]];
	const d = [0];
	let at = 0;
	let next = step;
	for (let i = 1; i < pts.length; i++) {
		const a = pts[i - 1];
		const b = pts[i];
		const seg = haversine(a, b);
		if (!even) next = at + step;
		while (seg > 0 && next < at + seg - 1e-6) {
			const t = (next - at) / seg;
			points.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
			d.push(next);
			next += step;
		}
		at += seg;
		if (!even || i === pts.length - 1) {
			points.push(b);
			d.push(at);
		}
	}
	return { points, d };
}

/** The numbers for a sampled line. */
export function lineStats(s: Sample[]): LineStats | null {
	if (s.length < 2) return null;
	let climb = 0;
	let descent = 0;
	let ref = s[0].elev;
	let minElev = Infinity;
	let maxElev = -Infinity;
	let steepGround = 0;
	let steepAt = 0;
	for (let i = 0; i < s.length; i++) {
		const e = s[i].elev;
		minElev = Math.min(minElev, e);
		maxElev = Math.max(maxElev, e);
		if (e - ref >= CLIMB_NOISE_M) {
			climb += e - ref;
			ref = e;
		} else if (ref - e >= CLIMB_NOISE_M) {
			descent += ref - e;
			ref = e;
		}
		if (s[i].slope > steepGround) {
			steepGround = s[i].slope;
			steepAt = i;
		}
	}
	const distance = s[s.length - 1].d;
	// The steepest stretch of the line: each sample against the first one GRADE_RUN_M on.
	let steepGrade = 0;
	let j = 0;
	for (let i = 0; i < s.length; i++) {
		while (j < s.length && s[j].d - s[i].d < GRADE_RUN_M) j++;
		if (j >= s.length) break;
		const run = s[j].d - s[i].d;
		steepGrade = Math.max(steepGrade, deg(Math.abs(s[j].elev - s[i].elev), run));
	}
	// A line shorter than that: its whole length.
	if (distance > 0 && distance < GRADE_RUN_M)
		steepGrade = deg(Math.abs(s[s.length - 1].elev - s[0].elev), distance);
	return {
		distance,
		climb,
		descent,
		minElev,
		maxElev,
		avgGrade: distance > 0 ? deg(climb + descent, distance) : 0,
		steepGrade,
		steepGround,
		steepAt
	};
}

const deg = (rise: number, run: number) => (Math.atan2(rise, run) * 180) / Math.PI;

/** Colour of a slope class on the map and the profile: the slope overlay's, or plain below 25°. */
export const FLAT_COLOR = '#5b6b7a';
export function slopeColor(deg: number): string {
	const k = slopeClass(deg);
	return k < 0 ? FLAT_COLOR : SLOPE_CLASSES[k].color;
}

/** Runs of consecutive samples in the same slope class, each with its colour. */
export function segments(s: Sample[]): { from: number; to: number; color: string }[] {
	const out: { from: number; to: number; color: string }[] = [];
	for (let i = 0; i + 1 < s.length; i++) {
		// A stretch takes the steeper of its two ends: a short steep pitch isn't lost.
		const color = slopeColor(Math.max(s[i].slope, s[i + 1].slope));
		const last = out[out.length - 1];
		if (last && last.color === color && last.to === i) last.to = i + 1;
		else out.push({ from: i, to: i + 1, color });
	}
	return out;
}

/** The line as coloured GeoJSON segments for the map. */
export function segmentsGeojson(s: Sample[]): GeoJSON.FeatureCollection {
	return {
		type: 'FeatureCollection',
		features: segments(s).map((g) => ({
			type: 'Feature',
			properties: { color: g.color },
			geometry: {
				type: 'LineString',
				coordinates: s.slice(g.from, g.to + 1).map((p) => [p.lon, p.lat])
			}
		}))
	};
}

// ---- Words and numbers in the viewer's units -----------------------------------------

export function distanceText(m: number, units: UnitSystem): string {
	if (units === 'imperial') {
		const mi = m / 1609.344;
		return mi < 0.2 ? `${Math.round(mToFt(m) / 10) * 10} ft` : `${mi.toFixed(mi < 10 ? 2 : 1)} mi`;
	}
	return m < 1000 ? `${Math.round(m / 5) * 5} m` : `${(m / 1000).toFixed(m < 10000 ? 2 : 1)} km`;
}

/** A height difference (climb, descent, vertical), rounded less than an elevation. */
export function heightText(m: number, units: UnitSystem): string {
	return units === 'imperial'
		? `${Math.round(mToFt(m) / 10) * 10} ft`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
		: `${Math.round(m)} m`.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// ---- Lines from the map's features ---------------------------------------------------

/**
 * One line from a MultiLineString's pieces (a ski route made of many ways), joined end to
 * end where they meet, nearest piece next otherwise.
 */
export function joinLines(parts: LngLat[][]): LngLat[] {
	const pool = parts.filter((p) => p.length >= 2).map((p) => [...p]);
	if (!pool.length) return [];
	const line = pool.shift()!;
	while (pool.length) {
		const end = line[line.length - 1];
		const start = line[0];
		let best = 0;
		let bestD = Infinity;
		let how: 'end' | 'endRev' | 'start' | 'startRev' = 'end';
		pool.forEach((p, i) => {
			const options: [number, typeof how][] = [
				[haversine(end, p[0]), 'end'],
				[haversine(end, p[p.length - 1]), 'endRev'],
				[haversine(start, p[p.length - 1]), 'start'],
				[haversine(start, p[0]), 'startRev']
			];
			for (const [d, h] of options)
				if (d < bestD) {
					bestD = d;
					best = i;
					how = h;
				}
		});
		const p = pool.splice(best, 1)[0];
		if (how === 'end') line.push(...p.slice(bestD === 0 ? 1 : 0));
		else if (how === 'endRev') line.push(...p.reverse().slice(bestD === 0 ? 1 : 0));
		else if (how === 'start') line.unshift(...p.slice(0, bestD === 0 ? -1 : undefined));
		else line.unshift(...p.reverse().slice(0, bestD === 0 ? -1 : undefined));
	}
	return line;
}

// ---- GPX ---------------------------------------------------------------------------

export interface Track {
	name: string;
	points: LngLat[];
}

/**
 * A GPX file's track (or route) as one line, read here in the browser: the file is never
 * sent anywhere. Every track segment, in order; long tracks are thinned for drawing.
 */
export function parseGpx(text: string): Track {
	const doc = new DOMParser().parseFromString(text, 'application/xml');
	if (doc.getElementsByTagName('parsererror').length) throw new Error('This isn’t a GPX file.');
	const pick = (tag: string) =>
		[...doc.getElementsByTagNameNS('*', tag)]
			.map((el): LngLat => [Number(el.getAttribute('lon')), Number(el.getAttribute('lat'))])
			.filter(
				([lon, lat]) =>
					Number.isFinite(lon) &&
					Number.isFinite(lat) &&
					Math.abs(lat) <= 90 &&
					Math.abs(lon) <= 180
			);
	let points = pick('trkpt');
	if (points.length < 2) points = pick('rtept');
	if (points.length < 2) throw new Error('No track or route in this GPX file.');
	if (points.length > MAX_TRACK_POINTS) {
		const k = Math.ceil(points.length / MAX_TRACK_POINTS);
		points = points.filter((_, i) => i % k === 0 || i === points.length - 1);
	}
	const named = [...doc.getElementsByTagNameNS('*', 'name')].find(
		(el) => el.parentElement?.localName === 'trk' || el.parentElement?.localName === 'rte'
	);
	const meta = [...doc.getElementsByTagNameNS('*', 'name')].find(
		(el) => el.parentElement?.localName === 'metadata'
	);
	const name = (named?.textContent ?? meta?.textContent ?? '').trim().slice(0, 80);
	return { name, points };
}

/** [west, south, east, north] around a line. */
export function lineBounds(pts: LngLat[]): [number, number, number, number] {
	let w = Infinity;
	let s = Infinity;
	let e = -Infinity;
	let n = -Infinity;
	for (const [lon, lat] of pts) {
		w = Math.min(w, lon);
		e = Math.max(e, lon);
		s = Math.min(s, lat);
		n = Math.max(n, lat);
	}
	return [w, s, e, n];
}

// ---- Sampling the terrain under a line ---------------------------------------------

/** Elevation tiles whose pixels are about half the sample spacing: zoom 10 to 14. */
export function profileZoom(stepM: number, lat: number): number {
	const atZ0 = (40075016.686 * Math.cos(rad(lat))) / 512;
	const z = Math.round(Math.log2(atZ0 / Math.max(1, stepM / 2)));
	return Math.min(14, Math.max(10, z));
}

/** What the terrain worker answers for a line (TerrainClient.profile). */
export type ProfileFn = (
	points: LngLat[],
	z: number,
	signal?: AbortSignal
) => Promise<{ elev: number[]; slope: number[] }>;

/** The line sampled every few metres, with the terrain under each sample. */
export async function sampleLine(
	pts: LngLat[],
	profile: ProfileFn,
	signal?: AbortSignal
): Promise<Sample[]> {
	const { points, d } = densify(pts);
	if (points.length < 2) return [];
	const step = d[d.length - 1] / (points.length - 1);
	const { elev, slope } = await profile(points, profileZoom(step, points[0][1]), signal);
	return points.map(([lon, lat], i) => ({ lon, lat, d: d[i], elev: elev[i], slope: slope[i] }));
}
