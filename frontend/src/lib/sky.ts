// The weather behind the page: one scene for the location's current hour. The sky is
// deliberately static; it never follows the chart while you scrub, so the page never
// flashes. It changes only when the location (or the data) changes.
import type { HourlyOut, Snapshot, SunDay } from './types.gen';

export type Scene =
	'clear' | 'night' | 'glow' | 'partly' | 'overcast' | 'snow' | 'heavy' | 'mixed' | 'rain' | 'fog';

export interface SkyState {
	scene: Scene;
	/** After dark, for scenes that keep their own palette under a dusk veil. */
	night: boolean;
	/** A short word for the scene, e.g. "Light snow". */
	label: string;
}

export const SCENE_LABEL: Record<Scene, string> = {
	clear: 'Clear',
	night: 'Clear night',
	glow: 'Alpenglow',
	partly: 'Partly cloudy',
	overcast: 'Overcast',
	snow: 'Light snow',
	heavy: 'Heavy snow',
	mixed: 'Rain and snow',
	rain: 'Rain',
	fog: 'Fog'
};

/** The calm default before any forecast has loaded. */
export const DEFAULT_SKY: SkyState = { scene: 'partly', night: false, label: SCENE_LABEL.partly };

/** Snow over the next three hours that counts as heavy: 0.9 in. */
const HEAVY_3H_CM = 2.29;
/** Within this long of sunrise or sunset, a clear sky is alpenglow. */
const GLOW_MIN = 75;

const num = (v: number | null | undefined) => (typeof v === 'number' ? v : 0);

/** The scene for hour `at` of the hourly series. */
export function pickScene(h: HourlyOut, sun: SunDay[] = [], at = 0): SkyState {
	const i = Math.max(0, Math.min(at, h.t.length - 1));
	if (!h.t.length) return DEFAULT_SKY;
	const snow = num(h.snow_cm[i]);
	const rain = num(h.rain_mm[i]);
	let snow3 = 0;
	for (let k = i; k < Math.min(i + 3, h.t.length); k++) snow3 += num(h.snow_cm[k]);
	const cloud = num(h.cloud[i]);
	const code = h.wcode[i];
	const night = h.is_day[i] === 0;

	let scene: Scene;
	if (snow3 >= HEAVY_3H_CM) scene = 'heavy';
	else if (snow > 0.05 && rain >= 0.3) scene = 'mixed';
	else if (snow > 0.05) scene = 'snow';
	else if (rain >= 0.2) scene = 'rain';
	else if (code === 45 || code === 48) scene = 'fog';
	else if (cloud >= 85) scene = 'overcast';
	else if (cloud >= 35) scene = 'partly';
	else scene = 'clear';

	if (scene === 'clear' || scene === 'partly') {
		const t = Date.parse(h.t[i]);
		const day = h.t[i].slice(0, 10);
		const today = sun.find((s) => s.date === day);
		const near = (iso: string | null | undefined) =>
			!!iso && Math.abs(Date.parse(iso) - t) <= GLOW_MIN * 60_000;
		if (today && (near(today.sunrise) || near(today.sunset)))
			return { scene: 'glow', night: false, label: SCENE_LABEL.glow };
		if (night) return { scene: 'night', night: true, label: SCENE_LABEL.night };
	}
	return { scene, night, label: SCENE_LABEL[scene] };
}

/** A location's sky right now, at mid-mountain. */
export function skyOf(snap: Snapshot): SkyState {
	const band = snap.bands[1] ?? snap.bands[0];
	if (!band) return DEFAULT_SKY;
	return pickScene(band.hourly, snap.sun ?? [], hourIndex(band.hourly, snap.now));
}

/** Index of the hour holding `now` (or 0). */
export function hourIndex(h: HourlyOut, now: string | null | undefined): number {
	if (!now) return 0;
	const t = Date.parse(now);
	let k = 0;
	for (let i = 0; i < h.t.length; i++) if (Date.parse(h.t[i]) <= t) k = i;
	return k;
}
