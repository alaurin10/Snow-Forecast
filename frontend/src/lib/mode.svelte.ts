// Light or dark. Light and Dark are what they say. Auto follows the device and, with Live
// Sky, also goes dark from dusk until dawn, so text stays readable on a night sky.
// static/theme-init.js reads the hint saved here (`sw.skyDark`) to start dark at night.
import { prefs } from './prefs.svelte';
import { skyState } from './skystate.svelte';

/** How long the saved night hint is trusted when the app next opens. */
export const SKY_DARK_TTL_MS = 2 * 3600e3;

class ColorMode {
	/** The device asks for dark (prefers-color-scheme). The layout keeps this in step. */
	systemDark = $state(
		typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-color-scheme: dark)').matches
	);

	readonly dark: boolean = $derived(
		prefs.theme === 'dark' ||
			(prefs.theme === 'auto' &&
				(this.systemDark || (prefs.themeFamily === 'sky' && skyState.dark)))
	);
}

export const colorMode = new ColorMode();

/** Remember whether the live sky is dark now, for the next start (see theme-init.js). */
export function saveSkyDark(dark: boolean, at = Date.now()): void {
	try {
		localStorage.setItem('sw.skyDark', `${dark ? 1 : 0}:${at}`);
	} catch {
		// blocked storage: the next start just begins in the device's mode
	}
}
