// Compare: several locations on one chart. The data side: each location's steps at one
// band, lined up on one timeline; its days for the timeline's bars; and the comparison
// itself (which locations and their colours, band, metric, range), how it travels in a
// URL and how it's kept as a named group. Values stay metric; the page converts them.
import type { BandOut, CompareDay, Snapshot } from './types.gen';
import { buildSteps, niceAxis, STEP, type Range, type Step } from './charts/forecast';
import { converters, elevation, snowNum, speed, type UnitSystem } from './units';
import { dateOf } from './time';

export type CompareMetric = 'snow' | 'temp' | 'wind' | 'cloud' | 'fl' | 'slr';
export const METRICS: readonly CompareMetric[] = ['snow', 'temp', 'wind', 'cloud', 'fl', 'slr'];
export const METRIC_NAMES: Record<CompareMetric, { long: string; short: string }> = {
	snow: { long: 'Snow', short: 'Snow' },
	temp: { long: 'Temperature', short: 'Temp' },
	wind: { long: 'Wind gusts', short: 'Gusts' },
	cloud: { long: 'Cloud cover', short: 'Cloud' },
	fl: { long: 'Freezing level', short: 'Freezing' },
	slr: { long: 'Snow ratio', short: 'Ratio' }
};
export type BandName = 'base' | 'mid' | 'summit';
export const BANDS: readonly BandName[] = ['base', 'mid', 'summit'];
export const COMPARE_RANGES = [1, 3, 5, 10] as const satisfies readonly Range[];
export type CompareRange = (typeof COMPARE_RANGES)[number];

/** Locations in one comparison or group, every one a line on the chart: four is the most
 *  colours that stay distinct on one chart (docs/COMPARE-PLAN.md). */
export const MAX_LOCS = 4;
export const MAX_GROUPS = 20;
export const MAX_NAME = 40;
/** The snow level sits this far below the freezing level (config: snow_level_offset_m). */
export const SNOW_LEVEL_OFFSET_M = 305;
/** The ski-day rating's lift-hold gust (config: skiday.gust_hold_kmh). */
export const LIFT_HOLD_KMH = 70;

export interface Comparison {
	/** The locations, in the comparison's own order. */
	locs: string[];
	/** Colour slots: the index is the line's colour; null is a free colour. Every location
	 *  has one, and keeps it while others come and go. */
	on: (string | null)[];
	band: BandName;
	metric: CompareMetric;
	range: CompareRange;
}

export interface Group extends Comparison {
	name: string;
}

export const emptyComparison = (): Comparison => ({
	locs: [],
	on: [],
	band: 'mid',
	metric: 'snow',
	range: 5
});

// --- Editing a comparison -------------------------------------------------------------

const trim = (on: (string | null)[]) => {
	const out = [...on];
	while (out.length && out[out.length - 1] === null) out.pop();
	return out;
};
const freeSlot = (on: (string | null)[]) => {
	for (let i = 0; i < MAX_LOCS; i++) if (on[i] === null || on[i] === undefined) return i;
	return -1;
};
const place = (on: (string | null)[], i: number, id: string) => {
	const out = [...on];
	while (out.length < i) out.push(null);
	out[i] = id;
	return out;
};

/** The line's colour slot (0–3), or -1 when the location isn't in the comparison. */
export const lineSlot = (c: Comparison, id: string): number => c.on.indexOf(id);

/** Adds a location at the end, in the lowest free colour. */
export function addLocation(c: Comparison, id: string): Comparison {
	if (c.locs.includes(id) || c.locs.length >= MAX_LOCS) return c;
	return { ...c, locs: [...c.locs, id], on: place(c.on, freeSlot(c.on), id) };
}

/** Removes a location; the others keep their colours. */
export function removeLocation(c: Comparison, id: string): Comparison {
	return {
		...c,
		locs: c.locs.filter((x) => x !== id),
		on: trim(c.on.map((x) => (x === id ? null : x)))
	};
}

// --- Checking what comes from a URL or from storage ----------------------------------

const ID = /^[A-Za-z0-9_-]{1,64}$/;

/** A comparison from untrusted parts: bad values fall back, unknown or repeated ids are
 *  dropped, and every location gets a colour. Past four locations (comparisons used to hold
 *  eight, four of them drawn), the ones `on` drew are kept, then the first of the rest. */
export function clean(
	raw: { locs?: unknown; on?: unknown; band?: unknown; metric?: unknown; range?: unknown },
	known?: Set<string>
): Comparison {
	const all: string[] = [];
	for (const id of Array.isArray(raw.locs) ? raw.locs.slice(0, 64) : [])
		if (typeof id === 'string' && ID.test(id) && !all.includes(id) && (!known || known.has(id)))
			all.push(id);
	const onRaw: unknown[] = Array.isArray(raw.on) ? raw.on.slice(0, 8) : [];
	const keep = new Set(all.filter((id) => onRaw.includes(id)).slice(0, MAX_LOCS));
	for (const id of all) if (keep.size < MAX_LOCS) keep.add(id);
	const locs = all.filter((id) => keep.has(id));
	let on: (string | null)[] = [];
	for (const id of onRaw.slice(0, MAX_LOCS))
		on.push(typeof id === 'string' && locs.includes(id) && !on.includes(id) ? id : null);
	for (const id of locs) if (!on.includes(id)) on = place(on, freeSlot(on), id);
	on = trim(on);
	const band = BANDS.includes(raw.band as BandName) ? (raw.band as BandName) : 'mid';
	const metric = METRICS.includes(raw.metric as CompareMetric)
		? (raw.metric as CompareMetric)
		: 'snow';
	const range = (COMPARE_RANGES as readonly number[]).includes(Number(raw.range))
		? (Number(raw.range) as CompareRange)
		: 5;
	return { locs, on, band, metric, range };
}

/** A group's name: trimmed, single spaces, at most 40 characters; null when empty. */
export function cleanName(v: unknown): string | null {
	if (typeof v !== 'string') return null;
	const s = v.replace(/\s+/g, ' ').trim().slice(0, MAX_NAME).trim();
	return s || null;
}

/** The comparison as a query string: `name=…&loc=a,b&on=a,,b&band=…&metric=…&range=…`. */
export function toQuery(c: Comparison, name?: string | null): string {
	const p = new URLSearchParams();
	if (name) p.set('name', name);
	p.set('loc', c.locs.join(','));
	if (c.on.length) p.set('on', c.on.map((x) => x ?? '').join(','));
	p.set('band', c.band);
	p.set('metric', c.metric);
	p.set('range', String(c.range));
	// Commas are safe in a query; keeping them makes a copied link readable.
	return p.toString().replace(/%2C/gi, ',');
}

/** The comparison in a URL, or null when the URL holds none (no `loc`). */
export function fromQuery(
	p: Pick<URLSearchParams, 'has' | 'get'>,
	known?: Set<string>
): { cmp: Comparison; name: string | null } | null {
	if (!p.has('loc')) return null;
	const list = (k: string) => (p.get(k) ?? '').split(',');
	const cmp = clean(
		{
			locs: list('loc').filter(Boolean),
			on: p.has('on') ? list('on').map((x) => x || null) : undefined,
			band: p.get('band'),
			metric: p.get('metric'),
			range: p.get('range')
		},
		known
	);
	return { cmp, name: cleanName(p.get('name')) };
}

// --- Groups ---------------------------------------------------------------------------

const same = (a: string, b: string) => a.toLocaleLowerCase() === b.toLocaleLowerCase();
export const findGroup = (groups: Group[], name: string | null): Group | null =>
	name ? (groups.find((g) => same(g.name, name)) ?? null) : null;

/** Groups as saved in this browser; anything malformed is left out. */
export function readGroups(json: string | null): Group[] {
	if (!json) return [];
	let raw: unknown;
	try {
		raw = JSON.parse(json);
	} catch {
		return [];
	}
	if (!Array.isArray(raw)) return [];
	const out: Group[] = [];
	for (const g of raw) {
		if (!g || typeof g !== 'object') continue;
		const name = cleanName((g as { name?: unknown }).name);
		if (!name || findGroup(out, name)) continue;
		out.push({ name, ...clean(g as Record<string, unknown>) });
		if (out.length >= MAX_GROUPS) break;
	}
	return out;
}

export type GroupError = 'name' | 'exists' | 'full';

/** Saves a comparison as a new group. */
export function addGroup(
	groups: Group[],
	name: string,
	c: Comparison
): { groups: Group[]; error?: GroupError } {
	const n = cleanName(name);
	if (!n) return { groups, error: 'name' };
	if (findGroup(groups, n)) return { groups, error: 'exists' };
	if (groups.length >= MAX_GROUPS) return { groups, error: 'full' };
	return { groups: [...groups, { ...c, name: n }] };
}

/** Keeps an open group's changes (its name stays). */
export function updateGroup(groups: Group[], name: string, c: Comparison): Group[] {
	return groups.map((g) => (same(g.name, name) ? { ...c, name: g.name } : g));
}

export function renameGroup(
	groups: Group[],
	from: string,
	to: string
): { groups: Group[]; name?: string; error?: GroupError } {
	const n = cleanName(to);
	if (!n) return { groups, error: 'name' };
	const clash = findGroup(groups, n);
	if (clash && !same(clash.name, from)) return { groups, error: 'exists' };
	return { groups: groups.map((g) => (same(g.name, from) ? { ...g, name: n } : g)), name: n };
}

/** Removes a group, returning it and its place so it can be put back. */
export function removeGroup(
	groups: Group[],
	name: string
): { groups: Group[]; removed: { group: Group; index: number } | null } {
	const index = groups.findIndex((g) => same(g.name, name));
	if (index < 0) return { groups, removed: null };
	return {
		groups: groups.filter((_, i) => i !== index),
		removed: { group: groups[index], index }
	};
}

/** Puts a removed group back where it was (undo). */
export function restoreGroup(groups: Group[], r: { group: Group; index: number }): Group[] {
	if (findGroup(groups, r.group.name) || groups.length >= MAX_GROUPS) return groups;
	const out = [...groups];
	out.splice(Math.min(r.index, out.length), 0, r.group);
	return out;
}

export function moveGroup(groups: Group[], name: string, by: -1 | 1): Group[] {
	const i = groups.findIndex((g) => same(g.name, name));
	const j = i + by;
	if (i < 0 || j < 0 || j >= groups.length) return groups;
	const out = [...groups];
	[out[i], out[j]] = [out[j], out[i]];
	return out;
}

// --- One timeline for every location -------------------------------------------------

export interface Track {
	id: string;
	name: string;
	band: BandOut;
	generatedAt: string;
	/** The UTC offset of the location's times, e.g. "-08:00". */
	offset: string;
	/** The location's steps on the timeline's slots (null where it has none). */
	steps: (Step | null)[];
}

export interface Timeline {
	/** The location whose steps are the slots: the one on the viewer's clock (or nearest
	 *  it), the freshest forecast among those. */
	ref: Track | null;
	slots: Step[];
	tracks: Track[];
	/** The forecast days, as the reference location's dates (up to 10). */
	dates: string[];
}

export interface LocSnap {
	id: string;
	name: string;
	snap: Snapshot;
}

/** The chosen band, or mid (then the first) when the location lacks it. */
export const pickBand = (snap: Snapshot, band: BandName): BandOut =>
	snap.bands.find((b) => b.band === band) ?? snap.bands[1] ?? snap.bands[0];

const offsetOf = (iso: string | undefined) => (iso && iso.length > 16 ? iso.slice(16) : '');
const centre = (s: Step) => Date.parse(s.t) + (s.hours * 3600e3) / 2;

/**
 * A location's steps placed on the timeline's slots. Day and night halves (12 h steps) go
 * by the location's own date and half, so "Saturday" is Saturday where the mountain is.
 * Shorter steps go by time: each slot takes the step whose middle is nearest its own,
 * within half a step, so places an hour apart still line up step for step.
 */
export function align(slots: Step[], steps: Step[]): (Step | null)[] {
	if (!slots.length) return [];
	if (slots[0].hours === 12) {
		const key = (s: Step) => `${dateOf(s.t)}${s.night ? 'n' : 'd'}`;
		const by = new Map(steps.map((s) => [key(s), s]));
		return slots.map((s) => by.get(key(s)) ?? null);
	}
	const half = (slots[0].hours * 3600e3) / 2;
	let j = 0;
	return slots.map((s) => {
		const c = centre(s);
		while (
			j + 1 < steps.length &&
			Math.abs(centre(steps[j + 1]) - c) <= Math.abs(centre(steps[j]) - c)
		)
			j++;
		const st = steps[j];
		return st && Math.abs(centre(st) - c) < half ? st : null;
	});
}

/** Minutes east of UTC from a "-08:00" style offset (null when there's none). */
const offsetMin = (o: string): number | null => {
	const m = /^([+-])(\d\d):(\d\d)$/.exec(o);
	return m ? (m[1] === '-' ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3])) : null;
};

/** The viewer's clock now, in minutes east of UTC. */
export const viewerOffset = (): number => -new Date().getTimezoneOffset();

/**
 * Every location's steps at one band, lined up on one location's steps: the one whose
 * clock is the viewer's (`viewerMin`, minutes east of UTC), or nearest it, so times read
 * as the viewer's own; the freshest forecast among equals. Without `viewerMin`, the
 * freshest forecast.
 */
export function buildTimeline(
	locs: LocSnap[],
	band: BandName,
	range: Range,
	viewerMin?: number
): Timeline {
	const tracks0 = locs
		.filter((l) => l.snap.bands?.length)
		.map((l) => {
			const b = pickBand(l.snap, band);
			return {
				id: l.id,
				name: l.name,
				band: b,
				generatedAt: l.snap.generated_at,
				offset: offsetOf(b.hourly.t[0]),
				own: buildSteps(b.hourly, range, true)
			};
		});
	if (!tracks0.length) return { ref: null, slots: [], tracks: [], dates: [] };
	const away = (o: string) => {
		const m = offsetMin(o);
		return viewerMin === undefined ? 0 : m === null ? Infinity : Math.abs(m - viewerMin);
	};
	let r = 0;
	tracks0.forEach((t, i) => {
		const d = away(t.offset) - away(tracks0[r].offset);
		if (d < 0 || (d === 0 && Date.parse(t.generatedAt) > Date.parse(tracks0[r].generatedAt))) r = i;
	});
	const slots = tracks0[r].own;
	const tracks: Track[] = tracks0.map(({ own, ...t }, i) => ({
		...t,
		steps: i === r ? own : align(slots, own)
	}));
	const refBand = tracks[r].band;
	const dates = [...new Set(refBand.periods.map((p) => p.date))]
		.filter((d) => refBand.hourly.t.some((x) => dateOf(x) === d))
		.slice(0, 10);
	return { ref: tracks[r], slots, tracks, dates };
}

/** The value a metric draws for one step (metric units); snow is the running total. */
export function stepValue(st: Step | null | undefined, metric: CompareMetric): number | null {
	if (!st) return null;
	if (metric === 'snow') return st.cum;
	if (metric === 'temp') return st.temp;
	if (metric === 'wind') return st.gust;
	if (metric === 'cloud') return st.cloud;
	if (metric === 'fl') return st.fl;
	return st.slr;
}

// --- What the chart draws (shared by the page and its share image) ---------------------

/** The locations drawn as lines: each line colour holding a loaded location. */
export function chartLines(t: Timeline, c: Comparison): { slot: number; track: Track }[] {
	return c.on.flatMap((id, slot) => {
		const track = id ? t.tracks.find((x) => x.id === id) : undefined;
		return track ? [{ slot, track }] : [];
	});
}

/** A metric value in display units. */
export function shown(v: number | null, metric: CompareMetric, units: UnitSystem): number | null {
	if (v === null) return null;
	const c = converters(units);
	if (metric === 'snow') return c.snow(v);
	if (metric === 'temp') return c.temp(v);
	if (metric === 'wind') return c.speed(v);
	if (metric === 'fl') return c.height(v);
	return v;
}

/** How snow totals run: from now (the forecast's running total, so a line keeps its place
 *  as the window moves) or from the window's first step. */
export type SnowTotal = 'run' | 'window';

/** A location's values across the window, in display units. Snow is a running total from
 *  now, or from the window's first step (then a line ends at its total for the window). */
export function lineValues(
	track: Track,
	metric: CompareMetric,
	w: Win,
	units: UnitSystem,
	total: SnowTotal = 'run'
): (number | null)[] {
	const inView = track.steps.slice(w.off, w.off + w.n);
	if (metric !== 'snow') return inView.map((st) => shown(stepValue(st, metric), metric, units));
	if (total === 'window') return windowTotals(inView).map((v) => shown(v, metric, units));
	return inView.map((st) => (st ? shown(st.cum, metric, units) : null));
}

/** The chart's scale for the whole forecast (not just the window), so lines keep their
 *  heights as the window moves (freezing level also takes in each location's elevation). */
export function chartAxis(
	tracks: Track[],
	metric: CompareMetric,
	w: Win,
	units: UnitSystem,
	total: SnowTotal = 'run'
): { min: number; max: number; ticks: number[] } {
	const c = converters(units);
	if (metric === 'snow') {
		// From now: the most any location has by the forecast's end. From the window's
		// start: the snowiest window anywhere.
		const most = tracks.map(
			(t) =>
				c.snow(
					total === 'run'
						? Math.max(0, ...t.steps.map((st) => st?.cum ?? 0))
						: maxWindowTotal(t.steps, w.n)
				) ?? 0
		);
		return niceAxis(0, Math.max(units === 'imperial' ? 1 : 2, ...most), 4);
	}
	const vals = tracks
		.flatMap((t) => t.steps.map((st) => shown(stepValue(st, metric), metric, units)))
		.filter((v): v is number => v !== null);
	if (metric === 'temp')
		return niceAxis(Math.min(c.freezing, ...vals) - 2, Math.max(c.freezing, ...vals) + 2, 4);
	if (metric === 'wind') return niceAxis(0, Math.max(10, ...vals), 4);
	if (metric === 'fl') {
		const all = [...vals, ...tracks.map((t) => c.height(t.band.elev_m) ?? 0)];
		if (!all.length) return niceAxis(0, units === 'imperial' ? 10000 : 3000, 4);
		return niceAxis(Math.min(...all) * 0.9, Math.max(...all) * 1.05, 4);
	}
	if (metric === 'slr') return { min: 4, max: 20, ticks: [5, 8, 11, 14, 17, 20] };
	return { min: 0, max: 100, ticks: [0, 25, 50, 75, 100] };
}

/** The axis' tick labels. */
export function tickText(v: number, metric: CompareMetric, units: UnitSystem): string {
	if (metric === 'temp') return `${v}°`;
	if (metric === 'slr') return `${v}:1`;
	if (metric === 'cloud') return `${v}%`;
	if (metric === 'fl')
		return units === 'imperial'
			? `${(v / 1000).toLocaleString('en-US')}k ft`
			: `${v.toLocaleString('en-US')} m`;
	return `${v}`;
}

/** A location's summary for the window, in words: the snow total, the high and low, the
 *  top gust, the lowest freezing level, the mean ratio while snowing, the mean cloud.
 *  `bare` leaves the unit off where a heading gives it. */
export function summaryText(
	s: Summary | null,
	metric: CompareMetric,
	units: UnitSystem,
	bare = false
): string {
	if (!s) return '';
	const c = converters(units);
	const round = (v: number | null) => (v === null ? null : Math.round(v));
	if (metric === 'snow')
		return bare ? snowNum(s.snow, units) : `${snowNum(s.snow, units)} ${c.snowUnit}`;
	if (metric === 'temp') {
		const hi = round(c.temp(s.tmax));
		const lo = round(c.temp(s.tmin));
		return hi === null || lo === null ? '–' : `${hi}°/${lo}°`;
	}
	if (metric === 'wind')
		return s.gust === null ? '–' : bare ? `${round(c.speed(s.gust))}` : speed(s.gust, units);
	if (metric === 'fl') {
		if (s.flMin === null) return '–';
		if (!bare) return elevation(s.flMin, units);
		const v = c.height(s.flMin) ?? 0;
		return (Math.round(v / 10) * 10).toLocaleString('en-US');
	}
	if (metric === 'slr') return s.slr === null ? '–' : `${Math.round(s.slr)}:1`;
	return s.cloud === null ? '–' : `${Math.round(s.cloud)}%`;
}

/** Hours that a location's clock is ahead of the reference's (from "-07:00" style offsets). */
export function hoursAhead(offset: string, ref: string): number {
	const mins = (o: string) => {
		const m = /^([+-])(\d\d):(\d\d)$/.exec(o);
		return m ? (m[1] === '-' ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3])) : 0;
	};
	return (mins(offset) - mins(ref)) / 60;
}

// --- The window the chart shows ---------------------------------------------------------

export interface Win {
	off: number;
	n: number;
	maxOff: number;
}

/** The slots in view: `range` days from `startMs` (now when null), kept inside the data. */
export function windowFor(slots: Step[], range: Range, startMs: number | null): Win {
	const n = Math.min((range * 24) / STEP[range], slots.length);
	const maxOff = Math.max(0, slots.length - n);
	if (startMs === null) return { off: 0, n, maxOff };
	const k = slots.findIndex((s) => Date.parse(s.t) >= startMs);
	return { off: k < 0 ? maxOff : Math.min(maxOff, k), n, maxOff };
}

/** The days the window touches, as indexes into `dates` (first and last). */
export function windowDays(slots: Step[], w: Win, dates: string[]): { from: number; to: number } {
	const inView = slots.slice(w.off, w.off + w.n).map((s) => dates.indexOf(dateOf(s.t)));
	const ks = inView.filter((k) => k >= 0);
	if (!ks.length) return { from: 0, to: Math.max(0, dates.length - 1) };
	return { from: Math.min(...ks), to: Math.max(...ks) };
}

/** Where each forecast day starts (ms) on the timeline: now for the first, then the first
 *  hour of each later date (midnight) in the reference location's times. */
export function dayStarts(t: string[], dates: string[]): number[] {
	return dates.map((d, k) => {
		if (k === 0) return t.length ? Date.parse(t[0]) : 0;
		const i = t.findIndex((x) => dateOf(x) === d);
		return i < 0 ? NaN : Date.parse(t[i]);
	});
}

/** The window as a stretch of the timeline, in days from its left edge (fractions where it
 *  starts or ends inside a day), as the forecast page's timeline draws it. At either end of
 *  the data it meets the edge, as steps of 6 or 12 h start a little after now. */
export function windowSpan(slots: Step[], w: Win, starts: number[]): { from: number; to: number } {
	const n = starts.length;
	if (!slots.length || !n || w.n < 1) return { from: 0, to: n };
	const pos = (ms: number) => {
		if (ms <= starts[0]) return 0;
		for (let k = 0; k < n; k++) {
			const s0 = starts[k];
			const s1 = k + 1 < n ? starts[k + 1] : s0 + 24 * 3600e3;
			if (ms < s1) return k + (ms - s0) / (s1 - s0);
		}
		return n;
	};
	const last = slots[w.off + w.n - 1];
	return {
		from: w.off === 0 ? 0 : pos(Date.parse(slots[w.off].t)),
		to: w.off >= w.maxOff ? n : pos(Date.parse(last.t) + last.hours * 3600e3)
	};
}

/** Where a window starting on day `k` begins: now for the first day, else its first slot. */
export function dayStart(slots: Step[], dates: string[], k: number): number | null {
	if (k <= 0) return null;
	const d = dates[Math.min(k, dates.length - 1)];
	const s = slots.find((x) => dateOf(x.t) === d);
	return s ? Date.parse(s.t) : null;
}

// --- Days, for the location rows ------------------------------------------------------

export interface DayCell {
	date: string;
	/** False when the location has no forecast for this date. */
	has: boolean;
	snow: number;
	rain: number;
	tmax: number | null;
	tmin: number | null;
	gust: number | null;
	flMin: number | null;
	slr: number | null;
	cloud: number | null;
}

const nums = (xs: (number | null | undefined)[]) =>
	xs.filter((v): v is number => v !== null && v !== undefined && Number.isFinite(v));
const meanOf = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

/** A location's days at one band (its own calendar dates; a night goes with its evening). */
export function dayCells(band: BandOut, dates: string[]): DayCell[] {
	return dates.map((date) => {
		const ps = band.periods.filter((p) => p.date === date);
		const fl = nums(band.hourly.t.map((t, i) => (dateOf(t) === date ? band.hourly.fl_m[i] : null)));
		const tmax = nums(ps.map((p) => p.tmax_c));
		const tmin = nums(ps.map((p) => p.tmin_c));
		const gust = nums(ps.map((p) => p.gust_max_kmh));
		return {
			date,
			has: ps.length > 0,
			snow: ps.reduce((a, p) => a + (p.snow_cm ?? 0), 0),
			rain: ps.reduce((a, p) => a + (p.rain_mm ?? 0), 0),
			tmax: tmax.length ? Math.max(...tmax) : null,
			tmin: tmin.length ? Math.min(...tmin) : null,
			gust: gust.length ? Math.max(...gust) : null,
			flMin: fl.length ? Math.min(...fl) : null,
			slr: meanOf(nums(ps.map((p) => p.slr))),
			cloud: meanOf(nums(ps.map((p) => p.cloud_mean)))
		};
	});
}

export interface Summary {
	/** Snow (cm) and rain (mm) over the window. */
	snow: number;
	rain: number;
	tmax: number | null;
	tmin: number | null;
	gust: number | null;
	flMin: number | null;
	/** Mean ratio over the steps that snow. */
	slr: number | null;
	cloud: number | null;
}

/** The summary column, from the very steps the chart draws in its window, so a row's
 *  total and its line's end always agree. */
export function summarizeSteps(steps: (Step | null | undefined)[]): Summary {
	const ok = steps.filter((s): s is Step => !!s);
	const temps = nums(ok.map((s) => s.temp));
	const gust = nums(ok.map((s) => s.gust));
	const fl = nums(ok.map((s) => s.fl));
	return {
		snow: ok.reduce((a, s) => a + s.snow, 0),
		rain: ok.reduce((a, s) => a + s.rain * 10, 0),
		tmax: temps.length ? Math.max(...temps) : null,
		tmin: temps.length ? Math.min(...temps) : null,
		gust: gust.length ? Math.max(...gust) : null,
		flMin: fl.length ? Math.min(...fl) : null,
		slr: meanOf(nums(ok.filter((s) => s.snow > 0.05).map((s) => s.slr))),
		cloud: meanOf(nums(ok.map((s) => s.cloud)))
	};
}

/** Snow (cm) as a running total from the window's first step (null where a step is missing). */
export function windowTotals(steps: (Step | null | undefined)[]): (number | null)[] {
	let run = 0;
	return steps.map((s) => {
		if (!s) return null;
		run += s.snow;
		return run;
	});
}

/** The most snow any `n` steps in a row add up to: the snow scale, so lines keep their
 *  heights as the window moves. */
export function maxWindowTotal(steps: (Step | null)[], n: number): number {
	const pre = [0];
	for (const s of steps) pre.push(pre[pre.length - 1] + (s?.snow ?? 0));
	let best = 0;
	for (let k = 0; k + n <= steps.length; k++) best = Math.max(best, pre[k + n] - pre[k]);
	if (steps.length < n) best = pre[pre.length - 1];
	return best;
}

/**
 * The freezing level against a location's elevation: how far above or below it is, and
 * what that means for snow there (the snow level is 305 m below the freezing level).
 */
export function fzSide(
	fl: number | null | undefined,
	elev: number
): { diff: number; word: 'snow' | 'wet' | 'warm' } | null {
	if (fl === null || fl === undefined) return null;
	const diff = fl - elev;
	return { diff, word: diff <= 0 ? 'snow' : diff <= SNOW_LEVEL_OFFSET_M ? 'wet' : 'warm' };
}

// --- Ranking every location (the Add list) -------------------------------------------

/** How the Add list ranks locations for each metric, best first. */
export const RANK: Record<CompareMetric, { label: string; better: 'high' | 'low' }> = {
	snow: { label: 'Most snow', better: 'high' },
	temp: { label: 'Coldest', better: 'low' },
	wind: { label: 'Lightest wind', better: 'low' },
	cloud: { label: 'Clearest', better: 'low' },
	fl: { label: 'Lowest freezing level', better: 'low' },
	slr: { label: 'Driest snow', better: 'high' }
};

/** A location's summary from the server's days: over `dates` when given, else its first
 *  five days. */
export function daysSummary(days: CompareDay[], dates: string[] | null): Summary {
	const inRange = dates ? days.filter((d) => dates.includes(d.date)) : days.slice(0, 5);
	const pick = (f: (d: CompareDay) => number | null) => nums(inRange.map(f));
	const tmax = pick((d) => d.tmax_c);
	const tmin = pick((d) => d.tmin_c);
	const gust = pick((d) => d.gust_kmh);
	const fl = pick((d) => d.fl_min_m);
	return {
		snow: inRange.reduce((a, d) => a + d.snow_cm, 0),
		rain: inRange.reduce((a, d) => a + d.rain_mm, 0),
		tmax: tmax.length ? Math.max(...tmax) : null,
		tmin: tmin.length ? Math.min(...tmin) : null,
		gust: gust.length ? Math.max(...gust) : null,
		flMin: fl.length ? Math.min(...fl) : null,
		slr: meanOf(pick((d) => d.slr)),
		cloud: meanOf(pick((d) => d.cloud))
	};
}

/** The number a metric ranks by (null sorts last). */
export function rankValue(s: Summary | null, metric: CompareMetric): number | null {
	if (!s) return null;
	if (metric === 'snow') return s.snow;
	if (metric === 'temp') return s.tmax;
	if (metric === 'wind') return s.gust;
	if (metric === 'cloud') return s.cloud;
	if (metric === 'fl') return s.flMin;
	return s.slr;
}

/** Best first for the metric; ties and missing values keep their order. */
export function rankOrder<T>(
	items: T[],
	value: (it: T) => number | null,
	metric: CompareMetric
): T[] {
	const dir = RANK[metric].better === 'high' ? -1 : 1;
	return items
		.map((it, i) => ({ it, i, v: value(it) }))
		.sort((a, b) => {
			if (a.v === null || b.v === null) return a.v === null ? (b.v === null ? a.i - b.i : 1) : -1;
			return (a.v - b.v) * dir || a.i - b.i;
		})
		.map((x) => x.it);
}
