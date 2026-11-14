// Generated from backend/snowwatch/api/models.py by `npm run types`. Do not edit.

/**
 * Every response shape, exported as one JSON Schema for the TypeScript types.
 */
export interface ApiTypes {
	admin_locations: Location[];
	ates: AtesOut;
	avalanche: {
		[k: string]: AvalancheView;
	};
	avalanche_zones: ZonesOut;
	budget: BudgetOut;
	catalog: CatalogItem[];
	job: JobOut;
	locations: LocationSummary[];
	lookups: LookupStatus;
	map_concern: ConcernOut;
	map_point: PointOut;
	map_stations: StationsOut;
	map_wind: MapWindOut;
	me: Me;
	meta: MetaOut;
	observations: ObsOut;
	overlay_files: OverlayFile[];
	overview: OverviewRow[];
	plan: PlanOut;
	resolve_in: ResolveIn;
	resolve_out: ResolveOut;
	runs: RunOut[];
	sat: SatOut;
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
 * Every ATES file the owner has supplied, as one collection.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "AtesOut".
 */
export interface AtesOut {
	features: AtesFeature[];
	files: OverlayFile[];
	type?: 'FeatureCollection';
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "AtesFeature".
 */
export interface AtesFeature {
	geometry: {
		[k: string]: unknown;
	};
	properties: AtesProps;
	type?: 'Feature';
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "AtesProps".
 */
export interface AtesProps {
	file: string;
	name: string;
	rating: 'non' | 'simple' | 'challenging' | 'complex' | 'extreme' | 'unrated';
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "OverlayFile".
 */
export interface OverlayFile {
	bytes: number;
	error?: string | null;
	features: number;
	name: string;
	ratings: {
		[k: string]: number;
	};
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
 * Every forecast zone in the map's box, as published, with expiry applied now.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ZonesOut".
 */
export interface ZonesOut {
	features: ZoneFeature[];
	generated_at: string | null;
	problem_slope_deg?: number;
	spot_km?: number;
	treeline: TreelineRule[];
	treeline_spots: TreelineSpot[];
	type?: 'FeatureCollection';
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ZoneFeature".
 */
export interface ZoneFeature {
	geometry: {
		[k: string]: unknown;
	};
	id: string;
	properties: ZoneProps;
	type?: 'Feature';
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ZoneProps".
 */
export interface ZoneProps {
	id: string;
	today: string;
	tz: string;
	view: AvalancheView;
}
/**
 * Where the treeline band is: the first rule whose conditions all match wins.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "TreelineRule".
 */
export interface TreelineRule {
	/**
	 * @minItems 2
	 * @maxItems 2
	 */
	band: [number, number];
	box?: [number, number, number, number] | null;
	center?: string | null;
	name: string;
	zone?: string | null;
}
/**
 * The owner's treeline numbers near one location.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "TreelineSpot".
 */
export interface TreelineSpot {
	/**
	 * @minItems 2
	 * @maxItems 2
	 */
	band: [number, number];
	lat: number;
	location_id: string;
	lon: number;
	name: string;
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
 * The experimental terrain concern index's settings (config `terrain:`), for every
 * visitor unless HAZARD_INDEX is off. The browser works the index out from these.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ConcernOut".
 */
export interface ConcernOut {
	caption: string;
	/**
	 * @minItems 3
	 * @maxItems 3
	 */
	classes: [number, number, number];
	match_listed: number;
	match_none: number;
	match_other: number;
	slope: [number, number][];
	sun: number;
	sun_hours: number;
	wind_effect: number;
	wind_loaded: number;
	wind_scoured: number;
	wind_snow_cm: number;
}
/**
 * What the map's weather says at a point (GET /api/map/point).
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PointOut".
 */
export interface PointOut {
	depth: PointDepth | null;
	elevations?: number[];
	generated: string | null;
	gust: PointValue[];
	inside: boolean;
	lat: number;
	lon: number;
	min_snow_cm: number;
	min_wind_kmh: number;
	observed: PointObserved[];
	rates: PointRate[];
	ridge: PointWind[];
	roses: RoseOut[];
	snow_level: PointValue[];
	totals: PointTotal[];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PointDepth".
 */
export interface PointDepth {
	cm: number | null;
	src: {
		[k: string]: string;
	};
	t: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PointValue".
 */
export interface PointValue {
	t: number;
	value: number | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PointObserved".
 */
export interface PointObserved {
	cm: number | null;
	end: number;
	hours: number;
}
/**
 * One frame of the precipitation timeline at the point.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PointRate".
 */
export interface PointRate {
	high: number | null;
	kind: string;
	low: number | null;
	span_h: number;
	t: number;
	type: ('snow' | 'mix' | 'rain') | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PointWind".
 */
export interface PointWind {
	dir: number | null;
	kmh: number | null;
	t: number;
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
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "PointTotal".
 */
export interface PointTotal {
	by_elevation?: number[] | null;
	cm: number | null;
	end: number;
	hours: number;
	source: string;
	start: number;
	window: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "StationsOut".
 */
export interface StationsOut {
	errors?: string[];
	generated_at: string;
	stations: MapStation[];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "MapStation".
 */
export interface MapStation {
	change24_cm: number | null;
	daily: StationDay[];
	depth_cm: number | null;
	elev_m: number | null;
	id: string;
	lat: number;
	lon: number;
	name: string;
	network: 'snotel' | 'bc';
	obs_time: string | null;
	url?: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "StationDay".
 */
export interface StationDay {
	date: string;
	depth_cm: number | null;
}
/**
 * Wind and new snow per location for the map's wind-effect layer.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "MapWindOut".
 */
export interface MapWindOut {
	locations: MapWindLocation[];
	min_snow_cm: number;
	min_wind_kmh: number;
}
/**
 * A location's loading roses, placed at its summit (where the wind is taken).
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "MapWindLocation".
 */
export interface MapWindLocation {
	flags?: Flag[];
	generated_at: string;
	id: string;
	lat: number;
	lon: number;
	name: string;
	roses: RoseOut[];
}
/**
 * Something worth a look (see docs/ARCHITECTURE.md). The browser words it in your units.
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
 * via the `definition` "Me".
 */
export interface Me {
	is_owner: boolean;
	owner_login_enabled: boolean;
}
/**
 * About this server: version, and numbers the app shows instead of hard-coding them.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "MetaOut".
 */
export interface MetaOut {
	commit: string | null;
	open_meteo_daily_budget: number;
	powder_cm: number;
	snowfall_cm_per_mm: number;
	storm_cm: number;
	version: string;
}
/**
 * Recent field reports in the map's box.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ObsOut".
 */
export interface ObsOut {
	days: number;
	errors?: string[];
	features: ObsFeature[];
	generated_at: string | null;
	type?: 'FeatureCollection';
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ObsFeature".
 */
export interface ObsFeature {
	geometry: {
		[k: string]: unknown;
	};
	properties: ObsProps;
	type?: 'Feature';
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ObsProps".
 */
export interface ObsProps {
	id: string;
	images: number;
	kinds: string[];
	region: string;
	time: string;
	title: string;
	url: string | null;
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
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "OverviewPeriod".
 */
export interface OverviewPeriod {
	date: string;
	key: string;
	kind: string;
	label: string;
	ptype?: string;
	rain_mm?: number | null;
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
 * The map's recent satellite imagery: daily VIIRS everywhere, and per location a
 * stitched newest-clear view and the newest whole clear scenes.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SatOut".
 */
export interface SatOut {
	attribution?: string[];
	days?: number;
	generated_at?: string | null;
	locations?: SatLocation[];
	min_clear_pct?: number;
	scene_days?: number;
	viirs_date?: string | null;
	zooms?: number[];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SatLocation".
 */
export interface SatLocation {
	box?: [number, number, number, number] | null;
	checked_at?: string | null;
	composite?: SatComposite | null;
	error?: string | null;
	id: string;
	lat: number;
	lon: number;
	name: string;
	scenes?: SatScene[];
}
/**
 * The newest clear view of the area, stitched from passes (see `stitch`).
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SatComposite".
 */
export interface SatComposite {
	at_location: string | null;
	filled_pct: number;
	latest_pass: string | null;
	layers: SatLayer[];
	lines?: [number, number][][];
	parts: SatPart[];
	view: string;
}
/**
 * One pass in a stitched view.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SatLayer".
 */
export interface SatLayer {
	id: string;
	platform: string;
	share_pct: number;
	time: string;
}
/**
 * Where one pass supplies a stitched view, for the map's outlines and dates.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SatPart".
 */
export interface SatPart {
	polygons: [number, number][][][];
	share_pct: number;
	time: string;
}
/**
 * One pass that covers the whole area and sees most of it: a coherent picture.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SatScene".
 */
export interface SatScene {
	clear_pct: number;
	id: string;
	nodata_pct: number;
	platform: string;
	snow_pct: number;
	time: string;
	view: string;
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
	slr?: (number | null)[];
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
	ens_raw?: EnsStats | null;
	ens_slr: EnsStats | null;
	members_cm?: number[];
	members_cm_raw?: number[];
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
	headline?: string;
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
