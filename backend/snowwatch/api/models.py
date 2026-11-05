"""Response models for the API (the snapshot document itself is `snowwatch.doc.Snapshot`)."""

from __future__ import annotations

from pydantic import BaseModel

from snowwatch.doc import Snapshot


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


class ApiTypes(BaseModel):
    """Every response shape, exported as one JSON Schema for the TypeScript types."""

    snapshot: Snapshot
    locations: list[LocationSummary]
    overview: list[OverviewRow]
    trend: TrendOut
    runs: list[RunOut]
