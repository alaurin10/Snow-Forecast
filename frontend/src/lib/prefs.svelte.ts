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

function load<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
	try {
		const v = localStorage.getItem(key);
		return v !== null && (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
	} catch {
		return fallback;
	}
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
	mapPrecip = $state<'on' | 'off'>(load('sw.mapPrecip', ['on', 'off'] as const, 'on'));
	mapPistes = $state<'on' | 'off'>(load('sw.mapPistes', ['on', 'off'] as const, 'on'));
	mapTerrain = $state<'on' | 'off'>(load('sw.mapTerrain', ['on', 'off'] as const, 'off'));
	mapMode = $state<'timeline' | 'totals'>(
		load('sw.mapMode', ['timeline', 'totals'] as const, 'timeline')
	);
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

	setMapPrecip(on: boolean) {
		this.mapPrecip = on ? 'on' : 'off';
		save('sw.mapPrecip', this.mapPrecip);
	}

	setMapMode(mode: 'timeline' | 'totals') {
		this.mapMode = mode;
		save('sw.mapMode', mode);
	}

	setMapBase(base: 'topo' | 'satellite') {
		this.mapBase = base;
		save('sw.mapBase', base);
	}

	setMapTerrain(on: boolean) {
		this.mapTerrain = on ? 'on' : 'off';
		save('sw.mapTerrain', this.mapTerrain);
	}

	setMapPistes(on: boolean) {
		this.mapPistes = on ? 'on' : 'off';
		save('sw.mapPistes', this.mapPistes);
	}
}

export const prefs = new Prefs();
