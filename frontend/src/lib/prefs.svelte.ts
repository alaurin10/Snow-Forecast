// Per-device viewer preferences, kept in localStorage (which can be missing
// or blocked, so every access is guarded).
import type { UnitSystem } from './units';

/** Colour mode. */
export type Theme = 'auto' | 'light' | 'dark';
/** Theme family: Live Sky (the weather behind the page) or a still, fixed sky. */
export type ThemeFamily = 'sky' | 'alpenglow' | 'glacier' | 'larch' | 'granite';
export const THEME_FAMILIES: readonly ThemeFamily[] = [
	'sky',
	'alpenglow',
	'glacier',
	'larch',
	'granite'
] as const;
/** Full: everything moves. Subtle: no falling snow or count-ups. Off: nothing moves. */
export type Motion = 'full' | 'subtle' | 'off';
export type BandName = 'base' | 'mid' | 'summit';
/** The one weather layer on the map. */
export type MapWeather = 'radar' | 'totals' | 'off';
export const MAP_WEATHER: readonly MapWeather[] = ['radar', 'totals', 'off'] as const;
/** The one terrain overlay on the map. */
export type MapOverlay =
	'none' | 'slope' | 'aspect' | 'bands' | 'sun' | 'wind' | 'problems' | 'concern';
export const MAP_OVERLAYS: readonly MapOverlay[] = [
	'none',
	'slope',
	'aspect',
	'bands',
	'sun',
	'wind',
	'problems',
	'concern'
] as const;
/** Things drawn on top that can each be on or off. */
export type MapFeature = 'runs' | 'peaks' | 'contours' | 'zones';
export const MAP_FEATURES: readonly MapFeature[] = ['runs', 'peaks', 'contours', 'zones'] as const;
export type MapShade = 'off' | 'light' | 'strong';

function load<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
	try {
		const v = localStorage.getItem(key);
		return v !== null && (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
	} catch {
		return fallback;
	}
}

function read(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

/** The weather layer, from before it had its own setting (precipitation on/off + mode). */
function loadWeather(): MapWeather {
	const v = read('sw.mapWeather');
	if (v !== null && (MAP_WEATHER as readonly string[]).includes(v)) return v as MapWeather;
	if (read('sw.mapPrecip') === 'off') return 'off';
	return read('sw.mapMode') === 'totals' ? 'totals' : 'radar';
}

function loadFeatures(): Set<MapFeature> {
	const v = read('sw.mapFeatures');
	if (v === null) {
		// Before: only ski runs could be switched off.
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- replaced wholesale on change
		const all = new Set<MapFeature>(['runs', 'peaks', 'contours']);
		if (read('sw.mapPistes') === 'off') all.delete('runs');
		return all;
	}
	return new Set(
		v.split(',').filter((f): f is MapFeature => (MAP_FEATURES as readonly string[]).includes(f))
	);
}

function save(key: string, value: string): void {
	try {
		localStorage.setItem(key, value);
	} catch {
		// private window or blocked storage: the choice just won't persist
	}
}

class Prefs {
	units = $state<UnitSystem>(load('sw.units', ['imperial', 'metric'] as const, 'imperial'));
	theme = $state<Theme>(load('sw.theme', ['auto', 'light', 'dark'] as const, 'auto'));
	themeFamily = $state<ThemeFamily>(load('sw.themeFamily', THEME_FAMILIES, 'sky'));
	motion = $state<Motion>(load('sw.motion', ['full', 'subtle', 'off'] as const, 'full'));
	/** The day-scrubbing strip under the forecast chart. */
	showTimeline = $state<'on' | 'off'>(load('sw.showTimeline', ['on', 'off'] as const, 'on'));
	band = $state<BandName>(load('sw.band', ['base', 'mid', 'summit'] as const, 'mid'));
	mapWeather = $state<MapWeather>(loadWeather());
	mapOverlay = $state<MapOverlay>(load('sw.mapOverlay', MAP_OVERLAYS, 'none'));
	mapFeatures = $state<Set<MapFeature>>(loadFeatures());
	mapShade = $state<MapShade>(load('sw.mapShade', ['off', 'light', 'strong'] as const, 'light'));
	mapTerrain = $state<'on' | 'off'>(load('sw.mapTerrain', ['on', 'off'] as const, 'off'));
	/** The concern index's warning has been read and accepted on this device. */
	concernAck = $state<boolean>(read('sw.concernAck') === '1');
	mapBase = $state<'topo' | 'satellite'>(
		load('sw.mapBase', ['topo', 'satellite'] as const, 'topo')
	);

	/** Overview order on phones: the order set on the Manage page, or most snow first. */
	sort = $state<'mine' | 'snow'>(load('sw.sort', ['mine', 'snow'] as const, 'mine'));

	setSort(s: 'mine' | 'snow') {
		this.sort = s;
		save('sw.sort', s);
	}

	setUnits(u: UnitSystem) {
		this.units = u;
		save('sw.units', u);
	}

	setTheme(t: Theme) {
		this.theme = t;
		save('sw.theme', t);
	}

	setThemeFamily(f: ThemeFamily) {
		this.themeFamily = f;
		save('sw.themeFamily', f);
	}

	setMotion(m: Motion) {
		this.motion = m;
		save('sw.motion', m);
	}

	setShowTimeline(on: boolean) {
		this.showTimeline = on ? 'on' : 'off';
		save('sw.showTimeline', this.showTimeline);
	}

	setBand(b: BandName) {
		this.band = b;
		save('sw.band', b);
	}

	setMapWeather(w: MapWeather) {
		this.mapWeather = w;
		save('sw.mapWeather', w);
	}

	setMapOverlay(o: MapOverlay) {
		this.mapOverlay = o;
		save('sw.mapOverlay', o);
	}

	setMapFeature(f: MapFeature, on: boolean) {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- replaced wholesale on change
		const next = new Set(this.mapFeatures);
		if (on) next.add(f);
		else next.delete(f);
		this.mapFeatures = next;
		save('sw.mapFeatures', [...next].join(','));
	}

	setMapShade(s: MapShade) {
		this.mapShade = s;
		save('sw.mapShade', s);
	}

	setMapBase(base: 'topo' | 'satellite') {
		this.mapBase = base;
		save('sw.mapBase', base);
	}

	acceptConcern() {
		this.concernAck = true;
		save('sw.concernAck', '1');
	}

	setMapTerrain(on: boolean) {
		this.mapTerrain = on ? 'on' : 'off';
		save('sw.mapTerrain', this.mapTerrain);
	}
}

export const prefs = new Prefs();
