// The three layout tiers. Phones get their own layouts (a chart-first location page,
// list rows instead of tables), desktops get the left rail and wide tables, and tablets
// use the touch layouts with room for two-up cards. Keep these widths in step with the
// media queries in the components: phone ≤ 640 px, tablet 641–1099 px, desktop ≥ 1100 px.
export const PHONE_MAX = 640;
export const DESKTOP_MIN = 1100;

class Viewport {
	phone = $state(false);
	desktop = $state(false);

	/** Between phone and desktop. */
	get tablet(): boolean {
		return !this.phone && !this.desktop;
	}

	constructor() {
		// matchMedia is missing in some test environments; they render the desktop layout.
		if (typeof window === 'undefined' || !window.matchMedia) {
			this.desktop = true;
			return;
		}
		const phone = window.matchMedia(`(max-width: ${PHONE_MAX}px)`);
		const desktop = window.matchMedia(`(min-width: ${DESKTOP_MIN}px)`);
		this.phone = phone.matches;
		this.desktop = desktop.matches;
		phone.addEventListener('change', (e) => (this.phone = e.matches));
		desktop.addEventListener('change', (e) => (this.desktop = e.matches));
	}
}

export const viewport = new Viewport();
