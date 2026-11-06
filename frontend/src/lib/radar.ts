// Weather radar frames from RainViewer's free public API: the last two hours in
// 10-minute steps. Tiles carry real detail up to zoom 7; Leaflet scales them past that.
export const RADAR_INDEX = 'https://api.rainviewer.com/public/weather-maps.json';
export const RADAR_MAX_NATIVE_ZOOM = 7;
/** Colour scheme 2 ("Universal Blue"), smoothed, with snow drawn in its own colours. */
const COLOR = 2;
const OPTIONS = '1_1';

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

/** "2:40 PM · 20 min ago" for a frame, in the viewer's time. */
export function frameLabel(time: number, now = Date.now()): string {
	const at = new Date(time * 1000).toLocaleTimeString('en-US', {
		hour: 'numeric',
		minute: '2-digit'
	});
	const ago = Math.round((now / 1000 - time) / 60);
	return ago <= 1 ? `${at} · latest` : `${at} · ${ago} min ago`;
}
