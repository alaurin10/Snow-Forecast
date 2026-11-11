// Precipitation for the map: one timeline from three hours ago to ten days ahead, in one
// set of colours for rain, mix/ice and snow by rate.
//
// The server draws every frame (backend/snowwatch/maps/) as one picture over western
// North America, and lists them in /api/precip. The browser only downloads and swaps
// pictures, so scrubbing is instant and a phone's memory stays low.
// Sources: Environment Canada's North American radar composite (past 3 h, typed) and its
// nowcast (next 72 min); hourly to ~48 h, Environment Canada's HRDPS (Canada and the
// northern US) and NOAA HRRR for the rest of the US; then 3-hourly to ~84 h (Canadian
// RDPS) and 6-hourly to 10 days (Canadian GDPS) in Canada, with NOAA's National Blend in
// the US. The server blends the sources as numbers, so there are no joins to see.
import type { UnitSystem } from './units';

const HOUR = 3600;

// ---- Colours (the backend draws with the same ones: keep them in step) ------------------

export type PrecipKind = 'snow' | 'mix' | 'rain';

export interface RampStep {
	/** Lower bound, mm of water per hour (cm of snow per hour for snow). */
	from: number;
	color: string;
}

export interface Ramp {
	kind: PrecipKind;
	label: string;
	steps: RampStep[];
}

/**
 * Snow amounts are per hour: at a typical 10:1 ratio, 1 mm of water is about 1 cm of
 * snow, so the model's water equivalent and the radar's snow rate share one ramp.
 */
export const RAMPS: Record<PrecipKind, Ramp> = {
	snow: {
		kind: 'snow',
		label: 'Snow',
		steps: [
			{ from: 0.1, color: '#c6dbef' },
			{ from: 0.5, color: '#8fbfe6' },
			{ from: 1, color: '#4a90d9' },
			{ from: 2, color: '#2c5fb8' },
			{ from: 3, color: '#6a3fb0' }
		]
	},
	mix: {
		kind: 'mix',
		label: 'Mix / ice',
		steps: [
			{ from: 0.1, color: '#f4a6c6' },
			{ from: 1, color: '#e0457b' }
		]
	},
	rain: {
		kind: 'rain',
		label: 'Rain',
		steps: [
			{ from: 0.1, color: '#a6dba0' },
			{ from: 0.5, color: '#5aae61' },
			{ from: 1, color: '#1b7837' },
			{ from: 2.5, color: '#f4d03f' },
			{ from: 5, color: '#ee8a2a' },
			{ from: 10, color: '#d7301f' }
		]
	}
};

// ---- The frame list ------------------------------------------------------------------

/** Observed radar, the radar nowcast (echoes moved forward), or a model forecast. */
export type FrameKind = 'radar' | 'nowcast' | 'forecast';

export interface Frame {
	/** Unix seconds: a radar scan's time, a nowcast's time, or the end of a forecast span. */
	t: number;
	/** True for observed radar. */
	past: boolean;
	/** Picture file under /api/precip/. */
	file: string;
	/** Where the US forecast came from: "hrrr", "nbm", or "" (none, or radar). */
	south: string;
	kind: FrameKind;
	/**
	 * Hours the amount covers: 1 for hourly forecast frames, 3 and 6 beyond two days (shown
	 * as the average hourly rate), 0 for a rate at an instant (radar, nowcast).
	 */
	span_h: number;
	/**
	 * The sources blended into the frame: the main one for Canada (`north`) and for the US
	 * (`south`), e.g. "hrdps", "nbm", and one filling in where neither reaches (`fill`).
	 */
	src: { north?: string; south?: string; fill?: string };
}

/** Forecast snow over a window: Canada's models north of 49°N, NOAA's blend south of it. */
export interface Total {
	/** The window's actual length in hours (shorter than `window` if the models stop sooner). */
	hours: number;
	/** The window asked for, in hours: 12, 24, 48, 72, 120, 168 or 240. */
	window: number;
	/** Unix seconds. */
	start: number;
	end: number;
	file: string;
	/** The models used, joined by "+" ("hrdps+rdps+gdps+nbm"). */
	source?: string;
	/** Each model used → when its run began (Unix seconds). */
	runs?: Record<string, number>;
}

/** The index as the server writes it. Version 1 frames lack `kind`, `span_h` and `src`. */
export interface PrecipIndex {
	version?: number;
	generated: string;
	/** [[south, west], [north, east]] the pictures cover. */
	bounds: [[number, number], [number, number]];
	width: number;
	height: number;
	frames: (Pick<Frame, 't' | 'past' | 'file' | 'south'> & Partial<Frame>)[];
	/** `window` arrived with the 10-day totals; older indexes have only `hours`. */
	totals?: (Omit<Total, 'window'> & { window?: number })[];
	/** Credit lines for the sources in use. */
	attribution?: string[];
}

export interface Timeline {
	frames: Frame[];
	bounds: PrecipIndex['bounds'];
	/** Picture size in pixels. */
	width: number;
	height: number;
	/** Index of the latest radar frame ("now"), or -1. */
	now: number;
	/** Index of the last nowcast frame, or -1. */
	nowcastEnd: number;
	/** Index of the first 3- or 6-hour frame (beyond ~48 h, loaded on demand), or -1. */
	extendedFrom: number;
	totals: Total[];
	attribution: string[];
}

const ORDER: Record<FrameKind, number> = { radar: 0, nowcast: 1, forecast: 2 };

/** Turn the server's list into a timeline: in time order, radar, then nowcast, then forecast. */
export function toTimeline(ix: PrecipIndex): Timeline {
	const frames: Frame[] = [...(ix.frames ?? [])]
		.filter((f) => typeof f?.t === 'number' && typeof f?.file === 'string')
		.map((f) => {
			const kind: FrameKind =
				f.kind === 'radar' || f.kind === 'nowcast' || f.kind === 'forecast'
					? f.kind
					: f.past
						? 'radar'
						: 'forecast';
			return {
				...f,
				kind,
				past: kind === 'radar',
				span_h: typeof f.span_h === 'number' ? f.span_h : kind === 'forecast' ? 1 : 0,
				src: f.src ?? {}
			};
		})
		.sort((a, b) => a.t - b.t || ORDER[a.kind] - ORDER[b.kind]);
	let now = -1;
	let nowcastEnd = -1;
	let extendedFrom = -1;
	frames.forEach((f, i) => {
		if (f.kind === 'radar') now = i;
		if (f.kind === 'nowcast') nowcastEnd = i;
		if (f.kind === 'forecast' && f.span_h > 1 && extendedFrom < 0) extendedFrom = i;
	});
	const totals: Total[] = (ix.totals ?? [])
		.filter((t) => typeof t?.hours === 'number' && typeof t?.file === 'string')
		.map((t) => ({
			...t,
			window: typeof t.window === 'number' && t.window > 0 ? t.window : t.hours
		}))
		.sort((a, b) => a.window - b.window);
	return {
		frames,
		bounds: ix.bounds,
		width: ix.width,
		height: ix.height,
		now,
		nowcastEnd,
		extendedFrom,
		totals,
		attribution: Array.isArray(ix.attribution) ? ix.attribution : []
	};
}

/** Why the timeline isn't available, in words for the map. */
export class PrecipError extends Error {
	constructor(
		readonly kind: 'building' | 'offline' | 'server',
		message: string
	) {
		super(message);
	}
}

export async function loadTimeline(): Promise<Timeline> {
	let res: Response;
	try {
		res = await fetch('/api/precip', { cache: 'no-cache' });
	} catch {
		throw new PrecipError('offline', "Can't reach Snow Watch right now.");
	}
	if (res.status === 503) {
		// The server says the frames aren't drawn yet; the offline cache says "offline".
		const detail = await res
			.json()
			.then((j: { detail?: string }) => j.detail ?? '')
			.catch(() => '');
		if (detail === 'offline') throw new PrecipError('offline', "Can't reach Snow Watch right now.");
		throw new PrecipError(
			'building',
			'The server is still drawing the precipitation frames (about a minute and a half after an update).'
		);
	}
	if (!res.ok) {
		throw new PrecipError(
			'server',
			`Precipitation is unavailable (server answered ${res.status}).`
		);
	}
	const tl = toTimeline((await res.json()) as PrecipIndex);
	if (!tl.frames.length) {
		throw new PrecipError(
			'building',
			"The server hasn't drawn any precipitation frames yet: it may not reach the weather sources."
		);
	}
	return tl;
}

export const frameUrl = (f: { file: string }) => `/api/precip/${f.file}`;

// ---- Labels ------------------------------------------------------------------

const clock = (d: Date) =>
	d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).replace(':00', '');

/** "in 4 h" up to two days ahead, then "in 3 days". */
function aheadText(hours: number): string {
	if (hours < 48) return `in ${hours} h`;
	return `in ${Math.round(hours / 24)} days`;
}

/**
 * "2:40 PM" and "radar · 20 min ago" for a radar frame, "3:04 PM" and "nowcast · in 24 min"
 * for a nowcast, "Sat 5–6 AM" and "forecast · in 4 h" ahead, and beyond two days
 * "Fri 4–10 AM" and "6-hour average · in 3 days".
 */
export function frameLabel(f: Frame, now = Date.now()): { when: string; rel: string } {
	if (f.kind === 'nowcast') {
		const when = new Date(f.t * 1000).toLocaleTimeString('en-US', {
			hour: 'numeric',
			minute: '2-digit'
		});
		const ahead = Math.round((f.t - now / 1000) / 60);
		return { when, rel: ahead <= 0 ? 'nowcast · now' : `nowcast · in ${ahead} min` };
	}
	if (f.kind === 'radar') {
		const d = new Date(f.t * 1000);
		const when = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
		const ago = Math.round((now / 1000 - f.t) / 60);
		if (ago <= 10) return { when, rel: 'radar · now' };
		if (ago < 60) return { when, rel: `radar · ${ago} min ago` };
		const h = Math.floor(ago / 60);
		const m = ago % 60;
		return { when, rel: `radar · ${h} h${m ? ` ${m} min` : ''} ago` };
	}
	const span = (f.span_h || 1) * HOUR;
	const start = new Date((f.t - span) * 1000);
	const end = new Date(f.t * 1000);
	const day = start.toLocaleDateString('en-US', { weekday: 'short' });
	const a = clock(start);
	const b = clock(end);
	// "5–6 AM" when both ends share AM/PM, else "11 AM–12 PM".
	const [aNum, aMer] = a.split(' ');
	const [bNum, bMer] = b.split(' ');
	const range = aMer === bMer ? `${aNum}–${bNum} ${bMer}` : `${a}–${b}`;
	const ahead = Math.round((f.t - span - now / 1000) / HOUR);
	if (f.span_h > 1) {
		return {
			when: `${day} ${range}`,
			rel: `${f.span_h}-hour average${ahead > 0 ? ` · ${aheadText(ahead)}` : ''}`
		};
	}
	return {
		when: `${day} ${range}`,
		rel: ahead <= 0 ? 'forecast · this hour' : `forecast · ${aheadText(ahead)}`
	};
}

/** Model names for the sources the server lists. */
const MODEL_NAMES: Record<string, string> = {
	hrdps: 'Canadian HRDPS',
	rdps: 'Canadian RDPS',
	gdps: 'Canadian GDPS',
	hrrr: 'NOAA HRRR',
	nbm: "NOAA's National Blend of Models"
};

const modelName = (s: string | undefined) => (s && MODEL_NAMES[s]) || s || '';

/** Where a frame came from, in a sentence for the map's info panel. */
export function frameSource(f: Frame): string {
	if (f.kind === 'radar') {
		return f.src.north === 'rainviewer'
			? 'Observed by radar (RainViewer).'
			: "Observed by radar: Environment Canada's North American composite, which includes the US radars.";
	}
	if (f.kind === 'nowcast') {
		return 'Nowcast: the latest radar echoes moved forward by Environment Canada, without growth or decay.';
	}
	const north = f.src.north || 'hrdps';
	const south = f.src.south ?? f.south;
	if (f.span_h > 1) {
		const avg = `Forecast, ${f.span_h}-hour average`;
		if (!south || south === north) return `${avg}: ${modelName(north)} model.`;
		return `${avg}: ${modelName(north)} model in Canada, ${modelName(south)} in the US, blended across the border.`;
	}
	if (!south) return `Forecast: ${modelName(north)} model where it reaches.`;
	const beyond = f.src.fill ? `${modelName(south)} and ${modelName(f.src.fill)}` : modelName(south);
	return `Forecast: ${modelName(north)} model where it reaches (Canada and the northern US), ${beyond} beyond, blended where they meet.`;
}

/** Shown with radar and nowcast frames. */
export const RADAR_GAPS = "Radar can't see into many mountain valleys.";

// ---- Legend ------------------------------------------------------------------

/** "0.4", "3" or "0.04": short, for the legend. */
const tidy = (n: number) => String(Number(n.toFixed(n < 0.1 ? 2 : 1)));

/** The amount at the top step of a ramp, as "3+ cm/h" or "1.2+ in/h". */
export function rampTop(ramp: Ramp, units: UnitSystem): string {
	const mm = ramp.steps[ramp.steps.length - 1].from;
	if (ramp.kind === 'snow') {
		return units === 'imperial' ? `${tidy(mm / 2.54)}+ in/h` : `${tidy(mm)}+ cm/h`;
	}
	return units === 'imperial' ? `${tidy(mm / 25.4)}+ in/h` : `${tidy(mm)}+ mm/h`;
}

// ---- Snowfall totals ------------------------------------------------------------------

/** Lower bound in cm of snow; on whole inches (1, 3, 6, 9, 12, 18, 24, 36, 48). */
export const TOTAL: RampStep[] = [
	{ from: 2.54, color: '#cfe8f8' },
	{ from: 7.62, color: '#8cc8ef' },
	{ from: 15.24, color: '#4a98e0' },
	{ from: 22.86, color: '#2b5cc2' },
	{ from: 30.48, color: '#6a3fb0' },
	{ from: 45.72, color: '#a535a3' },
	{ from: 60.96, color: '#e0457b' },
	{ from: 91.44, color: '#f08a24' },
	{ from: 121.92, color: '#f4d03f' }
];

/** Legend tick for a TOTAL step: "6" (inches) or "15" (cm). */
export function totalTick(cm: number, units: UnitSystem): string {
	return units === 'imperial' ? String(Math.round(cm / 2.54)) : String(Math.round(cm));
}

/** A window's button: "12 h", "48 h", "3 days", "10 days". */
export function totalLabel(t: Pick<Total, 'window'>): string {
	return t.window <= 48 ? `${t.window} h` : `${Math.round(t.window / 24)} days`;
}

/** "Next 12 hours", "Next 3 days": the button's accessible name. */
export function totalName(t: Pick<Total, 'window'>): string {
	return t.window <= 48 ? `Next ${t.window} hours` : `Next ${Math.round(t.window / 24)} days`;
}

const runClock = (s: number) =>
	new Date(s * 1000)
		.toLocaleString('en-US', { weekday: 'short', hour: 'numeric' })
		.replace(',', '');

/**
 * The models behind a total and when each run began:
 * "Canada: HRDPS (Tue 4 AM), RDPS (Tue 4 AM), GDPS (Mon 4 PM). US: NOAA National Blend (Tue 4 AM)."
 */
export function totalSources(t: Total): string {
	const runs = t.runs ?? {};
	const names = Object.keys(runs).length
		? Object.keys(runs)
		: (t.source ?? 'hrdps').split('+').filter(Boolean);
	const at = (m: string) => (runs[m] ? ` (${runClock(runs[m])})` : '');
	const north = names.filter((m) => m !== 'nbm');
	const parts: string[] = [];
	if (north.length)
		parts.push(`Canada: ${north.map((m) => `${m.toUpperCase()}${at(m)}`).join(', ')}.`);
	if (names.includes('nbm')) parts.push(`US: NOAA National Blend${at('nbm')}.`);
	return parts.join(' ');
}

/** "Sun 10 AM → Tue 4 AM". */
export function totalSpan(t: Total): string {
	const f = (s: number) =>
		new Date(s * 1000)
			.toLocaleString('en-US', { weekday: 'short', hour: 'numeric' })
			.replace(',', '');
	return `${f(t.start)} → ${f(t.end)}`;
}
