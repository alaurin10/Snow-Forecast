// Precipitation layers for the map.
//
// Past: weather radar from RainViewer's free public API, the last two hours in
// 10-minute steps. Tiles carry real detail up to zoom 7; Leaflet scales them past that.
//
// Future: hourly precipitation from Environment Canada's HRDPS model (2.5 km, out to
// ~48 h), served free by MSC GeoMet as WMS images. Its domain covers Canada and the
// northern US. Rain, freezing rain and snow are separate layers, each drawn on its own
// colour ramp (we send the ramp as an SLD style), so one frame shows both type and amount.
import type { UnitSystem } from './units';

export const RADAR_INDEX = 'https://api.rainviewer.com/public/weather-maps.json';
export const RADAR_MAX_NATIVE_ZOOM = 7;
/** Colour scheme 2 ("Universal Blue"), smoothed, with snow drawn in its own colours. */
const COLOR = 2;
const OPTIONS = '1_1';

export const FORECAST_WMS = 'https://geo.weather.gc.ca/geomet';

export interface RadarFrame {
	/** Unix seconds. */
	time: number;
	/** Leaflet tile URL template. */
	url: string;
}

interface Index {
	host?: string;
	radar?: { past?: { time: number; path: string }[]; nowcast?: { time: number; path: string }[] };
}

export function radarFrames(index: unknown): RadarFrame[] {
	const ix = index as Index;
	if (!ix?.host || !ix.radar) return [];
	return [...(ix.radar.past ?? []), ...(ix.radar.nowcast ?? [])]
		.filter((f) => typeof f?.time === 'number' && typeof f?.path === 'string')
		.sort((a, b) => a.time - b.time)
		.map((f) => ({
			time: f.time,
			url: `${ix.host}${f.path}/256/{z}/{x}/{y}/${COLOR}/${OPTIONS}.png`
		}));
}

export async function loadRadar(): Promise<RadarFrame[]> {
	const res = await fetch(RADAR_INDEX);
	if (!res.ok) throw new Error(`radar index ${res.status}`);
	return radarFrames(await res.json());
}

// ---- Forecast ----------------------------------------------------------------

export type PrecipKind = 'snow' | 'mix' | 'rain';

export interface RampStep {
	/** Lower bound, mm of water per hour. */
	from: number;
	color: string;
}

export interface Ramp {
	kind: PrecipKind;
	label: string;
	layer: string;
	steps: RampStep[];
}

/**
 * Drawn in this order, so snow sits on top where a cell has some of each.
 * Snow amounts are water equivalent: at a typical 10:1 ratio, 1 mm of water is about
 * 1 cm of snow, so the snow steps read directly as cm of snow per hour.
 */
export const RAMPS: Ramp[] = [
	{
		kind: 'rain',
		label: 'Rain',
		layer: 'HRDPS.CONTINENTAL.DIAG_RN_PT1H',
		steps: [
			{ from: 0.1, color: '#a6dba0' },
			{ from: 0.5, color: '#5aae61' },
			{ from: 1, color: '#1b7837' },
			{ from: 2.5, color: '#f4d03f' },
			{ from: 5, color: '#ee8a2a' },
			{ from: 10, color: '#d7301f' }
		]
	},
	{
		kind: 'mix',
		label: 'Freezing rain',
		layer: 'HRDPS.CONTINENTAL.DIAG_FR_PT1H',
		steps: [
			{ from: 0.1, color: '#f4a6c6' },
			{ from: 1, color: '#e0457b' }
		]
	},
	{
		kind: 'snow',
		label: 'Snow',
		layer: 'HRDPS.CONTINENTAL.DIAG_SN_PT1H',
		steps: [
			{ from: 0.1, color: '#c6dbef' },
			{ from: 0.5, color: '#8fbfe6' },
			{ from: 1, color: '#4a90d9' },
			{ from: 2, color: '#2c5fb8' },
			{ from: 3, color: '#6a3fb0' }
		]
	}
];

/**
 * A WMS style for one layer. GeoMet reads each entry as the lower bound of a band and
 * leaves values under the first entry transparent, so light drizzle doesn't paint the map.
 */
export function sldBody(ramp: Ramp): string {
	const top = ramp.steps[ramp.steps.length - 1];
	const entries = [...ramp.steps, { from: 9999, color: top.color }]
		.map((s) => `<ColorMapEntry color="${s.color}" quantity="${s.from}"/>`)
		.join('');
	return (
		'<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld">' +
		`<NamedLayer><Name>${ramp.layer}</Name><UserStyle><FeatureTypeStyle><Rule>` +
		`<RasterSymbolizer><ColorMap type="intervals">${entries}</ColorMap></RasterSymbolizer>` +
		'</Rule></FeatureTypeStyle></UserStyle></NamedLayer></StyledLayerDescriptor>'
	);
}

const HOUR = 3600;

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
		const step = m ? Number(m[1] ?? 0) * HOUR + Number(m[2] ?? 0) * 60 : 0;
		if (!Number.isFinite(end) || step <= 0) continue;
		for (let t = start; t <= end && out.length < 500; t += step) out.push(t);
	}
	return [...new Set(out)].sort((x, y) => x - y);
}

/**
 * Hours the forecast covers that haven't finished yet. Each value is the END of a
 * one-hour accumulation, so the hour under way now is the first frame.
 */
export function forecastTimes(capabilities: string, now = Date.now()): number[] {
	const m = /<Dimension[^>]*name="time"[^>]*>([^<]+)</.exec(capabilities);
	if (!m) return [];
	const nowS = now / 1000;
	return parseTimeDimension(m[1]).filter((t) => t > nowS);
}

export async function loadForecastTimes(): Promise<number[]> {
	// The snow layer stands in for all three: they come from the same model run.
	const url =
		`${FORECAST_WMS}?service=WMS&version=1.3.0&request=GetCapabilities` +
		`&layer=${RAMPS.find((r) => r.kind === 'snow')!.layer}`;
	const res = await fetch(url);
	if (!res.ok) throw new Error(`forecast times ${res.status}`);
	return forecastTimes(await res.text());
}

// ---- Labels ------------------------------------------------------------------

const clock = (d: Date) =>
	d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).replace(':00', '');

/** Radar frame: "2:40 PM" and "20 min ago". */
export function frameLabel(time: number, now = Date.now()): { when: string; rel: string } {
	const when = new Date(time * 1000).toLocaleTimeString('en-US', {
		hour: 'numeric',
		minute: '2-digit'
	});
	const ago = Math.round((now / 1000 - time) / 60);
	if (ago <= 5) return { when, rel: 'latest' };
	if (ago < 60) return { when, rel: `${ago} min ago` };
	const h = Math.floor(ago / 60);
	const m = ago % 60;
	return { when, rel: m ? `${h} h ${m} min ago` : `${h} h ago` };
}

/** Forecast hour ending at `time`: "Sat 5–6 AM" and "in 4 h". */
export function forecastLabel(time: number, now = Date.now()): { when: string; rel: string } {
	const start = new Date((time - HOUR) * 1000);
	const end = new Date(time * 1000);
	const day = start.toLocaleDateString('en-US', { weekday: 'short' });
	const a = clock(start);
	const b = clock(end);
	// "5–6 AM" when both ends share AM/PM, else "11 AM–12 PM".
	const [aNum, aMer] = a.split(' ');
	const [bNum, bMer] = b.split(' ');
	const span = aMer === bMer ? `${aNum}–${bNum} ${bMer}` : `${a}–${b}`;
	const ahead = Math.round((time - HOUR - now / 1000) / HOUR);
	const rel = ahead <= 0 ? 'this hour' : `in ${ahead} h`;
	return { when: `${day} ${span}`, rel };
}

// ---- Legend ------------------------------------------------------------------

/** "0.4", "3" or "0.04": short, for the legend. */
const tidy = (n: number) => String(Number(n.toFixed(n < 0.1 ? 2 : 1)));

/** The amount at the top step of a ramp, as "3+ cm/h" or "1.2+ in/h". */
export function rampTop(ramp: Ramp, units: UnitSystem): string {
	const mm = ramp.steps[ramp.steps.length - 1].from;
	if (ramp.kind === 'snow') {
		// mm of water ≈ cm of snow at 10:1.
		return units === 'imperial' ? `${tidy(mm / 2.54)}+ in/h` : `${tidy(mm)}+ cm/h`;
	}
	return units === 'imperial' ? `${tidy(mm / 25.4)}+ in/h` : `${tidy(mm)}+ mm/h`;
}
