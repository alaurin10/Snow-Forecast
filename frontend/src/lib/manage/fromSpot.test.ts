import { describe, expect, it } from 'vitest';
import { spotToResolve } from './fromSpot';

describe('spotToResolve', () => {
	it('makes three pins at the point with the bands’ elevations', () => {
		const q = new URLSearchParams({
			spot: '46.85,-121.76',
			name: '24 km SW of Crystal Mountain',
			elev: '2871,3768,4366'
		});
		expect(spotToResolve(q)).toEqual({
			kind: 'backcountry',
			name: '24 km SW of Crystal Mountain',
			pins: [
				{ band: 'base', lat: 46.85, lon: -121.76, elev_m: 2871 },
				{ band: 'mid', lat: 46.85, lon: -121.76, elev_m: 3768 },
				{ band: 'summit', lat: 46.85, lon: -121.76, elev_m: 4366 }
			]
		});
	});
	it('ignores anything incomplete or odd', () => {
		expect(spotToResolve(new URLSearchParams())).toBeNull();
		expect(spotToResolve(new URLSearchParams({ spot: '1,2', elev: '3,2,1' }))).toBeNull();
		expect(spotToResolve(new URLSearchParams({ spot: '91,2', elev: '1,2,3' }))).toBeNull();
		expect(spotToResolve(new URLSearchParams({ spot: 'a,b', elev: '1,2,3' }))).toBeNull();
	});
});
