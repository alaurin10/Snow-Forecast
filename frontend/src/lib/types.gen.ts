// Generated from backend/snowwatch/api/models.py by `npm run types`. Do not edit.

/**
 * Every response shape, exported as one JSON Schema for the TypeScript types.
 */
export interface ApiTypes {
	locations: LocationSummary[];
	runs: RunOut[];
	snapshot: Snapshot;
	trend: TrendOut;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "LocationSummary".
 */
export interface LocationSummary {
	alerts?: number;
	bands: BandSummary[];
	country: string;
	d6_10_cm?: number | null;
	generated_at?: string | null;
	id: string;
	kind: string;
	last24_cm?: number | null;
	name: string;
	next5_cm?: number | null;
	next5_p10_cm?: number | null;
	next5_p90_cm?: number | null;
	region: string;
	run_id?: number | null;
	tz: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "BandSummary".
 */
export interface BandSummary {
	band: string;
	elev_m: number;
	label: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "RunOut".
 */
export interface RunOut {
	api_weight: number;
	errors: string[];
	finished_at: string | null;
	id: number;
	kind: string;
	started_at: string;
	status: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Snapshot".
 */
export interface Snapshot {
	alerts?: Alert[];
	avalanche?: {
		[k: string]: unknown;
	} | null;
	bands: BandOut[];
	basis_switch: string | null;
	daily: DailyRow[];
	depth_method: string;
	ensembles: {
		[k: string]: number;
	};
	flags?: {
		[k: string]: unknown;
	}[];
	generated_at: string;
	location: LocationMeta;
	models: string[];
	now: string;
	run_id: number | null;
	snotel?: Snotel | null;
	sun: SunDay[];
	version?: number;
	warnings?: string[];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Alert".
 */
export interface Alert {
	ends: string | null;
	event: string | null;
	headline: string | null;
	onset: string | null;
	severity: string | null;
	url: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "BandOut".
 */
export interface BandOut {
	band: string;
	elev_m: number;
	hourly: HourlyOut;
	label: string;
	periods: PeriodOut[];
	stats: ElevationOut;
	windows: {
		[k: string]: WindowOut;
	};
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "HourlyOut".
 */
export interface HourlyOut {
	cloud: (number | null)[];
	cloud_high: (number | null)[];
	cloud_low: (number | null)[];
	cloud_mid: (number | null)[];
	fl_hi: (number | null)[];
	fl_lo: (number | null)[];
	fl_m: (number | null)[];
	gust_kmh: (number | null)[];
	is_day: (number | null)[];
	pop: (number | null)[];
	ptype: string[];
	rain_mm: (number | null)[];
	snow_cm: (number | null)[];
	snow_level_m: (number | null)[];
	swe_mm: (number | null)[];
	t: string[];
	temp_c: (number | null)[];
	temp_hi: (number | null)[];
	temp_lo: (number | null)[];
	visibility_m: (number | null)[];
	water_mm: (number | null)[];
	wcode: (number | null)[];
	wdir: (number | null)[];
	wind_hi: (number | null)[];
	wind_kmh: (number | null)[];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PeriodOut".
 */
export interface PeriodOut {
	basis: string | null;
	blend_cm: number | null;
	cloud_mean: number | null;
	date: string;
	ens: EnsStats | null;
	gust_max_kmh: number | null;
	hours: number;
	key: string;
	kind: string;
	label: string;
	models: {
		[k: string]: number | null;
	};
	nmodels: number;
	pop_max: number | null;
	ptype: string;
	quality: string | null;
	rain_mm: number | null;
	slr: number | null;
	snow_cm: number | null;
	snow_cm_raw: number | null;
	snow_cm_slr: number | null;
	snow_level_min_m: number | null;
	start: string;
	swe_mm: number | null;
	tmax_c: number | null;
	tmin_c: number | null;
	water_mm: number | null;
	wind_max_kmh: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "EnsStats".
 */
export interface EnsStats {
	estimated?: boolean;
	mean: number | null;
	n: number;
	p10: number | null;
	p50: number | null;
	p90: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ElevationOut".
 */
export interface ElevationOut {
	d6_10_cm: number | null;
	last24_cm: number | null;
	next24_cm: number | null;
	next5_cm: number | null;
	temp_now_c: number | null;
	tmax24_c: number | null;
	tmin24_c: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "WindowOut".
 */
export interface WindowOut {
	ens: EnsStats | null;
	ens_slr: EnsStats | null;
	members_cm?: number[];
	members_cm_slr?: number[];
	scale?: number | null;
	snow_cm: number | null;
	snow_cm_raw: number | null;
	snow_cm_slr: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "DailyRow".
 */
export interface DailyRow {
	date: string;
	ens_cum: {
		[k: string]: DailyEns | null;
	};
	ens_day: DailyEns | null;
	hours: number;
	models: {
		[k: string]: number | null;
	};
	models_cum: {
		[k: string]: number | null;
	};
	pooled_cum: DailyEns | null;
	pooled_tail: string | null;
	snow_level_min_m: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "DailyEns".
 */
export interface DailyEns {
	n: number;
	p10: number | null;
	p50: number | null;
	p90: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "LocationMeta".
 */
export interface LocationMeta {
	country: string;
	id: string;
	kind: string;
	lat: number;
	links: {
		[k: string]: string;
	};
	lon: number;
	name: string;
	region: string;
	tz: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Snotel".
 */
export interface Snotel {
	change24_cm: number | null;
	change72_cm: number | null;
	daily: SnotelDay[];
	depth_cm: number | null;
	elev_m: number | null;
	name: string | null;
	obs_time: string | null;
	swe_mm: number | null;
	triplet: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SnotelDay".
 */
export interface SnotelDay {
	date: string;
	depth_cm: number | null;
	precip_mm: number | null;
	swe_mm: number | null;
	temp_c: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SunDay".
 */
export interface SunDay {
	date: string;
	daylight_s: number | null;
	sunrise: string | null;
	sunset: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "TrendOut".
 */
export interface TrendOut {
	location_id: string;
	runs: TrendRun[];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "TrendRun".
 */
export interface TrendRun {
	daily: {
		[k: string]: number | null;
	};
	issued_at: string;
	next5_cm: number | null;
	run_id: number;
}
