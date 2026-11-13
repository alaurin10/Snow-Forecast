// The desktop rail over the full-window map: open (the whole rail floats over the map's
// left side) or folded to a small button, remembered in this browser. The map keeps its
// controls and its centre clear of whichever is showing.

/** Where the open rail ends, from the window's left edge: 14 px margin, 248 px rail, 10 px gap. */
export const RAIL_OPEN_INSET = 272;
/** Folded, the button heads the map's own column of buttons (10 px in, 40 px wide), so
 *  nothing moves right for it; the column starts this much lower instead. */
export const RAIL_FOLDED_INSET = 0;
export const RAIL_FOLDED_DROP = 48;

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
