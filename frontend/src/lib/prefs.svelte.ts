// Per-device viewer preferences, kept in localStorage (which can be missing
// or blocked, so every access is guarded).
import type { UnitSystem } from './units';

export type Theme = 'auto' | 'light' | 'dark';
export type BandName = 'base' | 'mid' | 'summit';
export type SortKey = 'next5' | 'd6_10' | 'last24' | 'name';
export type KindFilter = 'all' | 'resort' | 'backcountry';

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
	sort = $state<SortKey>(load('sw.sort', ['next5', 'd6_10', 'last24', 'name'] as const, 'next5'));
	kind = $state<KindFilter>(load('sw.kind', ['all', 'resort', 'backcountry'] as const, 'all'));

	setSort(s: SortKey) {
		this.sort = s;
		save('sw.sort', s);
	}

	setKind(k: KindFilter) {
		this.kind = k;
		save('sw.kind', k);
	}

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
}

export const prefs = new Prefs();
