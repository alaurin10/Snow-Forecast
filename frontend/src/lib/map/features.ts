// The map's point and area features from the server: snow stations (SNOTEL and BC snow
// pillows), Avalanche Canada's field reports, and the ATES ratings the owner supplied.
// Pure functions: GeoJSON for the map, and words for the sheets.
import type { AtesOut, MapStation, ObsOut, StationsOut } from '../types.gen';
import type { UnitSystem } from '../units';
import { cmToIn } from '../units';

// ---- Snow stations -----------------------------------------------------------------

/** Snow depth colours for station dots: bare to deep. */
export const DEPTH_STEPS = [
	{ from: 0, color: '#c9d1d9', label: 'bare' },
	{ from: 1, color: '#9cc7ee' },
	{ from: 30, color: '#5b9be0' },
	{ from: 100, color: '#2f63c4' },
	{ from: 200, color: '#2b2f8f' }
] as const;

export function depthColor(cm: number | null | undefined): string {
	if (cm == null) return '#8a8f98';
	let c: string = DEPTH_STEPS[0].color;
	for (const s of DEPTH_STEPS) if (cm >= s.from) c = s.color;
	return c;
}

/** "+12" (cm or in) for a station's new snow in 24 hours; '' when it hasn't snowed. */
export function newSnowLabel(cm: number | null | undefined, units: UnitSystem): string {
	if (cm == null || cm < 1) return '';
	return units === 'imperial' ? `+${Math.round(cmToIn(cm))}` : `+${Math.round(cm)}`;
}

export function stationsGeojson(d: StationsOut, units: UnitSystem): GeoJSON.FeatureCollection {
	return {
		type: 'FeatureCollection',
		features: d.stations.map((s, i) => ({
			type: 'Feature',
			id: i,
			properties: {
				i,
				color: depthColor(s.depth_cm),
				label: newSnowLabel(s.change24_cm, units),
				fresh: (s.change24_cm ?? 0) >= 1
			},
			geometry: { type: 'Point', coordinates: [s.lon, s.lat] }
		}))
	};
}

/** Where a station's numbers come from. */
export function networkName(s: MapStation): string {
	return s.network === 'bc' ? 'BC River Forecast Centre snow pillow' : 'NRCS SNOTEL';
}

/** "3 h ago", "2 days ago": how old a reading or report is. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
	if (!iso) return '';
	const ms = now - Date.parse(iso);
	if (!Number.isFinite(ms)) return '';
	const h = ms / 3600000;
	if (h < 1) return 'within the hour';
	if (h < 36) return `${Math.round(h)} h ago`;
	return `${Math.round(h / 24)} days ago`;
}

/** The week's daily depths as sparkline points in a w × h box (null days leave gaps). */
export function sparkline(
	days: { depth_cm: number | null }[],
	w: number,
	h: number
): { d: string; max: number } {
	const vals = days.map((d) => d.depth_cm);
	const got = vals.filter((v): v is number => v != null);
	if (got.length < 2) return { d: '', max: got[0] ?? 0 };
	const max = Math.max(10, ...got);
	const step = w / Math.max(1, vals.length - 1);
	let d = '';
	let pen = false;
	vals.forEach((v, i) => {
		if (v == null) {
			pen = false;
			return;
		}
		const x = (i * step).toFixed(1);
		const y = (h - (v / max) * h).toFixed(1);
		d += `${pen ? 'L' : 'M'}${x},${y}`;
		pen = true;
	});
	return { d, max };
}

// ---- Field reports -----------------------------------------------------------------

/** Each kind of observation in a report, in words and as its dot's colour. */
export const REPORT_KINDS: Record<string, { label: string; color: string }> = {
	avalanche: { label: 'Avalanche', color: '#d2382c' },
	incident: { label: 'Incident', color: '#7a1f3d' },
	snowpack: { label: 'Snowpack', color: '#2f63c4' },
	weather: { label: 'Weather', color: '#2a9d8f' },
	quick: { label: 'Quick report', color: '#6b7280' }
};

export function reportColor(kinds: readonly string[]): string {
	return REPORT_KINDS[kinds[0]]?.color ?? REPORT_KINDS.quick.color;
}

export function reportsGeojson(d: ObsOut): GeoJSON.FeatureCollection {
	return {
		type: 'FeatureCollection',
		features: d.features.map((f, i) => ({
			type: 'Feature',
			id: i,
			properties: { i, color: reportColor(f.properties.kinds) },
			geometry: f.geometry as unknown as GeoJSON.Geometry
		}))
	};
}

// ---- ATES --------------------------------------------------------------------------

/** ATES classes as Avalanche Canada draws them; "unrated" means the file didn't say. */
export const ATES: Record<string, { label: string; color: string }> = {
	non: { label: 'Non-avalanche', color: '#9ccc65' },
	simple: { label: 'Simple', color: '#2e9d4a' },
	challenging: { label: 'Challenging', color: '#1f6fd6' },
	complex: { label: 'Complex', color: '#1b1b1f' },
	extreme: { label: 'Extreme', color: '#c2185b' },
	unrated: { label: 'Unrated', color: '#8a8f98' }
};

export function atesGeojson(d: AtesOut): GeoJSON.FeatureCollection {
	return {
		type: 'FeatureCollection',
		features: d.features.map((f) => ({
			type: 'Feature',
			properties: {
				rating: f.properties.rating,
				name: f.properties.name,
				file: f.properties.file
			},
			geometry: f.geometry as unknown as GeoJSON.Geometry
		}))
	};
}
