"""The snapshot document: everything the UI shows for one location, built once per run.

Metric units throughout (cm of snow, mm of water, °C, m, km/h); the browser
converts. Times are local ISO strings with their UTC offset. Hourly data is
columnar (one list per field) to keep the gzipped document small.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from snowwatch.models import Webcam
from snowwatch.urls import clean_links

DOC_VERSION = 3


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
    # Snow-to-liquid ratio from the temperature (the configured bands); None when it is
    # too warm for snow. Empty in snapshots built before this field existed.
    slr: list[float | None] = []


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
    network: str = "NRCS SNOTEL"
    distance_km: float | None = None  # from the mid band


class Flag(BaseModel):
    """Something worth a look (see docs/ARCHITECTURE.md). The browser words it in your units."""

    type: str  # powder_day, storm_incoming, model_outlier, low_confidence, rain_on_snow, …
    severity: str  # info, notice, warning
    date: str | None = None
    period_key: str | None = None
    value: float | None = None  # metric: cm, mm, km/h, m or °C, depending on the type
    value2: float | None = None
    model: str | None = None  # model_outlier: which model
    detail: str | None = None  # e.g. below_base / above_mid, the rating, the NWS event
    first_run: int | None = None  # the run that first raised it (for "New")


class RidgeOut(BaseModel):
    """Free-air wind at summit height, aligned with each band's `hourly.t`."""

    level_m: float
    kmh: list[float | None]
    dir: list[float | None]


class RoseOut(BaseModel):
    """Where wind would drift new snow: snowfall × ridge wind per sector (N first, clockwise)."""

    window: str  # past72, next48 (the Backcountry tab), past48, next24, next72 (the map)
    sectors: list[float]  # share of the loading, wind blowing from that sector
    snow_cm: float  # summit snowfall in the window
    mean_kmh: float | None
    wind_from: str | None
    loading: list[str]  # lee aspects
    label: str


class WarmingOut(BaseModel):
    """The biggest 24 h warming in the next 72 h, and rain falling on snow."""

    fl_rise_m: float | None
    fl_rise_at: str | None
    temp_rise_c: float | None  # mid band
    temp_rise_at: str | None
    rain_on_snow_mm: float | None  # rain at mid in the next 48 h when snow is on the ground


class RefreezeNight(BaseModel):
    date: str  # the date the night starts
    band: str
    status: str  # Good, Partial, None, Unknown
    low_c: float | None
    clear_frac: float | None


class SkyDay(BaseModel):
    """Daytime sky at the summit: mean cloud per layer (%) and the lowest visibility."""

    date: str
    cloud_low: float | None
    cloud_mid: float | None
    cloud_high: float | None
    vis_min_m: float | None


class StormOut(BaseModel):
    past72_cm: float | None  # summit, model snowfall
    next48_cm: float | None


class BackcountryOut(BaseModel):
    rose: list[RoseOut]
    warming: WarmingOut
    refreeze: list[RefreezeNight]
    sky: list[SkyDay]
    storm: StormOut


class Reason(BaseModel):
    """Why a day got its rating. The browser words it in the viewer's units."""

    code: str  # new_snow, heavy_wet, clear, grey, rain, gusts, flat_light, very_cold
    value: float | None = None


class DayOut(BaseModel):
    """One day for Plan a day and the ski-day rating. Snow and temperatures at mid."""

    date: str
    label: str  # "Today", "Thu"
    overnight_cm: float | None  # the night before
    day_cm: float | None
    quality: str | None
    rating: str | None  # resorts only: Powder, Great, Good, Fair, Poor
    score: int | None  # 5 = Powder … 1 = Poor
    reasons: list[Reason] = []
    gust_max_kmh: float | None  # summit, lift hours
    rain_mm: float | None  # mid, lift hours
    tmax_c: float | None
    tmin_c: float | None
    cloud_low: float | None
    vis_min_m: float | None
    wcode: float | None  # the day's most significant weather code at mid


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
    webcams: list[Webcam] = []

    @field_validator("links")
    @classmethod
    def _safe_links(cls, v: dict[str, str]) -> dict[str, str]:
        return clean_links(v)


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
    ridge: RidgeOut | None = None
    backcountry: BackcountryOut | None = None
    days: list[DayOut] = []
    flags: list[Flag] = Field(default_factory=list)
    warnings: list[str] = []
