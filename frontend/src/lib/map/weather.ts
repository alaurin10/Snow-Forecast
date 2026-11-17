// The map's one weather layer: what it shows, and how its controls work.
//
// Radar & forecast, snow level, wind and clouds are loops (a slider through frames);
// snow totals, snow on the ground and observed snowfall are pictures picked by window.
// The server draws every picture (backend/snowwatch/maps/layers.py) and lists them in the
// same index as the precipitation frames (../radar.ts).
import type { MapWeather, MapWind } from '../prefs.svelte';
import {
	totalLabel,
	totalName,
	totalSources,
	totalSpan,
	type Frame,
	type LayerFrame,
	type RampStep,
	type Timeline
} from '../radar';
import { kmhToMph, mToFt, type UnitSystem } from '../units';

const HOUR = 3600;

// ---- Colours (the backend draws with the same ones: keep them in step with palette.py) --

/** Snow level, lower bound in metres above sea level, a band every 250 m. */
export const SNOWLEVEL: RampStep[] = [
	{ from: 0, color: '#5b2a86' },
	{ from: 250, color: '#6b44b5' },
	{ from: 500, color: '#4e5fc9' },
	{ from: 750, color: '#3b7dd8' },
	{ from: 1000, color: '#2f9be0' },
	{ from: 1250, color: '#33b4d6' },
	{ from: 1500, color: '#3fc6b8' },
	{ from: 1750, color: '#5ed19a' },
	{ from: 2000, color: '#8fd97a' },
	{ from: 2250, color: '#bfe06a' },
	{ from: 2500, color: '#e6e35c' },
	{ from: 2750, color: '#f6cf4f' },
	{ from: 3000, color: '#f7ad45' },
	{ from: 3250, color: '#f28a3b' },
	{ from: 3500, color: '#e5653a' },
	{ from: 3750, color: '#cf4339' },
	{ from: 4000, color: '#a82f3a' }
];

/** Wind (gusts, or the ridge-level wind), lower bound in km/h; clear below 20. */
export const WIND: RampStep[] = [
	{ from: 20, color: '#d9f0d3' },
	{ from: 30, color: '#acdca5' },
	{ from: 40, color: '#f7e08a' },
	{ from: 50, color: '#f6b94f' },
	{ from: 60, color: '#ef8a3c' },
	{ from: 80, color: '#d9472f' },
	{ from: 100, color: '#a3243f' },
	{ from: 120, color: '#6b1f5c' }
];

/** Snow on the ground, lower bound in cm, on whole inches (1, 4, 8, 12, 24 … 120). */
export const DEPTH: RampStep[] = [
	{ from: 2.54, color: '#e8f4f2' },
	{ from: 10.16, color: '#c3e6e1' },
	{ from: 20.32, color: '#94d3cc' },
	{ from: 30.48, color: '#5fbcb4' },
	{ from: 60.96, color: '#2f9f9a' },
	{ from: 91.44, color: '#1b7f86' },
	{ from: 121.92, color: '#155f78' },
	{ from: 182.88, color: '#1d3f6b' },
	{ from: 243.84, color: '#2c2160' },
	{ from: 304.8, color: '#4b0f55' }
];

/** Snow level key: a tick every 1,000 m ("0", "1k" … m, or "3.3k" … ft). */
export function levelTick(m: number, units: UnitSystem): string {
	if (m === 0) return '0';
	if (m % 1000) return '';
	if (units === 'metric') return `${m / 1000}k`;
	return `${(mToFt(m) / 1000).toFixed(1).replace('.0', '')}k`;
}

/** Wind key: "20" (km/h) or "12" (mph). */
export const windTick = (kmh: number, units: UnitSystem) =>
	String(Math.round(units === 'imperial' ? kmhToMph(kmh) : kmh));

/** Depth key: "12" (inches) or "30" (cm). */
export const depthTick = (cm: number, units: UnitSystem) =>
	String(Math.round(units === 'imperial' ? cm / 2.54 : cm));

// ---- What the controls show ---------------------------------------------------------

/** A picture chosen by window: a snow total, snow on the ground, observed snowfall. */
export interface Pick {
	/** The window in hours (0 for snow on the ground). */
	id: number;
	/** The button: "24 h", "3 days". */
	label: string;
	/** Its accessible name: "Next 24 hours", "Last 48 hours". */
	name: string;
	file: string;
	/** Under the buttons: "Sun 10 AM → Tue 4 AM". */
	span: string;
	/** Where it comes from, in a sentence. */
	sources: string;
	/** Snow totals: the terrain-adjusted tiles' URL template, when there are some. */
	tiles?: string | null;
	/** Snow totals: when the window ends ("to Fri 4 PM"). */
	until?: string;
	/** Snow totals: the slider's tick under this window ("12h", "3d"). */
	tick?: string;
}

export interface WeatherView {
	mode: 'loop' | 'pick' | 'none';
	frames: Frame[];
	/** The frame "now" sits at, or -1 (a forecast-only loop). */
	now: number;
	nowcastEnd: number;
	extendedFrom: number;
	picks: Pick[];
	/** The snow total as numbers (a continuous slider): its start and each step's hours. */
	steps: { start: number; hours: number[] } | null;
}

const NONE: WeatherView = {
	mode: 'none',
	frames: [],
	now: -1,
	nowcastEnd: -1,
	extendedFrom: -1,
	picks: [],
	steps: null
};

/** Which layer of the index a weather choice shows. */
export function layerName(weather: MapWeather, wind: MapWind): string | null {
	if (weather === 'wind') return wind === 'ridge' ? 'ridge' : 'gust';
	if (weather === 'snowlevel' || weather === 'clouds') return weather;
	if (weather === 'depth' || weather === 'snowfall') return weather;
	return null;
}

/** A layer's picture as a timeline frame (observed ones count as the past). */
export function asFrame(f: LayerFrame): Frame {
	const past = f.kind === 'observed';
	return {
		t: f.t,
		past,
		file: f.file,
		south: f.src.south ?? '',
		kind: past ? 'radar' : 'forecast',
		span_h: 0,
		src: f.src,
		valid: f.t
	};
}

const dayHour = (s: number) =>
	new Date(s * 1000)
		.toLocaleString('en-US', { weekday: 'short', hour: 'numeric' })
		.replace(',', '');
const monthDay = (s: number) =>
	new Date(s * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

/** The pictures picked by window, for the pick-type layers. */
function picks(tl: Timeline, weather: MapWeather): Pick[] {
	if (weather === 'totals') {
		return tl.totals.map((t) => ({
			id: t.window,
			label: totalLabel(t),
			name: totalName(t),
			file: t.file,
			span: totalSpan(t),
			sources: totalSources(t),
			tiles: t.tiles ?? null,
			until: `to ${dayHour(t.end)}`,
			tick: t.window < 48 ? `${t.window}h` : `${Math.round(t.window / 24)}d`
		}));
	}
	if (weather === 'depth') {
		return (tl.layers.depth ?? []).slice(-1).map((f) => ({
			id: 0,
			label: 'Now',
			name: 'Snow on the ground',
			file: f.file,
			span: depthSpan(f),
			sources: depthSources(f)
		}));
	}
	if (weather === 'snowfall') {
		return (tl.layers.snowfall ?? []).map((f) => ({
			id: f.hours,
			label: `${f.hours} h`,
			name: `Last ${f.hours} hours`,
			file: f.file,
			span: `${dayHour(f.t - f.hours * HOUR)} → ${dayHour(f.t)}`,
			sources: "Observed: NOAA's National Snowfall Analysis (the US only)."
		}));
	}
	return [];
}

/** "SNODAS Nov 11 · CaLDAS Nov 11". */
function depthSpan(f: LayerFrame): string {
	const parts: string[] = [];
	if (f.runs.snodas) parts.push(`US ${monthDay(f.runs.snodas)}`);
	if (f.runs.caldas) parts.push(`Canada ${monthDay(f.runs.caldas)}`);
	return parts.join(' · ');
}

function depthSources(f: LayerFrame): string {
	const parts: string[] = [];
	if (f.runs.snodas) parts.push("US: NOAA's SNODAS analysis");
	if (f.runs.caldas) parts.push("Canada: Environment Canada's CaLDAS analysis");
	return parts.length ? `${parts.join('; ')}, blended across the border.` : '';
}

/** What the controls show for a weather choice. */
export function weatherView(tl: Timeline | null, weather: MapWeather, wind: MapWind): WeatherView {
	if (!tl || weather === 'off') return NONE;
	if (weather === 'radar') {
		return {
			mode: 'loop',
			frames: tl.frames,
			now: tl.now,
			nowcastEnd: tl.nowcastEnd,
			extendedFrom: tl.extendedFrom,
			picks: [],
			steps: null
		};
	}
	if (weather === 'totals' || weather === 'depth' || weather === 'snowfall') {
		const steps =
			weather === 'totals' && tl.steps
				? { start: tl.steps.start, hours: tl.steps.steps.map((x) => x.hours) }
				: null;
		return { ...NONE, mode: 'pick', picks: picks(tl, weather), steps };
	}
	const name = layerName(weather, wind)!;
	const frames = (tl.layers[name] ?? []).map(asFrame);
	return {
		...NONE,
		mode: 'loop',
		frames,
		// Clouds: "now" is the last satellite picture (the forecast's cloud cover follows);
		// the forecast layers start after it.
		now: weather === 'clouds' ? frames.findLastIndex((f) => f.past) : -1
	};
}

/** "in 4 h" up to two days ahead, then "in 3 days". */
function ahead(seconds: number): string {
	const h = Math.round(seconds / HOUR);
	if (h <= 0) return 'now';
	if (h < 48) return `in ${h} h`;
	return `in ${Math.round(h / 24)} days`;
}

/**
 * The slider's label for a frame of one of the other layers: "Sat 5 AM" and
 * "forecast · in 4 h", or "2:30 PM" and "satellite · 40 min ago".
 */
export function layerLabel(f: Frame, now = Date.now()): { when: string; rel: string } {
	const d = new Date(f.t * 1000);
	if (f.past) {
		const when = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
		const ago = Math.round((now / 1000 - f.t) / 60);
		if (ago < 60) return { when, rel: `satellite · ${Math.max(0, ago)} min ago` };
		const h = Math.floor(ago / 60);
		const m = ago % 60;
		return { when, rel: `satellite · ${h} h${m ? ` ${m} min` : ''} ago` };
	}
	const when = `${d.toLocaleDateString('en-US', { weekday: 'short' })} ${d
		.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
		.replace(':00', '')}`;
	return { when, rel: `forecast · ${ahead(f.t - now / 1000)}` };
}

const MODELS: Record<string, string> = {
	hrdps: 'Canadian HRDPS',
	rdps: 'Canadian RDPS',
	gdps: 'Canadian GDPS',
	nbm: "NOAA's National Blend of Models"
};

/** Where a frame of one of the loop layers came from, for the map's info panel. */
export function layerSource(weather: MapWeather, wind: MapWind, f: Frame | undefined): string {
	if (weather === 'clouds') {
		if (f && !f.past) {
			const north = MODELS[f.src.north ?? ''] ?? f.src.north ?? '';
			const south = MODELS[f.src.south ?? ''] ?? f.src.south ?? '';
			const from =
				north && south && north !== south
					? `${north} in Canada, ${south} in the US`
					: north || south;
			return `Forecast cloud cover from ${from}: the thicker the cloud, the greyer.`;
		}
		return 'GOES-West satellite, GeoColor: true colour by day, infrared with city lights by night (NOAA, CIRA; via NASA GIBS). After it, the forecast cloud cover.';
	}
	const north = MODELS[f?.src.north ?? ''] ?? '';
	const south = MODELS[f?.src.south ?? ''] ?? '';
	const models =
		north && south && north !== south
			? `${north} in Canada, ${south} in the US, blended across the border`
			: north || south;
	if (weather === 'wind' && wind === 'ridge') {
		return `Wind at ridge level (700 hPa, about 3,000 m) from the ${north || 'Canadian RDPS'} model, which covers the whole map.`;
	}
	if (weather === 'wind') return `Wind gusts near the ground (10 m): ${models}.`;
	if (weather === 'snowlevel') {
		return `Snow level: the height above sea level where falling snow turns to rain, from ${models}. The darkest band also means snow reaching the ground everywhere.`;
	}
	return '';
}

/** "Clouds" and the like, for the "Zoom out to see …" note. */
export const WEATHER_WORDS: Record<MapWeather, string> = {
	radar: 'precipitation',
	totals: 'snow totals',
	snowlevel: 'the snow level',
	wind: 'the wind',
	depth: 'snow on the ground',
	snowfall: 'observed snowfall',
	clouds: 'clouds',
	off: ''
};

/** The weather choices, in the order the controls list them. */
export const WEATHER_CHOICES: { id: MapWeather; label: string }[] = [
	{ id: 'radar', label: 'Radar & forecast' },
	{ id: 'totals', label: 'Snow total' },
	{ id: 'snowlevel', label: 'Snow level' },
	{ id: 'wind', label: 'Wind' },
	{ id: 'depth', label: 'Snow depth' },
	{ id: 'snowfall', label: 'Observed snow' },
	{ id: 'clouds', label: 'Clouds' }
];

// ---- The snow total's continuous slider ------------------------------------------------

/** The windows the slider marks, evenly spaced along it (between them it is continuous). */
export const TOTAL_MARKS = [12, 24, 48, 72, 120, 168, 240];

/** The marks a total's steps reach (the last may stop short of a window: it is the end). */
export function totalMarks(stepHours: number[]): number[] {
	const last = Math.max(0, ...stepHours);
	const marks = TOTAL_MARKS.filter((h) => h <= last);
	if (!marks.length) return last ? [last] : [];
	if (marks[marks.length - 1] < last && last - marks[marks.length - 1] >= 6) marks.push(last);
	return marks;
}

/** Hours at a slider position (0 … marks − 1, the marks evenly spaced). */
export function hoursAt(pos: number, marks: number[]): number {
	if (!marks.length) return 0;
	const p = Math.min(Math.max(pos, 0), marks.length - 1);
	const i = Math.min(Math.floor(p), marks.length - 2);
	if (i < 0) return marks[0];
	return marks[i] + (marks[i + 1] - marks[i]) * (p - i);
}

/** The slider position for a number of hours (hoursAt's inverse). */
export function posAt(hours: number, marks: number[]): number {
	if (marks.length < 2) return 0;
	if (hours <= marks[0]) return 0;
	for (let i = 0; i < marks.length - 1; i++)
		if (hours <= marks[i + 1]) return i + (hours - marks[i]) / (marks[i + 1] - marks[i]);
	return marks.length - 1;
}

/** "Next 18 hours", "Next 2½ days". */
export function totalWords(hours: number): string {
	if (hours < 47.5) return `Next ${Math.round(hours)} hours`;
	const halves = Math.round(hours / 12);
	const whole = Math.floor(halves / 2);
	return `Next ${whole}${halves % 2 ? '½' : ''} days`;
}

/** A mark's tick: "12h", "3d". */
export const markTick = (h: number) => (h < 48 ? `${h}h` : `${Math.round(h / 24)}d`);

/** "to Fri 4 PM": when a total of so many hours from `start` ends. */
export function totalUntil(start: number, hours: number): string {
	return `to ${dayHour(start + Math.round(hours) * HOUR)}`;
}
