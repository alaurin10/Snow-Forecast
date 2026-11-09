// Whether the window is phone-sized. Phones get their own layouts (a chart-first
// location page, list rows instead of cards and tables), not a squeezed desktop page.
const PHONE = '(max-width: 640px)';

class Viewport {
	phone = $state(false);

	constructor() {
		// matchMedia is missing in some test environments; they render the desktop layout.
		if (typeof window === 'undefined' || !window.matchMedia) return;
		const m = window.matchMedia(PHONE);
		this.phone = m.matches;
		m.addEventListener('change', (e) => (this.phone = e.matches));
	}
}

export const viewport = new Viewport();
