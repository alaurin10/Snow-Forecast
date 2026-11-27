// "Save as location" on a spot's page opens Manage at /admin?spot=lat,lon&name=…&elev=b,m,s:
// a backcountry location with the spot's point and its three bands' elevations, ready for
// the usual auto-detect and review.
import type { ResolveIn } from '../types.gen';

export function spotToResolve(params: URLSearchParams): ResolveIn | null {
	const at = (params.get('spot') ?? '').split(',').map(Number);
	const elev = (params.get('elev') ?? '').split(',').map(Number);
	if (at.length !== 2 || elev.length !== 3) return null;
	const [lat, lon] = at;
	if (![lat, lon, ...elev].every(Number.isFinite)) return null;
	if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
	if (!(elev[0] < elev[1] && elev[1] < elev[2])) return null;
	const bands = ['base', 'mid', 'summit'] as const;
	return {
		kind: 'backcountry',
		name: (params.get('name') ?? '').slice(0, 80),
		pins: bands.map((band, i) => ({ band, lat, lon, elev_m: elev[i] })) as ResolveIn['pins']
	};
}
