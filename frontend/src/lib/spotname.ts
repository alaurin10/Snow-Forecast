// A spot's name in the viewer's units. The server names a spot after the terrain (the
// nearest named peak: "Mount Stuart", or "1.2 km NE of Mount Stuart") and sends the peak,
// its distance and direction, so the distance can be worded in miles or kilometres.
import type { Snapshot } from './types.gen';
import { distance, type UnitSystem } from './units';

export function spotTitle(snap: Snapshot, units: UnitSystem): string {
	const peak = snap.spot?.peak;
	if (!peak) return snap.location.name;
	if (!peak.bearing) return peak.name;
	return `${distance(peak.km, units)} ${peak.bearing} of ${peak.name}`;
}
