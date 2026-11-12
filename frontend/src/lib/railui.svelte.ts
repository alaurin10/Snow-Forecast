// The desktop rail over the full-window map: open (the whole rail floats over the map's
// left side) or folded to a small button, remembered in this browser. The map keeps its
// controls and its centre clear of whichever is showing.

/** Where the open rail ends, from the window's left edge: 14 px margin, 248 px rail, 10 px gap. */
export const RAIL_OPEN_INSET = 272;
/** Where the folded button ends: 14 px margin, 44 px button, 10 px gap. */
export const RAIL_FOLDED_INSET = 68;

function read(): boolean {
	try {
		return localStorage.getItem('sw.railFolded') === '1';
	} catch {
		return false;
	}
}

class RailUi {
	/** The rail is folded to a button (on the map page). */
	folded = $state(read());

	setFolded(on: boolean) {
		this.folded = on;
		try {
			localStorage.setItem('sw.railFolded', on ? '1' : '0');
		} catch {
			// blocked storage: the choice just won't persist
		}
	}
}

export const railUi = new RailUi();
