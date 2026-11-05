// Generated from backend/snowwatch/api/models.py by `npm run types`. Do not edit.

/**
 * Every response shape, exported as one JSON Schema for the TypeScript types.
 */
export interface ApiTypes {
	admin_locations: Location[];
	budget: BudgetOut;
	catalog: CatalogItem[];
	job: JobOut;
	locations: LocationSummary[];
	lookups: LookupStatus;
	me: Me;
	overview: OverviewRow[];
	resolve_in: ResolveIn;
	resolve_out: ResolveOut;
	runs: RunOut[];
	save: SaveOut;
	snapshot: Snapshot;
	trend: TrendOut;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Location".
 */
export interface Location {
	active?: boolean;
	avy?: AvyRef | null;
	bands: Band[];
	catalog_ref?: string | null;
	country: 'US' | 'CA';
	id: string;
	kind: 'resort' | 'backcountry';
	links?: {
		[k: string]: string;
	};
	name: string;
	nws_office?: string | null;
	radar_station?: string | null;
	region?: string;
	snotel?: string | null;
	sort_order?: number;
	tz?: string | null;
}
/**
 * Where to find the avalanche forecast. Canadian zones are looked up by point.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "AvyRef".
 */
export interface AvyRef {
	center_id?: string | null;
	provider: 'nac' | 'avcan';
	zone_id?: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Band".
 */
export interface Band {
	band: 'base' | 'mid' | 'summit';
	elev_m: number;
	label: string;
	lat: number;
	lon: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "BudgetOut".
 */
export interface BudgetOut {
	active: number;
	budget: number;
	max_locations: number;
	per_location: {
		[k: string]: number;
	};
	total: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "CatalogItem".
 */
export interface CatalogItem {
	country: string | null;
	id: string;
	lat: number;
	lon: number;
	max_elev_m: number | null;
	min_elev_m: number | null;
	name: string;
	region: string | null;
	website: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "JobOut".
 */
export interface JobOut {
	created_at: string;
	error: string | null;
	finished_at: string | null;
	id: number;
	kind: string;
	location_id: string | null;
	status: string;
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
 * via the `definition` "LookupStatus".
 */
export interface LookupStatus {
	avy_zones: number;
	ski_areas: number;
	snotel_stations: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Me".
 */
export interface Me {
	email: string | null;
	is_owner: boolean;
}
/**
 * One location on the Overview and Calendar pages (mid band).
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "OverviewRow".
 */
export interface OverviewRow {
	alerts?: string[];
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
	periods?: OverviewPeriod[];
	region: string;
	run_id?: number | null;
	snow_depth_cm?: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "OverviewPeriod".
 */
export interface OverviewPeriod {
	date: string;
	key: string;
	kind: string;
	label: string;
	snow_cm: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ResolveIn".
 */
export interface ResolveIn {
	catalog_id?: string | null;
	kind?: 'resort' | 'backcountry';
	name?: string;
	/**
	 * @minItems 1
	 */
	pins: [Pin, ...Pin[]];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Pin".
 */
export interface Pin {
	band: 'base' | 'mid' | 'summit';
	elev_m?: number | null;
	label?: string | null;
	lat: number;
	lon: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ResolveOut".
 */
export interface ResolveOut {
	avy: AvyRef | null;
	avy_name: string | null;
	bands: Band[];
	country: 'US' | 'CA';
	id: string;
	kind: string;
	links: {
		[k: string]: string;
	};
	name: string;
	nws_office: string | null;
	radar_station: string | null;
	region: string;
	snotel: string | null;
	snotel_candidates: SnotelCandidate[];
	tz: string | null;
	warnings: string[];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SnotelCandidate".
 */
export interface SnotelCandidate {
	distance_km: number;
	elev_m: number | null;
	name: string;
	triplet: string;
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
 * via the `definition` "SaveOut".
 */
export interface SaveOut {
	job_id: number | null;
	location: Location;
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
