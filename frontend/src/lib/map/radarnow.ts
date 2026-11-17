// What radar says at a tapped spot, in a line: what's falling now and whether that changes
// within the nowcast's hour or so (backend/snowwatch/maps/point.py gives the frames).
import type { PointRate } from '../types.gen';

export interface RadarNow {
	/** "Light snow", "Heavy rain", "Dry". */
	now: string;
	/** "Starting about 3:40 PM", "Ending about 4:05 PM", or "". */
	change: string;
	/** No radar sees the spot well: what's shown is the forecast filling in. */
	filled: boolean;
}

/** Words for a rate band's floor (mm of water an hour ≈ cm of snow an hour). */
export function intensity(low: number): 'Light' | 'Moderate' | 'Heavy' {
	return low < 1 ? 'Light' : low < 4 ? 'Moderate' : 'Heavy';
}

const words = (r: PointRate) => (r.type ? `${intensity(r.low ?? 0)} ${r.type}` : 'Dry');

/**
 * The latest radar scan at the spot and the nowcast after it; null without a scan.
 * `clock` formats a time (Unix seconds) for the change.
 */
export function radarNow(rates: PointRate[], clock: (t: number) => string): RadarNow | null {
	const radar = rates.filter((r) => r.kind === 'radar');
	const last = radar.at(-1);
	if (!last) return null;
	const ahead = rates.filter((r) => r.kind === 'nowcast' && r.t > last.t);
	const turn = ahead.find((r) => !!r.type !== !!last.type);
	const change = turn ? `${turn.type ? 'Starting' : 'Ending'} about ${clock(turn.t)}` : '';
	return { now: words(last), change, filled: !!last.filled };
}
