// Precipitation for the map: one timeline from two hours ago to two days ahead,
// blended from free sources so every frame shows type (rain / mix / snow) and amount
// in one set of colours.
//
//   Past, every 10 min, everywhere:
//     RainViewer's radar mosaic (NOAA NEXRAD and Canadian radars in North America),
//     which colours snow apart from rain. We read each colour back to its dBZ and type
//     and repaint it in our colours. Detail stops at zoom 7.
//   Future, hourly, Canada and the northern US (to about 42–44°N in the West):
//     Environment Canada's HRDPS model (2.5 km, ~48 h): rain, freezing rain and snow.
//   Future, the rest of the US:
//     NOAA's HRRR (3 km) simulated radar coloured by precip type, from Iowa State's
//     IEM tile cache, repainted in our colours. Hourly runs reach 18 h; the 6-hourly
//     runs reach 48 h, so most hours past 18 h are covered too.
//     Where HRRR has nothing: NWS/WPC 6-hour precipitation totals (no type).
//
// The US sources are clipped to outside the HRDPS domain, so each place shows one model.
// A future in-house HRRR layer (full type, 48 h, our own tiles) would replace the
// HRRR/WPC "south" source without touching the rest.
import type { UnitSystem } from './units';

export const GEOMET = 'https://geo.weather.gc.ca/geomet';
export const IEM = 'https://mesonet.agron.iastate.edu';
export const WPC =
	'https://mapservices.weather.noaa.gov/vector/rest/services/precip/wpc_qpf/MapServer';

const MIN = 60;
const HOUR = 3600;

// ---- Colours -----------------------------------------------------------------

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

// ---- GeoMet WMS layers ----------------------------------------------------------

export interface WmsLayer {
	layer: string;
	ramp: Ramp;
}

/** Forecast: 1-hour accumulations ending at `time`. Snow drawn last, on top. */
export const MODEL_LAYERS: WmsLayer[] = [
	{ layer: 'HRDPS.CONTINENTAL.DIAG_RN_PT1H', ramp: RAMPS.rain },
	{ layer: 'HRDPS.CONTINENTAL.DIAG_FR_PT1H', ramp: RAMPS.mix },
	{ layer: 'HRDPS.CONTINENTAL.DIAG_SN_PT1H', ramp: RAMPS.snow }
];

/** Any HRDPS layer drawn solid wherever the model has data: the domain, used as a mask. */
export const DOMAIN_LAYER = 'HRDPS.CONTINENTAL.DIAG_PR_PT1H';

/**
 * A WMS style. GeoMet reads each entry as the lower bound of a band and leaves values
 * under the first entry transparent, so the faintest drizzle doesn't paint the map.
 */
export function sldBody(layer: string, steps: RampStep[]): string {
	const top = steps[steps.length - 1];
	const entries = [...steps, { from: 9999, color: top.color }]
		.map((s) => `<ColorMapEntry color="${s.color}" quantity="${s.from}"/>`)
		.join('');
	return (
		'<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld">' +
		`<NamedLayer><Name>${layer}</Name><UserStyle><FeatureTypeStyle><Rule>` +
		`<RasterSymbolizer><ColorMap type="intervals">${entries}</ColorMap></RasterSymbolizer>` +
		'</Rule></FeatureTypeStyle></UserStyle></NamedLayer></StyledLayerDescriptor>'
	);
}

export const domainSld = () => sldBody(DOMAIN_LAYER, [{ from: -1, color: '#000000' }]);

// ---- Times -------------------------------------------------------------------

/** Parse a WMS time dimension: "start/end/PT1H" ranges and/or comma-separated instants. */
export function parseTimeDimension(dim: string): number[] {
	const out: number[] = [];
	for (const part of dim.split(',').map((s) => s.trim())) {
		if (!part) continue;
		const [a, b, p] = part.split('/');
		const start = Date.parse(a) / 1000;
		if (!Number.isFinite(start)) continue;
		if (!b) {
			out.push(start);
			continue;
		}
		const end = Date.parse(b) / 1000;
		const m = /^PT(?:(\d+)H)?(?:(\d+)M)?$/.exec(p ?? '');
		const step = m ? Number(m[1] ?? 0) * HOUR + Number(m[2] ?? 0) * MIN : 0;
		if (!Number.isFinite(end) || step <= 0) continue;
		for (let t = start; t <= end && out.length < 2000; t += step) out.push(t);
	}
	return [...new Set(out)].sort((x, y) => x - y);
}

/** The first time dimension in a GetCapabilities document. */
export function capabilityTimes(capabilities: string): number[] {
	const m = /<Dimension[^>]*name="time"[^>]*>([^<]+)</.exec(capabilities);
	return m ? parseTimeDimension(m[1]) : [];
}

async function layerTimes(layer: string): Promise<number[]> {
	const url = `${GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer=${layer}`;
	const res = await fetch(url);
	if (!res.ok) throw new Error(`${layer} times ${res.status}`);
	return capabilityTimes(await res.text());
}

/** Forecast hours (each the END of a 1-hour accumulation) from the one under way now. */
export function futureTimes(model: number[], now = Date.now()): number[] {
	return model.filter((t) => t > now / 1000);
}

export interface Frame {
	/** Unix seconds. */
	t: number;
	past: boolean;
}

export interface Timeline {
	frames: Frame[];
	/** Index of the latest radar frame ("now"), or -1. */
	now: number;
}

export function buildTimeline(past: number[], future: number[]): Timeline {
	const frames = [
		...past.map((t) => ({ t, past: true })),
		...future.map((t) => ({ t, past: false }))
	];
	return { frames, now: past.length - 1 };
}

export async function loadTimeline(): Promise<Timeline> {
	const [radar, model] = await Promise.allSettled([loadRadar(), layerTimes(MODEL_LAYERS[2].layer)]);
	if (radar.status === 'fulfilled') radarUrls = new Map(radar.value.map((f) => [f.time, f.url]));
	const past = radar.status === 'fulfilled' ? radar.value.map((f) => f.time) : [];
	const future = model.status === 'fulfilled' ? futureTimes(model.value) : [];
	const tl = buildTimeline(past, future);
	if (!tl.frames.length) throw new Error('no precipitation frames');
	return tl;
}

// ---- Radar (RainViewer) -----------------------------------------------------------

export const RADAR_INDEX = 'https://api.rainviewer.com/public/weather-maps.json';
export const RADAR_MAX_NATIVE_ZOOM = 7;
/** Colour scheme 2 ("Universal Blue"), smoothed, snow in its own colours. */
const RADAR_STYLE = '2/1_1';

export interface RadarFrame {
	/** Unix seconds. */
	time: number;
	/** Leaflet tile URL template. */
	url: string;
}

interface RadarIndex {
	host?: string;
	radar?: { past?: { time: number; path: string }[] };
}

export function radarFrames(index: unknown): RadarFrame[] {
	const ix = index as RadarIndex;
	if (!ix?.host || !ix.radar) return [];
	return (ix.radar.past ?? [])
		.filter((f) => typeof f?.time === 'number' && typeof f?.path === 'string')
		.sort((a, b) => a.time - b.time)
		.map((f) => ({ time: f.time, url: `${ix.host}${f.path}/256/{z}/{x}/{y}/${RADAR_STYLE}.png` }));
}

async function loadRadar(): Promise<RadarFrame[]> {
	const res = await fetch(RADAR_INDEX);
	if (!res.ok) throw new Error(`radar index ${res.status}`);
	return radarFrames(await res.json());
}

let radarUrls = new Map<number, string>();
export const radarUrl = (t: number) => radarUrls.get(t) ?? null;

/**
 * RainViewer's published "Universal Blue" table (rainviewer.com/api/color-schemes.html):
 * one colour per dBZ, separately for rain and snow. Rain starts at 15 dBZ (weaker
 * returns are faint, mostly clutter); snow from 0.
 */
const RV_RAIN_FROM = 15;
const RV_RAIN = [
	'88ddee',
	'6cd1eb',
	'51c5e8',
	'36bae5',
	'1baee2',
	'00a3e0',
	'009ad5',
	'0091ca',
	'0088bf',
	'007fb4',
	'0077aa',
	'0070a3',
	'00699c',
	'006295',
	'005b8e',
	'005588',
	'005180',
	'004e78',
	'004a70',
	'004768',
	'ffee00',
	'ffe000',
	'ffd200',
	'ffc500',
	'ffb700',
	'ffaa00',
	'ff9f00',
	'ff9500',
	'ff8b00',
	'ff8100',
	'ff4400',
	'f23600',
	'e62800',
	'd91b00',
	'cd0d00',
	'c10000',
	'a80000',
	'8f0000',
	'760000',
	'5d0000',
	'ffaaff',
	'ff9fff',
	'ff95ff',
	'ff8bff',
	'ff81ff',
	'ff77ff',
	'ff6cff',
	'ff62ff',
	'ff58ff',
	'ff4eff'
];
const RV_SNOW_FROM = 0;
const RV_SNOW = [
	'c7ffff',
	'c6ffff',
	'c5ffff',
	'c4ffff',
	'c3ffff',
	'c3ffff',
	'c2ffff',
	'c1ffff',
	'c0ffff',
	'bfffff',
	'bfffff',
	'b8f8ff',
	'b2f2ff',
	'abebff',
	'a5e5ff',
	'9fdfff',
	'98d8ff',
	'92d2ff',
	'8bcbff',
	'85c5ff',
	'7fbfff',
	'78b8ff',
	'72b2ff',
	'6babff',
	'65a5ff',
	'5f9fff',
	'5b9bff',
	'5898ff',
	'5595ff',
	'5292ff',
	'4f8fff',
	'4b8bff',
	'4888ff',
	'4585ff',
	'4282ff',
	'3f7fff',
	'3b7bff',
	'3878ff',
	'3575ff',
	'3272ff',
	'2f6fff',
	'2b6bff',
	'2868ff',
	'2565ff',
	'2262ff',
	'1f5fff',
	'1b5bff',
	'1858ff',
	'1555ff',
	'1252ff',
	'0f4fff',
	'0c4bff',
	'0948ff',
	'0645ff',
	'0242ff',
	'003fff',
	'003bff',
	'0038ff',
	'0035ff',
	'0032ff'
];

const rvTable: { rgb: [number, number, number]; snow: boolean; dbz: number }[] = [
	...RV_RAIN.map((h, i) => ({ h, snow: false, dbz: RV_RAIN_FROM + i })),
	...RV_SNOW.map((h, i) => ({ h, snow: true, dbz: RV_SNOW_FROM + i }))
].map(({ h, snow, dbz }) => ({
	rgb: [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4), 16)],
	snow,
	dbz
}));

/** Rain rate from reflectivity, Marshall–Palmer (Z = 200 R^1.6), mm/h. */
export const rainRate = (dbz: number) => (10 ** (dbz / 10) / 200) ** (1 / 1.6);
/**
 * Snow water rate from reflectivity, mm/h ≈ cm of snow per hour. NEXRAD offers
 * Z = 75–180 S^2 depending on region; 180 is the cautious end.
 */
export const snowRate = (dbz: number) => Math.sqrt(10 ** (dbz / 10) / 180);

export function rampColor(ramp: Ramp, rate: number): string | null {
	let c: string | null = null;
	for (const s of ramp.steps) if (rate >= s.from) c = s.color;
	return c;
}

/** A RainViewer pixel in our colours, or null to drop it. Smoothed edges match the nearest entry. */
export function radarRecolor(r: number, g: number, b: number): string | null {
	let best = rvTable[0];
	let dist = Infinity;
	for (const e of rvTable) {
		const d = (e.rgb[0] - r) ** 2 + (e.rgb[1] - g) ** 2 + (e.rgb[2] - b) ** 2;
		if (d < dist) {
			dist = d;
			best = e;
		}
	}
	if (dist > 40 * 40 * 3) return null;
	return best.snow
		? rampColor(RAMPS.snow, snowRate(best.dbz))
		: rampColor(RAMPS.rain, rainRate(best.dbz));
}

// ---- HRRR (IEM) -------------------------------------------------------------------

const pad4 = (n: number) => String(n).padStart(4, '0');
export const hrrrTileUrl = (minute: number) =>
	`${IEM}/cache/tile.py/1.0.0/hrrr::REFP-F${pad4(minute)}-0/{z}/{x}/{y}.png`;
const hrrrMetaUrl = (minute: number) =>
	`${IEM}/data/gis/images/4326/hrrr/refp_${pad4(minute)}.json`;

/**
 * IEM keeps one image per forecast minute, each from the newest run that reaches it:
 * the latest hourly run to 18 h, then an older 6-hourly run beyond. Each slot's JSON
 * names its valid time, so check it rather than assume.
 */
const hrrrMeta = new Map<number, Promise<number | null>>();

/** JSON from a busy server: one retry, and an error (not a cached null) if both fail. */
async function getJson<T>(url: string): Promise<T> {
	for (let attempt = 0; ; attempt++) {
		try {
			const r = await fetch(url);
			if (r.ok) return (await r.json()) as T;
			if (r.status === 404) throw new Error('missing');
		} catch (e) {
			if ((e as Error).message === 'missing' || attempt >= 1) throw e;
		}
		if (attempt >= 1) throw new Error(`failed ${url}`);
		await new Promise((res) => setTimeout(res, 700 + Math.random() * 600));
	}
}

function slotValid(minute: number): Promise<number | null> {
	let p = hrrrMeta.get(minute);
	if (!p) {
		p = getJson<{ model_forecast_utc?: string }>(hrrrMetaUrl(minute)).then((j) =>
			j?.model_forecast_utc ? Date.parse(j.model_forecast_utc) / 1000 : null
		);
		// Forget failures so a later frame asks again.
		p.catch(() => hrrrMeta.delete(minute));
		hrrrMeta.set(minute, p);
	}
	return p.catch(() => null);
}

/** The IEM forecast minute whose image is valid at `t`, or null. */
export async function hrrrSlot(t: number): Promise<number | null> {
	const latest = await slotValid(0);
	if (latest === null) return null;
	const m1 = Math.round((t - latest) / MIN);
	if (m1 >= 0 && m1 <= 18 * 60 && (await slotValid(m1)) === t) return m1;
	// Beyond 18 h: the slots come from a 6-hourly run; find it from the first such slot.
	const first = await slotValid(19 * 60);
	if (first === null) return null;
	const init = first - 19 * HOUR;
	const m2 = Math.round((t - init) / MIN);
	if (m2 > 18 * 60 && m2 <= 48 * 60 && (await slotValid(m2)) === t) return m2;
	return null;
}

/**
 * IEM paints HRRR reflectivity by type: greens then yellows for rain, blues for snow,
 * purples and reds for ice pellets and freezing rain. Map each colour to ours by family
 * and lightness. Returns null for colours to drop.
 */
export function hrrrRecolor(r: number, g: number, b: number): string | null {
	const max = Math.max(r, g, b) / 255;
	const min = Math.min(r, g, b) / 255;
	const l = (max + min) / 2;
	const d = max - min;
	if (d < 0.04) return null; // grey or white: no family
	const s = d / (1 - Math.abs(2 * l - 1));
	let h: number;
	const R = r / 255,
		G = g / 255,
		B = b / 255;
	if (max === R) h = 60 * (((G - B) / d) % 6);
	else if (max === G) h = 60 * ((B - R) / d + 2);
	else h = 60 * ((R - G) / d + 4);
	if (h < 0) h += 360;

	const rain = RAMPS.rain.steps;
	const snow = RAMPS.snow.steps;
	const mix = RAMPS.mix.steps;
	if (h >= 30 && h < 65 && s > 0.8) {
		// Yellow to orange: the heaviest rain.
		return h >= 48 ? rain[3].color : h >= 42 ? rain[4].color : rain[5].color;
	}
	if (h >= 80 && h < 170)
		return l > 0.75 ? rain[0].color : l > 0.45 ? rain[1].color : rain[2].color;
	if (h >= 170 && h < 225) {
		return l > 0.62
			? snow[0].color
			: l > 0.5
				? snow[1].color
				: l > 0.42
					? snow[2].color
					: l > 0.31
						? snow[3].color
						: snow[4].color;
	}
	// Purples and reds: ice pellets, freezing rain.
	return l > 0.78 ? mix[0].color : mix[1].color;
}

// ---- WPC 6-hour totals ---------------------------------------------------------------

/** Layer 13 is hours 0–6 from the product's base time, 14 is 6–12, … up to 25 (72–78). */
const WPC_FIRST = 13;
const WPC_LAST = 25;

let wpcBaseP: Promise<number | null> | null = null;
const wpcData = new Map<number, Promise<WpcCollection | null>>();

export interface WpcCollection {
	type: 'FeatureCollection';
	features: {
		properties: { qpf: number };
		geometry: { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown };
	}[];
}

/** "2026-11-07 12:00:00" (UTC) → Unix seconds. */
export const wpcTime = (s: string) => Date.parse(s.replace(' ', 'T') + 'Z') / 1000;

function wpcBase(): Promise<number | null> {
	wpcBaseP ??= fetch(
		`${WPC}/${WPC_FIRST}/query?where=1%3D1&outFields=start_time&returnGeometry=false&resultRecordCount=1&f=json`
	)
		.then((r) => (r.ok ? r.json() : null))
		.then((j) => {
			const s = j?.features?.[0]?.attributes?.start_time;
			return typeof s === 'string' ? wpcTime(s) : null;
		})
		.catch(() => null);
	return wpcBaseP;
}

/** Which 6-hour layer holds the hour ending at `t`. */
export function wpcLayerFor(t: number, base: number): number | null {
	const i = Math.floor((t - HOUR - base) / (6 * HOUR));
	const id = WPC_FIRST + i;
	return i >= 0 && id <= WPC_LAST ? id : null;
}

export async function wpcFor(t: number): Promise<WpcCollection | null> {
	const base = await wpcBase();
	if (base === null) return null;
	const id = wpcLayerFor(t, base);
	if (id === null) return null;
	let p = wpcData.get(id);
	if (!p) {
		p = fetch(
			`${WPC}/${id}/query?where=qpf%3E%3D0.1&outFields=qpf&returnGeometry=true` +
				`&maxAllowableOffset=0.02&geometryPrecision=3&outSR=4326&f=geojson`
		)
			.then((r) => (r.ok ? (r.json() as Promise<WpcCollection>) : null))
			.then((fc) => {
				fc?.features.sort((a, b) => a.properties.qpf - b.properties.qpf);
				return fc;
			})
			.catch(() => null);
		wpcData.set(id, p);
	}
	return p;
}

/** Forget cached HRRR and WPC metadata so the next frames use the newest runs. */
export function resetSouthCache() {
	hrrrMeta.clear();
	wpcData.clear();
	wpcBaseP = null;
}

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
