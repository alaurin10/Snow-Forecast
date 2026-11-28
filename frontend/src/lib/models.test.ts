import { describe, expect, it } from 'vitest';
import { modelRunsLine, runHour } from './models';

describe('model runs', () => {
	it('names each run by its UTC hour', () => {
		expect(runHour('2026-12-01T06:00:00+00:00')).toBe('06z');
	});

	it('lists runs in the snapshot’s model order', () => {
		const runs = {
			ncep_hrrr_conus: '2026-12-01T22:00:00+00:00',
			gfs_seamless: '2026-12-01T18:00:00+00:00',
			ecmwf_ifs025: '2026-12-01T12:00:00+00:00'
		};
		expect(modelRunsLine(runs, ['gfs_seamless', 'ecmwf_ifs025', 'ncep_hrrr_conus'])).toBe(
			'GFS 18z · ECMWF 12z · HRRR 22z'
		);
		expect(modelRunsLine({}, ['gfs_seamless'])).toBe('');
		expect(modelRunsLine(undefined, [])).toBe('');
	});
});
