"""Response models for the API (the snapshot document itself is `snowwatch.doc.Snapshot`)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from snowwatch.api.admin import (
    BudgetOut,
    CatalogAddIn,
    CatalogAddOut,
    CatalogItem,
    JobOut,
    LookupStatus,
    SaveOut,
)
from snowwatch.api.auth import Me
from snowwatch.avalanche import AvalancheView
from snowwatch.avalanche_zones import ZonesOut
from snowwatch.doc import CloudsOut, DayOut, Flag, RoseOut, Snapshot
from snowwatch.locations.resolve import ResolveIn, ResolveOut
from snowwatch.maps.point import PointOut
from snowwatch.maps.sat import SatOut
from snowwatch.models import Location
from snowwatch.observations import ObsOut, ObsProps
from snowwatch.overlays import AtesOut, OverlayFile
from snowwatch.stations import MapStation, StationsOut
from snowwatch.verify import VerificationOut


class BandSummary(BaseModel):
    band: str
    label: str
    elev_m: float


class LocationSummary(BaseModel):
    id: str
    name: str
    kind: str
    region: str
    country: str
    tz: str | None
    bands: list[BandSummary]
    # From the latest snapshot (mid band); None until the first pull.
    run_id: int | None = None
    generated_at: str | None = None
    next5_cm: float | None = None
    next5_p10_cm: float | None = None
    next5_p90_cm: float | None = None
    d6_10_cm: float | None = None
    last24_cm: float | None = None
    alerts: int = 0


class OverviewPeriod(BaseModel):
    key: str
    label: str
    kind: str
    date: str
    snow_cm: float | None
    ptype: str = "none"  # snow, mix, rain or none, as on the snapshot's periods
    rain_mm: float | None = None


class DangerChip(BaseModel):
    """The highest avalanche rating for a day, when the forecast is current."""

    level: int | None  # 1–5
    status: str  # current, expired, no_rating, none (no zone), not_issued (no rating for that day)


class BestDay(BaseModel):
    date: str
    label: str
    rating: str
    score: int


class OverviewRow(BaseModel):
    """One location on the Overview and Calendar pages (mid band)."""

    id: str
    name: str
    kind: str
    region: str
    country: str
    run_id: int | None = None
    generated_at: str | None = None
    last24_cm: float | None = None
    next5_cm: float | None = None
    next5_p10_cm: float | None = None
    next5_p90_cm: float | None = None
    d6_10_cm: float | None = None
    alerts: list[str] = []
    snow_depth_cm: float | None = None
    periods: list[OverviewPeriod] = []
    danger: DangerChip | None = None
    best_day: BestDay | None = None  # resorts: the best-rated day in the next 10
    powder_dates: list[str] = []  # resorts: days rated Powder
    flags: list[Flag] = []  # most important first; avalanche danger added when served
    lat: float | None = None  # mid band, for the map
    lon: float | None = None


class MapWindLocation(BaseModel):
    """A location's loading roses, placed at its summit (where the wind is taken)."""

    id: str
    name: str
    lat: float
    lon: float
    generated_at: str
    roses: list[RoseOut]
    # Its rapid-warming and rain-on-snow flags (the concern index's wet-snow inputs).
    flags: list[Flag] = []


class MapWindOut(BaseModel):
    """Wind and new snow per location for the map's wind-effect layer."""

    min_snow_cm: float  # less new snow than this: nothing to move
    min_wind_kmh: float  # lighter than this: little drifting
    locations: list[MapWindLocation]


class MapCloudsLocation(BaseModel):
    """A location's cloud layers hour by hour, placed at its middle, with the heights its
    bands span (so the map can say whether the summit is above the cloud)."""

    id: str
    name: str
    lat: float
    lon: float
    base_m: float
    summit_m: float
    generated_at: str
    clouds: CloudsOut


class MapCloudsOut(BaseModel):
    """Each location's cloud layers for the map's 3D clouds: an approximation."""

    locations: list[MapCloudsLocation]


class ConcernOut(BaseModel):
    """The experimental terrain concern index's settings (config `terrain:`), for every
    visitor unless HAZARD_INDEX is off. The browser works the index out from these."""

    caption: str
    slope: list[Annotated[list[float], Field(min_length=2, max_length=2)]]  # [from °, factor]
    match_listed: float
    match_other: float
    match_none: float
    wind_loaded: float
    wind_scoured: float
    wind_effect: float
    wind_snow_cm: float
    sun: float
    sun_hours: float
    classes: Annotated[list[float], Field(min_length=3, max_length=3)]


class PlanDate(BaseModel):
    date: str
    label: str


class PlanRow(BaseModel):
    id: str
    name: str
    kind: str
    region: str
    day: DayOut | None  # None when the location has no forecast for that date
    danger: DangerChip


class PlanOut(BaseModel):
    """Plan a day: every location on one date."""

    date: str
    dates: list[PlanDate]
    rows: list[PlanRow]


class CompareDay(BaseModel):
    """One location's day at one band (a night goes with its evening's date)."""

    date: str
    snow_cm: float
    rain_mm: float
    tmax_c: float | None
    tmin_c: float | None
    gust_kmh: float | None
    fl_min_m: float | None  # the day's lowest freezing level (hourly, calendar day)
    slr: float | None  # mean ratio over the periods that snow
    cloud: float | None  # mean cloud cover (%)


class CompareBand(BaseModel):
    band: str
    elev_m: float
    days: list[CompareDay]


class CompareRow(BaseModel):
    id: str
    bands: list[CompareBand]


class CompareOut(BaseModel):
    """Every location's days at each band, for ranking them on Compare's Add list."""

    rows: list[CompareRow]


class TrendRun(BaseModel):
    run_id: int
    issued_at: str
    next5_cm: float | None  # consensus over the five dates starting on the issue date
    daily: dict[str, float | None]  # target date → consensus snow (cm)


class TrendOut(BaseModel):
    location_id: str
    runs: list[TrendRun]  # oldest first


class NearbyStation(BaseModel):
    station: MapStation
    distance_km: float  # from the location's mid band


class NearbyReport(BaseModel):
    report: ObsProps
    distance_km: float
    # For the Webcams tab's photos: "near" (within `near_km` and closer to this location
    # than to any other) or "zone" (farther, but in the location's avalanche zone).
    group: Literal["near", "zone"] | None = None


class NearbyOut(BaseModel):
    """What was measured and reported around a location (the Observed tab): the
    closest snow stations and recent field reports (Avalanche Canada's Mountain
    Information Network and NWAC's observations), read from the files the map's layers
    use."""

    location_id: str
    radius_km: float
    stations_at: str | None  # when the stations were last read; None before the first time
    stations: list[NearbyStation]  # nearest first
    reports_at: str | None
    reports_days: int | None  # how far back the reports go
    reports: list[NearbyReport]  # newest first
    # The reports with photos (the Webcams tab), newest first: those near the location,
    # then those elsewhere in its avalanche zone (`group`). Others aren't listed.
    photo_reports: list[NearbyReport] = []
    # Every report near the location or in its avalanche zone, grouped the same way, with
    # or without photos (the Backcountry tab's recent observations).
    area_reports: list[NearbyReport] = []
    near_km: float = 20.0
    zone_name: str | None = None  # the location's avalanche zone, when known
    # Spots only (`/api/spot/nearby`): the avalanche zone the point is in and its forecast
    # with expiry applied now, as the map's zones layer shows it.
    zone_id: str | None = None
    avalanche: AvalancheView | None = None


class RunOut(BaseModel):
    id: int
    kind: str
    status: str
    started_at: str
    finished_at: str | None
    api_weight: float
    errors: list[str]


class SourceRow(BaseModel):
    source: str
    last_ok_at: str | None
    last_error_at: str | None
    last_error: str | None
    calls_today: int
    errors_today: int


class LocationAge(BaseModel):
    id: str
    name: str
    generated_at: str | None
    station: str | None
    station_obs_time: str | None
    flags: int


class ModelRunOut(BaseModel):
    """One model's latest run, as the model watcher last read it (milestone 4)."""

    model: str  # the app's name, e.g. gfs_seamless
    label: str  # e.g. GFS
    init_time: str | None  # the run (UTC)
    available_at: str | None  # when it became available


class LocalServerOut(BaseModel):
    """The self-hosted Open-Meteo server (OPEN_METEO_URL), from today's requests."""

    ok: bool  # its last request succeeded
    last_ok_at: str | None
    last_error_at: str | None
    last_error: str | None
    latency_s: float | None  # mean seconds per request today (UTC)
    requests_today: int
    fallbacks_today: int  # requests retried on the public API after it failed


class EnsembleSystemOut(BaseModel):
    """Where one ensemble system's members come from (milestone 1b)."""

    system: str  # the `models` name: gfs_seamless, ecmwf_ifs025, gem_global
    label: str  # GEFS, ECMWF ENS, GEPS
    source: str  # "self-hosted" or "public"
    run: str | None  # the run the server holds (ISO, UTC), when downloaded
    age_h: float | None  # that run's age now
    reason: str | None  # why it's on the public API in local mode
    since: str | None  # when it last switched between the two (local mode)


class ShadowOut(BaseModel):
    """A system's shadow-mode comparisons over the last 7 days: the server's answers
    against the public API's for the same requests."""

    system: str
    label: str
    comparisons: int
    errors: int  # the server couldn't answer
    same_run: int  # comparisons where the server and the public data had the same run
    members_local_min: int | None
    members_public_max: int | None
    # The most the server's reach fell short of the public's (negative: always ahead).
    reach_gap_h: float | None
    # Members' 16-day totals, over same-run comparisons: the mean of the mean
    # differences, and the largest difference.
    mean_diff_cm: float | None
    max_diff_cm: float | None


class EnsemblesOut(BaseModel):
    """Self-hosted ensembles (OPEN_METEO_ENSEMBLES, with OPEN_METEO_URL set)."""

    mode: str  # public, shadow or local
    systems: list[EnsembleSystemOut]
    shadow: list[ShadowOut]


class StatusOut(BaseModel):
    """The Status page: per-source health, runs, usage and data age."""

    sources: list[SourceRow]
    runs: list[RunOut]
    weight_today: float  # public Open-Meteo calls today (UTC), from the usage ledger
    budget: float
    locations: list[LocationAge]
    # Set when forecasts come from a self-hosted server: the public calls are then
    # ensembles (and any fallbacks) only.
    local: LocalServerOut | None = None
    # Set with a self-hosted server: where ensembles come from, and shadow comparisons.
    ensembles: EnsemblesOut | None = None
    # Each model's latest run (empty before the worker's model watcher has looked), and
    # how runs are scheduled: "data" (when models update) or "fixed" (schedule.runs_utc).
    model_runs: list[ModelRunOut] = []
    refresh: str = "fixed"


class MetaOut(BaseModel):
    """About this server: version, and numbers the app shows instead of hard-coding them."""

    version: str
    commit: str | None
    open_meteo_daily_budget: int
    powder_cm: float  # a powder-day alert: this much snow, night before plus the day
    storm_cm: float  # a storm alert: this much in 48 h
    snowfall_cm_per_mm: float  # Open-Meteo's fixed snow-to-water conversion
    # Whether the app's own experimental estimates are shown (HAZARD_INDEX): the map's
    # concern index and the Backcountry tab's weather-loading grade.
    hazard_index: bool = True
    # Whether forecasts come from a self-hosted Open-Meteo server (OPEN_METEO_URL), which
    # makes a forecast for any point affordable (docs/OPEN-METEO-PLAN.md, milestone 2).
    local_forecasts: bool = False


class ApiTypes(BaseModel):
    """Every response shape, exported as one JSON Schema for the TypeScript types."""

    snapshot: Snapshot
    locations: list[LocationSummary]
    overview: list[OverviewRow]
    map_wind: MapWindOut
    map_clouds: MapCloudsOut
    map_concern: ConcernOut
    avalanche_zones: ZonesOut
    sat: SatOut
    map_point: PointOut
    map_stations: StationsOut
    observations: ObsOut
    ates: AtesOut
    overlay_files: list[OverlayFile]
    trend: TrendOut
    runs: list[RunOut]
    me: Me
    admin_locations: list[Location]
    catalog: list[CatalogItem]
    resolve_in: ResolveIn
    resolve_out: ResolveOut
    save: SaveOut
    job: JobOut
    budget: BudgetOut
    catalog_add_in: CatalogAddIn
    catalog_add: CatalogAddOut
    lookups: LookupStatus
    avalanche: dict[str, AvalancheView]
    plan: PlanOut
    compare: CompareOut
    verification: VerificationOut
    nearby: NearbyOut
    status: StatusOut
    meta: MetaOut
