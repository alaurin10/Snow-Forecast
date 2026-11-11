"""Response models for the API (the snapshot document itself is `snowwatch.doc.Snapshot`)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from snowwatch.api.admin import BudgetOut, CatalogItem, JobOut, LookupStatus, SaveOut
from snowwatch.api.auth import Me
from snowwatch.avalanche import AvalancheView
from snowwatch.avalanche_zones import ZonesOut
from snowwatch.doc import DayOut, Flag, RoseOut, Snapshot
from snowwatch.locations.resolve import ResolveIn, ResolveOut
from snowwatch.models import Location
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


class TrendRun(BaseModel):
    run_id: int
    issued_at: str
    next5_cm: float | None  # consensus over the five dates starting on the issue date
    daily: dict[str, float | None]  # target date → consensus snow (cm)


class TrendOut(BaseModel):
    location_id: str
    runs: list[TrendRun]  # oldest first


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


class StatusOut(BaseModel):
    """The Status page: per-source health, runs, usage and data age."""

    sources: list[SourceRow]
    runs: list[RunOut]
    weight_today: float
    budget: float
    locations: list[LocationAge]


class MetaOut(BaseModel):
    """About this server: version, and numbers the app shows instead of hard-coding them."""

    version: str
    commit: str | None
    open_meteo_daily_budget: int
    powder_cm: float  # a powder-day alert: this much snow, night before plus the day
    storm_cm: float  # a storm alert: this much in 48 h
    snowfall_cm_per_mm: float  # Open-Meteo's fixed snow-to-water conversion


class ApiTypes(BaseModel):
    """Every response shape, exported as one JSON Schema for the TypeScript types."""

    snapshot: Snapshot
    locations: list[LocationSummary]
    overview: list[OverviewRow]
    map_wind: MapWindOut
    map_concern: ConcernOut
    avalanche_zones: ZonesOut
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
    lookups: LookupStatus
    avalanche: dict[str, AvalancheView]
    plan: PlanOut
    verification: VerificationOut
    status: StatusOut
    meta: MetaOut
