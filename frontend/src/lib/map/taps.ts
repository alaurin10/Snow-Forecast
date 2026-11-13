// Telling a tap on the map from the start of a double tap, on touch screens.
//
// A double tap zooms the map in, and a double tap held and dragged zooms with one finger
// (MapLibre's own gestures). Neither should open the map panel, so a tap waits a moment
// (TAP_WAIT_MS) before it counts, and a second touch in that moment calls it off. Pans
// and pinches are gestures too, never taps: they don't count towards a double tap, so the
// tap after one acts the first time.
//
// The browser's click for a tap can arrive late (after the next touch has begun, when the
// page is busy), so a click is judged by the touches around it, not by the order events
// arrive in.

/** How long a tap waits for a second one before it counts. */
export const TAP_WAIT_MS = 220;
/** MapLibre zooms on a second tap this soon after the first and this close to it. */
export const DOUBLE_TAP_MS = 500;
export const DOUBLE_TAP_PX = 30;
/** A finger that moves further than this is panning, not tapping. */
const MOVE_PX = 10;
/** A click this soon after a touch began came from the touch. */
const TOUCH_CLICK_MS = 1000;

interface Gesture {
	start: number;
	end: number | null;
	/** Panned, pinched, or more than one finger: not a tap. */
	moved: boolean;
	x: number;
	y: number;
}

export type TapVerdict = 'now' | 'wait' | 'drop';

export class TapGate {
	private gestures: Gesture[] = [];
	private current: Gesture | null = null;

	constructor(private now: () => number = () => Date.now()) {}

	/** A finger touched the map (`fingers` now on it). */
	start(x: number, y: number, fingers: number) {
		if (!this.current) {
			this.current = { start: this.now(), end: null, moved: false, x, y };
			this.gestures = [...this.gestures.slice(-3), this.current];
		}
		if (fingers > 1) this.current.moved = true;
	}

	move(x: number, y: number, fingers: number) {
		const g = this.current;
		if (!g) return;
		if (fingers > 1 || Math.hypot(x - g.x, y - g.y) > MOVE_PX) g.moved = true;
	}

	/** A finger lifted (`fingers` still on the map). */
	end(fingers: number) {
		if (!this.current || fingers > 0) return;
		this.current.end = this.now();
		this.current = null;
	}

	/**
	 * A click on the map: act on it now (a mouse), wait for a possible second tap, or drop
	 * it (part of a double tap).
	 */
	click(): TapVerdict {
		const last = this.gestures.at(-1);
		if (!last || this.now() - last.start > TOUCH_CLICK_MS) return 'now';
		// The tap this click is for: the latest finished touch that stayed put.
		let i = this.gestures.length - 1;
		while (i >= 0 && (this.gestures[i].end == null || this.gestures[i].moved)) i--;
		if (i < 0) return 'wait';
		const tap = this.gestures[i];
		// Another touch began before its click arrived.
		if (i < this.gestures.length - 1) return 'drop';
		// The second tap of a double tap (MapLibre zooms for it).
		const prev = this.gestures[i - 1];
		if (
			prev &&
			!prev.moved &&
			prev.end != null &&
			tap.start - prev.end < DOUBLE_TAP_MS &&
			Math.hypot(tap.x - prev.x, tap.y - prev.y) < DOUBLE_TAP_PX
		)
			return 'drop';
		return 'wait';
	}
}
