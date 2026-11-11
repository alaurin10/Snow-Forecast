// The avalanche layers' controls show ratings as published, say why a layer is empty,
// and always carry the concern index's fixed caption.
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { AvalancheView, ZoneFeature } from '../types.gen';
import AvalancheControls from './AvalancheControls.svelte';
import { concernSetup } from './avalanche';
import type { WindSource } from './windsource';

const CAPTION =
	"Experimental estimate from the bulletin and terrain shape. Not a forecast. Doesn't show runouts or slopes above you.";

function zone(view: Partial<AvalancheView> = {}, problems = true): ZoneFeature {
	return {
		id: 'nac:3023',
		geometry: { type: 'MultiPolygon', coordinates: [] },
		properties: {
			id: 'nac:3023',
			tz: 'America/Los_Angeles',
			today: '2026-12-10',
			view: {
				location_id: 'nac:3023',
				status: 'current',
				today_max: 3,
				doc: {
					provider: 'nac',
					center: 'Northwest Avalanche Center',
					center_id: 'NWAC',
					zone: 'West Slopes South',
					link: null,
					issued_at: null,
					expires_at: null,
					days: [{ date: '2026-12-10', alpine: 3, treeline: 2, below: 1 }],
					problems: problems
						? [
								{ name: 'Wind Slab', aspects: ['N', 'NE'], elevations: ['alpine'] },
								{ name: 'Wet Loose', aspects: ['S'], elevations: ['below'] }
							]
						: []
				},
				...view
			}
		}
	};
}
const treeline = { band: [1200, 1550] as [number, number], name: 'NWAC', own: false };
const base = {
	units: 'metric' as const,
	zonesState: 'ready' as const,
	treeline,
	tooFar: false,
	state: 'idle' as const,
	pick: 'all' as const,
	slopeMin: 30,
	caption: CAPTION
};

afterEach(cleanup);

describe('avalanche controls', () => {
	it("shows today's ratings, the problems and the treeline used", () => {
		render(AvalancheControls, { ...base, overlay: 'problems', zone: zone() });
		expect(screen.getByText('NWAC · West Slopes South', { exact: false })).toBeTruthy();
		expect(screen.getByTitle('Alpine: 3 Considerable')).toBeTruthy();
		expect(screen.getByRole('button', { name: 'Wind Slab' })).toBeTruthy();
		expect(screen.getByRole('button', { name: 'All' }).getAttribute('aria-pressed')).toBe('true');
		expect(screen.getByText(/Treeline taken as 1,200 m–1,550 m \(approximate\)/)).toBeTruthy();
	});

	it('says why the problems layer is empty', () => {
		const { unmount } = render(AvalancheControls, {
			...base,
			overlay: 'problems',
			zone: zone({ status: 'expired' })
		});
		expect(screen.getByText(/has expired/)).toBeTruthy();
		unmount();
		render(AvalancheControls, { ...base, overlay: 'problems', zone: zone({}, false) });
		expect(screen.getByText(/lists no avalanche problems today/)).toBeTruthy();
		cleanup();
		render(AvalancheControls, { ...base, overlay: 'problems', zone: null });
		expect(screen.getByText('No avalanche forecast zone here.')).toBeTruthy();
	});

	it('always carries the concern caption, and says how wind and sun count', () => {
		const wind: WindSource = {
			location: {
				id: 'crystal',
				name: 'Crystal Mountain',
				lat: 46.9,
				lon: -121.5,
				generated_at: 'x',
				roses: [],
				flags: []
			},
			km: 5,
			rose: {
				window: 'past48',
				sectors: [0, 0, 0, 0, 0, 1, 0, 0],
				snow_cm: 30,
				mean_kmh: 40,
				wind_from: 'SW',
				loading: ['NE'],
				label: ''
			},
			scale: 0.8
		};
		const setup = concernSetup(zone(), treeline, wind, 20);
		expect(setup.inputs).toMatchObject({ wind: true, windLoading: true, sun: true });
		render(AvalancheControls, {
			...base,
			overlay: 'concern',
			zone: zone(),
			concernWhy: setup.why,
			windNote: setup.windNote,
			sunNote: setup.sunNote
		});
		expect(screen.getByText(CAPTION, { exact: false })).toBeTruthy();
		expect(screen.getByText(/Loaded slopes count more/)).toBeTruthy();
		expect(screen.getByText(/a wet-snow problem is listed/)).toBeTruthy();
		expect(screen.getByText('Very high')).toBeTruthy();
		cleanup();
		const none = concernSetup(zone({ status: 'no_rating' }), treeline, null, 20);
		render(AvalancheControls, {
			...base,
			overlay: 'concern',
			zone: zone({ status: 'no_rating' }),
			concernWhy: none.why
		});
		expect(screen.getByText(/has no danger rating for today/)).toBeTruthy();
		expect(screen.getByText(CAPTION, { exact: false })).toBeTruthy();
		expect(screen.queryByText('Very high')).toBeNull();
	});
});
