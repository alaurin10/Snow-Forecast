"""The snapshot document: everything the UI shows for one location, built once per run.

Metric units throughout (cm of snow, mm of water, °C, m, km/h); the browser
converts. Times are local ISO strings with their UTC offset. Hourly data is
columnar (one list per field) to keep the gzipped document small.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

DOC_VERSION = 1


class EnsStats(BaseModel):
    p10: float | None
    p50: float | None
    p90: float | None
    mean: float | None
    n: int
    estimated: bool = False  # scaled from the mid band, not run at this elevation


class PeriodOut(BaseModel):
    key: str
    date: str
    kind: str
    label: str
    start: str
    hours: int
    snow_cm: float | None  # headline depth (config depth_method)
    snow_cm_raw: float | None  # model snowfall, 7:1
    snow_cm_slr: float | None  # snow water × temperature-based ratio
    swe_mm: float | None
    water_mm: float | None
    rain_mm: float | None
    basis: str | None
    nmodels: int
    models: dict[str, float | None]  # raw cm per model, None where a model has ended
    blend_cm: float | None
    ens: EnsStats | None  # raw cm
    ptype: str
    slr: float | None
    quality: str | None
    tmin_c: float | None
    tmax_c: float | None
    snow_level_min_m: float | None
    wind_max_kmh: float | None
    gust_max_kmh: float | None
    cloud_mean: float | None
    pop_max: float | None


class WindowOut(BaseModel):
    snow_cm: float | None
    snow_cm_raw: float | None
    snow_cm_slr: float | None
    ens: EnsStats | None
    ens_slr: EnsStats | None
    # Sorted member totals for exceedance curves (mid band only; other bands
    # multiply by `scale`).
    members_cm: list[float] = []
    members_cm_slr: list[float] = []
    scale: float | None = None


class HourlyOut(BaseModel):
    t: list[str]
    snow_cm: list[float | None]
    swe_mm: list[float | None]
    water_mm: list[float | None]
    rain_mm: list[float | None]
    ptype: list[str]
    temp_c: list[float | None]
    temp_lo: list[float | None]
    temp_hi: list[float | None]
    fl_m: list[float | None]
    fl_lo: list[float | None]
    fl_hi: list[float | None]
    snow_level_m: list[float | None]
    wind_kmh: list[float | None]
    wind_hi: list[float | None]
    gust_kmh: list[float | None]
    wdir: list[float | None]
    cloud: list[float | None]
    cloud_low: list[float | None]
    cloud_mid: list[float | None]
    cloud_high: list[float | None]
    pop: list[float | None]
    visibility_m: list[float | None]
    is_day: list[float | None]
    wcode: list[float | None]


class ElevationOut(BaseModel):
    temp_now_c: float | None
    tmin24_c: float | None
    tmax24_c: float | None
    last24_cm: float | None  # model snowfall over the past 24 h (high-res blend)
    next24_cm: float | None
    next5_cm: float | None
    d6_10_cm: float | None


class BandOut(BaseModel):
    band: str
    label: str
    elev_m: float
    periods: list[PeriodOut]
    windows: dict[str, WindowOut]
    hourly: HourlyOut
    stats: ElevationOut


class DailyEns(BaseModel):
    p10: float | None
    p50: float | None
    p90: float | None
    n: int


class DailyRow(BaseModel):
    date: str
    hours: int
    models: dict[str, float | None]  # raw cm per model for the day
    models_cum: dict[str, float | None]
    ens_cum: dict[str, DailyEns | None]  # per ensemble system, running total
    pooled_cum: DailyEns | None
    # Set once the pooled band has stopped (the shortest ensemble ended): the
    # system whose own band in ens_cum carries on.
    pooled_tail: str | None
    ens_day: DailyEns | None  # this day alone, all members pooled
    snow_level_min_m: float | None


class SunDay(BaseModel):
    date: str
    sunrise: str | None
    sunset: str | None
    daylight_s: float | None


class Alert(BaseModel):
    event: str | None
    headline: str | None
    severity: str | None
    onset: str | None
    ends: str | None
    url: str | None


class SnotelDay(BaseModel):
    date: str
    depth_cm: float | None
    swe_mm: float | None
    temp_c: float | None
    precip_mm: float | None


class Snotel(BaseModel):
    triplet: str
    name: str | None
    elev_m: float | None
    obs_time: str | None
    depth_cm: float | None
    swe_mm: float | None
    change24_cm: float | None
    change72_cm: float | None
    daily: list[SnotelDay]


class LocationMeta(BaseModel):
    id: str
    name: str
    kind: str
    region: str
    country: str
    tz: str
    lat: float
    lon: float
    links: dict[str, str]


class Snapshot(BaseModel):
    version: int = DOC_VERSION
    location: LocationMeta
    run_id: int | None
    generated_at: str
    now: str
    depth_method: str
    models: list[str]
    ensembles: dict[str, int]  # system → member count
    basis_switch: str | None  # start of the first period that uses the ensemble mean
    bands: list[BandOut]
    daily: list[DailyRow]
    sun: list[SunDay]
    alerts: list[Alert] = []
    snotel: Snotel | None = None
    flags: list[dict[str, object]] = Field(default_factory=list)  # milestone M6
    avalanche: dict[str, object] | None = None  # milestone M5
    warnings: list[str] = []
