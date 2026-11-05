// Display names for model and ensemble identifiers, and each model's fixed
// categorical color slot (identity follows the model, never its rank).

export const MODEL_NAMES: Record<string, string> = {
	gfs_seamless: 'GFS',
	ecmwf_ifs025: 'ECMWF',
	gem_seamless: 'GEM',
	icon_seamless: 'ICON',
	ncep_hrrr_conus: 'HRRR',
	ncep_nbm_conus: 'NBM',
	gem_hrdps_continental: 'HRDPS'
};

export const ENSEMBLE_NAMES: Record<string, string> = {
	gfs_seamless: 'GEFS',
	ecmwf_ifs025: 'ECMWF ENS',
	gem_global: 'GEPS'
};

const SLOT: Record<string, number> = {
	gfs_seamless: 1,
	ecmwf_ifs025: 2,
	gem_seamless: 3,
	icon_seamless: 4,
	ncep_hrrr_conus: 5,
	gem_hrdps_continental: 5,
	ncep_nbm_conus: 6
};

export const modelColor = (m: string): string => `var(--s${SLOT[m] ?? 7})`;
