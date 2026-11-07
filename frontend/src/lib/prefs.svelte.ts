// Per-device viewer preferences, kept in localStorage (which can be missing
// or blocked, so every access is guarded).
import type { UnitSystem } from './units';

export type Theme = 'auto' | 'light' | 'dark';
export type BandName = 'base' | 'mid' | 'summit';
export type MapLayer = 'radar' | 'forecast' | 'off';
export type Basemap = 'muted' | 'color';

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
	band = $state<BandName>(load('sw.band', ['base', 'mid', 'summit'] as const, 'mid'));
	mapLayer = $state<MapLayer>(load('sw.mapLayer', ['radar', 'forecast', 'off'] as const, 'radar'));
	basemap = $state<Basemap>(load('sw.basemap', ['muted', 'color'] as const, 'muted'));

	setUnits(u: UnitSystem) {
		this.units = u;
		save('sw.units', u);
	}

	setTheme(t: Theme) {
		this.theme = t;
		save('sw.theme', t);
	}

	setBand(b: BandName) {
		this.band = b;
		save('sw.band', b);
	}

	setMapLayer(m: MapLayer) {
		this.mapLayer = m;
		save('sw.mapLayer', m);
	}

	setBasemap(b: Basemap) {
		this.basemap = b;
		save('sw.basemap', b);
	}
}

export const prefs = new Prefs();
