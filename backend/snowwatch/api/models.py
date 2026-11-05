"""Response models for the API (the snapshot document itself is `snowwatch.doc.Snapshot`)."""

from __future__ import annotations

from pydantic import BaseModel

from snowwatch.api.admin import BudgetOut, CatalogItem, JobOut, LookupStatus, SaveOut
from snowwatch.avalanche import AvalancheView
from snowwatch.doc import DayOut, Flag, Snapshot
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


class Me(BaseModel):
    email: str | None
    is_owner: bool


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


class ApiTypes(BaseModel):
    """Every response shape, exported as one JSON Schema for the TypeScript types."""

    snapshot: Snapshot
    locations: list[LocationSummary]
    overview: list[OverviewRow]
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
