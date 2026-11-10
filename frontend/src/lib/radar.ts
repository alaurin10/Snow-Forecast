// Precipitation for the map: one timeline from two hours ago to two days ahead, in one
// set of colours for rain, mix/ice and snow by rate.
//
// The server draws every frame (backend/snowwatch/precip.py) as one picture over the
// region around the locations, and lists them in /api/precip. The browser only
// downloads and swaps pictures, so scrubbing is instant and a phone's memory stays low.
// Sources: RainViewer radar (past); Environment Canada's HRDPS (Canada and the northern
// US); NOAA HRRR via Iowa State, or NWS 6-hour totals, for the rest of the US.
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

/** NWS 6-hour totals carry no type: drawn in tan. `from` is inches per 6 hours. */
export const UNTYPED: RampStep[] = [
	{ from: 0.1, color: '#e6d3b3' },
	{ from: 0.25, color: '#d4b083' },
	{ from: 0.5, color: '#b88a50' },
	{ from: 1, color: '#8f612c' }
];

export function untypedColor(inches: number): string | null {
	let c: string | null = null;
	for (const s of UNTYPED) if (inches >= s.from) c = s.color;
	return c;
}

// ---- The frame list ------------------------------------------------------------------

export interface Frame {
	/** Unix seconds: a radar scan's time, or the end of a forecast hour. */
	t: number;
	past: boolean;
	/** Picture file under /api/precip/. */
	file: string;
	/** Where the US forecast outside the Canadian model came from. */
	south: '' | 'hrrr' | 'wpc';
}

/** Forecast snow over a window, from the Canadian model. */
export interface Total {
	/** Window length (12, 24, or up to 48 when the run ends sooner). */
	hours: number;
	/** Unix seconds. */
	start: number;
	end: number;
	file: string;
}

export interface PrecipIndex {
	generated: string;
	/** [[south, west], [north, east]] the pictures cover. */
	bounds: [[number, number], [number, number]];
	width: number;
	height: number;
	frames: Frame[];
	totals?: Total[];
}

export interface Timeline {
	frames: Frame[];
	bounds: PrecipIndex['bounds'];
	/** Picture size in pixels. */
	width: number;
	height: number;
	/** Index of the latest radar frame ("now"), or -1. */
	now: number;
	totals: Total[];
}

/** Turn the server's list into a timeline: in time order, radar before forecast. */
export function toTimeline(ix: PrecipIndex): Timeline {
	const frames = [...(ix.frames ?? [])]
		.filter((f) => typeof f?.t === 'number' && typeof f?.file === 'string')
		.sort((a, b) => a.t - b.t || Number(b.past) - Number(a.past));
	let now = -1;
	frames.forEach((f, i) => f.past && (now = i));
	const totals = (ix.totals ?? [])
		.filter((t) => typeof t?.hours === 'number' && typeof t?.file === 'string')
		.sort((a, b) => a.hours - b.hours);
	return { frames, bounds: ix.bounds, width: ix.width, height: ix.height, now, totals };
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

/** "Sat 2:40 PM" and "20 min ago" for a radar frame; "Sat 5–6 AM" and "in 4 h" ahead. */
export function frameLabel(f: Frame, now = Date.now()): { when: string; rel: string } {
	if (f.past) {
		const d = new Date(f.t * 1000);
		const when = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
		const ago = Math.round((now / 1000 - f.t) / 60);
		if (ago <= 10) return { when, rel: 'radar · now' };
		if (ago < 60) return { when, rel: `radar · ${ago} min ago` };
		const h = Math.floor(ago / 60);
		const m = ago % 60;
		return { when, rel: `radar · ${h} h${m ? ` ${m} min` : ''} ago` };
	}
	const start = new Date((f.t - HOUR) * 1000);
	const end = new Date(f.t * 1000);
	const day = start.toLocaleDateString('en-US', { weekday: 'short' });
	const a = clock(start);
	const b = clock(end);
	// "5–6 AM" when both ends share AM/PM, else "11 AM–12 PM".
	const [aNum, aMer] = a.split(' ');
	const [bNum, bMer] = b.split(' ');
	const span = aMer === bMer ? `${aNum}–${bNum} ${bMer}` : `${a}–${b}`;
	const ahead = Math.round((f.t - HOUR - now / 1000) / HOUR);
	return {
		when: `${day} ${span}`,
		rel: ahead <= 0 ? 'forecast · this hour' : `forecast · in ${ahead} h`
	};
}

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

export function untypedTop(units: UnitSystem): string {
	const inches = UNTYPED[UNTYPED.length - 1].from;
	return units === 'imperial' ? `${tidy(inches)}+ in / 6 h` : `${tidy(inches * 25.4)}+ mm / 6 h`;
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

/** "Sun 10 AM → Tue 4 AM". */
export function totalSpan(t: Total): string {
	const f = (s: number) =>
		new Date(s * 1000)
			.toLocaleString('en-US', { weekday: 'short', hour: 'numeric' })
			.replace(',', '');
	return `${f(t.start)} → ${f(t.end)}`;
}
