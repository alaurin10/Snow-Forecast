// Generated from backend/snowwatch/api/models.py by `npm run types`. Do not edit.

/**
 * Every response shape, exported as one JSON Schema for the TypeScript types.
 */
export interface ApiTypes {
	admin_locations: Location[];
	avalanche: {
		[k: string]: AvalancheView;
	};
	budget: BudgetOut;
	catalog: CatalogItem[];
	job: JobOut;
	locations: LocationSummary[];
	lookups: LookupStatus;
	me: Me;
	overview: OverviewRow[];
	plan: PlanOut;
	resolve_in: ResolveIn;
	resolve_out: ResolveOut;
	runs: RunOut[];
	save: SaveOut;
	snapshot: Snapshot;
	status: StatusOut;
	trend: TrendOut;
	verification: VerificationOut;
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
	webcams?: Webcam[];
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
 * via the `definition` "Webcam".
 */
export interface Webcam {
	image_url?: string | null;
	name: string;
	url: string;
}
/**
 * What the app may show right now.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "AvalancheView".
 */
export interface AvalancheView {
	doc: AvalancheDoc | null;
	location_id: string;
	status: 'current' | 'expired' | 'no_rating' | 'none';
	today_max: number | null;
}
/**
 * One location's forecast, normalised from either provider.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "AvalancheDoc".
 */
export interface AvalancheDoc {
	center: string | null;
	center_id: string | null;
	days?: AvyDay[];
	expires_at: string | null;
	issued_at: string | null;
	link: string | null;
	off_season?: boolean;
	problems?: AvyProblem[];
	provider: string;
	summary?: string | null;
	zone: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "AvyDay".
 */
export interface AvyDay {
	alpine: number | null;
	below: number | null;
	date: string;
	treeline: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "AvyProblem".
 */
export interface AvyProblem {
	aspects?: string[];
	elevations?: string[];
	likelihood?: string | null;
	name: string;
	size?: string | null;
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
	best_day?: BestDay | null;
	country: string;
	d6_10_cm?: number | null;
	danger?: DangerChip | null;
	flags?: Flag[];
	generated_at?: string | null;
	id: string;
	kind: string;
	last24_cm?: number | null;
	lat?: number | null;
	lon?: number | null;
	name: string;
	next5_cm?: number | null;
	next5_p10_cm?: number | null;
	next5_p90_cm?: number | null;
	periods?: OverviewPeriod[];
	powder_dates?: string[];
	region: string;
	run_id?: number | null;
	snow_depth_cm?: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "BestDay".
 */
export interface BestDay {
	date: string;
	label: string;
	rating: string;
	score: number;
}
/**
 * The highest avalanche rating for a day, when the forecast is current.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "DangerChip".
 */
export interface DangerChip {
	level: number | null;
	status: string;
}
/**
 * Something worth a look (section 4.7 of the plan). The browser words it in your units.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Flag".
 */
export interface Flag {
	date?: string | null;
	detail?: string | null;
	first_run?: number | null;
	model?: string | null;
	period_key?: string | null;
	severity: string;
	type: string;
	value?: number | null;
	value2?: number | null;
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
 * Plan a day: every location on one date.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PlanOut".
 */
export interface PlanOut {
	date: string;
	dates: PlanDate[];
	rows: PlanRow[];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PlanDate".
 */
export interface PlanDate {
	date: string;
	label: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PlanRow".
 */
export interface PlanRow {
	danger: DangerChip;
	day: DayOut | null;
	id: string;
	kind: string;
	name: string;
	region: string;
}
/**
 * One day for Plan a day and the ski-day rating. Snow and temperatures at mid.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "DayOut".
 */
export interface DayOut {
	cloud_low: number | null;
	date: string;
	day_cm: number | null;
	gust_max_kmh: number | null;
	label: string;
	overnight_cm: number | null;
	quality: string | null;
	rain_mm: number | null;
	rating: string | null;
	reasons?: Reason[];
	score: number | null;
	tmax_c: number | null;
	tmin_c: number | null;
	vis_min_m: number | null;
	wcode: number | null;
}
/**
 * Why a day got its rating. The browser words it in the viewer's units.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Reason".
 */
export interface Reason {
	code: string;
	value?: number | null;
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
	backcountry?: BackcountryOut | null;
	bands: BandOut[];
	basis_switch: string | null;
	daily: DailyRow[];
	days?: DayOut[];
	depth_method: string;
	ensembles: {
		[k: string]: number;
	};
	flags?: Flag[];
	generated_at: string;
	location: LocationMeta;
	models: string[];
	now: string;
	ridge?: RidgeOut | null;
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
 * via the `definition` "BackcountryOut".
 */
export interface BackcountryOut {
	refreeze: RefreezeNight[];
	rose: RoseOut[];
	sky: SkyDay[];
	storm: StormOut;
	warming: WarmingOut;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "RefreezeNight".
 */
export interface RefreezeNight {
	band: string;
	clear_frac: number | null;
	date: string;
	low_c: number | null;
	status: string;
}
/**
 * Where wind would drift new snow: snowfall × ridge wind per sector (N first, clockwise).
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "RoseOut".
 */
export interface RoseOut {
	label: string;
	loading: string[];
	mean_kmh: number | null;
	sectors: number[];
	snow_cm: number;
	wind_from: string | null;
	window: string;
}
/**
 * Daytime sky at the summit: mean cloud per layer (%) and the lowest visibility.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SkyDay".
 */
export interface SkyDay {
	cloud_high: number | null;
	cloud_low: number | null;
	cloud_mid: number | null;
	date: string;
	vis_min_m: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "StormOut".
 */
export interface StormOut {
	next48_cm: number | null;
	past72_cm: number | null;
}
/**
 * The biggest 24 h warming in the next 72 h, and rain falling on snow.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "WarmingOut".
 */
export interface WarmingOut {
	fl_rise_at: string | null;
	fl_rise_m: number | null;
	rain_on_snow_mm: number | null;
	temp_rise_at: string | null;
	temp_rise_c: number | null;
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
	webcams?: Webcam[];
}
/**
 * Free-air wind at summit height, aligned with each band's `hourly.t`.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "RidgeOut".
 */
export interface RidgeOut {
	dir: (number | null)[];
	kmh: (number | null)[];
	level_m: number;
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
	distance_km?: number | null;
	elev_m: number | null;
	name: string | null;
	network?: string;
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
 * The Status page: per-source health, runs, usage and data age.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "StatusOut".
 */
export interface StatusOut {
	budget: number;
	locations: LocationAge[];
	runs: RunOut[];
	sources: SourceRow[];
	weight_today: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "LocationAge".
 */
export interface LocationAge {
	flags: number;
	generated_at: string | null;
	id: string;
	name: string;
	station: string | null;
	station_obs_time: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SourceRow".
 */
export interface SourceRow {
	calls_today: number;
	errors_today: number;
	last_error: string | null;
	last_error_at: string | null;
	last_ok_at: string | null;
	source: string;
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
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "VerificationOut".
 */
export interface VerificationOut {
	band_elev_m: number;
	location_id: string;
	n_days: number;
	needs_days: number;
	pairs: VerificationPair[];
	ready: boolean;
	rows: VerificationRow[];
	since: string | null;
	station: string | null;
	station_elev_m: number | null;
	station_name: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "VerificationPair".
 */
export interface VerificationPair {
	cons_cm: number | null;
	cons_slr_cm: number | null;
	date: string;
	from_swe: boolean;
	observed_cm: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "VerificationRow".
 */
export interface VerificationRow {
	bias_cm: number | null;
	false_alarms: number;
	hits: number;
	mae_cm: number | null;
	misses: number;
	n: number;
	source: string;
}
