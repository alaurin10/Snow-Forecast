"""Forecast configuration (`config/forecast.yaml`)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import AfterValidator, BaseModel, Field, field_validator

from snowwatch.analysis.backcountry import BackcountryConfig
from snowwatch.analysis.flags import FlagConfig
from snowwatch.analysis.skiday import SkiDayConfig
from snowwatch.analysis.snowlevel import PhysicsConfig
from snowwatch.settings import get_settings


class ModelSets(BaseModel):
    global_: list[str] = Field(alias="global")
    short_range: dict[str, list[str]] = {}
    upper_air_exclude: list[str] = []
    # One model per country for each location's cloud layers (the map's 3D clouds): the
    # cloud cover at every pressure level from it. A country not listed takes the first.
    clouds: dict[str, str] = {"US": "gfs_seamless", "CA": "gem_seamless"}


class SlrBand(BaseModel):
    min_c: float | None
    ratio: float
    label: str


def _hhmm(v: str) -> str:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ValueError(f"{v!r} is not a HH:MM time")
    return v


HHMM = Annotated[str, AfterValidator(_hhmm)]


class Schedule(BaseModel):
    # "data": run each location a few minutes after a model it uses has a new run (at
    # most every 40 min, at least every 3 h; snowwatch/modelwatch.py), only with a
    # self-hosted Open-Meteo server. "fixed" (and always without one): runs_utc.
    refresh: Literal["data", "fixed"] = "data"
    runs_utc: list[HHMM] = Field(min_length=1)
    # When each ensemble system's runs are usually on the public API (UTC): a run asks a
    # system on the public API again once one of its times has passed since the last
    # answer (snowwatch/budget.py may use every other time). Systems the self-hosted
    # server answers are read every run instead.
    ensemble_runs: dict[str, list[HHMM]] = {}
    # Before milestone 4: one list for every system (still read when ensemble_runs is empty).
    ensemble_runs_utc: list[HHMM] = []

    def runs_for(self, system: str) -> list[str]:
        """A system's public-API times, sorted."""
        return sorted(self.ensemble_runs.get(system) or self.ensemble_runs_utc)

    backup_utc: HHMM = "10:00"
    # Avalanche centers publish 6–10 am Mountain time; check again after the runs.
    avalanche_utc: list[HHMM] = []
    vacuum_weekday: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"] = "sun"


class MapConfig(BaseModel):
    """The Map page's weather pictures (see docs/MAP-PLAN.md)."""

    # The box they cover: south, west, north, east in degrees. Widened only to take in
    # a location outside it.
    region: tuple[float, float, float, float] = (31.0, -134.0, 57.0, -102.0)
    # Picture width in pixels (1700 over the default box is about 1.5 km a pixel).
    width: int = Field(1700, ge=200, le=4000)
    radar_minutes: int = Field(6, ge=1)
    # Radar beyond the box (docs/RADAR-PLAN.md M6): a coarser loop of radar and nowcast
    # over most of North America, drawn beneath the box's own. None: none.
    wide_region: tuple[float, float, float, float] | None = (15.0, -170.0, 72.0, -50.0)
    wide_width: int = Field(1800, ge=200, le=4000)  # about 4–7 km a pixel
    wide_minutes: int = Field(12, ge=1)
    forecast_minutes: int = Field(30, ge=5)
    totals_minutes: int = Field(60, ge=10)
    # The other weather layers: snow level, wind, snow on the ground, observed snowfall
    # and clouds (each redrawn only when its sources change).
    layers_minutes: int = Field(30, ge=5)
    # NOAA NBM runs (UTC hours) used for the US beyond 48 h and for US snow totals. Only
    # the 00, 06, 12 and 18 UTC runs reach 10 days; each new run is ~60–80 MB to fetch.
    nbm_cycles: list[int] = [0, 12]
    # Recent satellite (Sentinel-2 round each location, docs/MAP-PLAN.md B6): how often to
    # look for new passes; how far back the stitched newest-clear view looks; how far
    # back whole scenes are looked for, what share of the 24 km area a whole scene must
    # see clearly and may miss, and how many are kept.
    sat_hours: int = Field(6, ge=1, le=48)
    sat_days: int = Field(30, ge=3, le=90)
    sat_scene_days: int = Field(60, ge=3, le=120)
    sat_min_clear: float = Field(0.85, gt=0, le=1)
    sat_max_nodata: float = Field(0.03, ge=0, lt=1)
    sat_keep: int = Field(3, ge=1, le=10)
    sat_wide_km: float = Field(36.0, ge=0, le=60)
    # Snow stations (SNOTEL and BC snow pillows) and Avalanche Canada's field reports
    # (Mountain Information Network): how often to fetch, and how far back reports go.
    stations_minutes: int = Field(60, ge=15)
    obs_minutes: int = Field(60, ge=15)
    obs_days: int = Field(14, ge=1, le=30)
    # Observations and their photos from NWAC's observations page (snowwatch/nwac_obs.py),
    # read in a headless browser this often while a location is in NWAC's area.
    nwac_obs: bool = True
    nwac_obs_minutes: int = Field(180, ge=60)

    @field_validator("region")
    @classmethod
    def _box(cls, v: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        south, west, north, east = v
        if not (-85 <= south < north <= 85 and -180 <= west < east <= 180):
            raise ValueError("map.region is [south, west, north, east] in degrees")
        return v


class TerrainConfig(BaseModel):
    """The map's avalanche terrain layers (docs/MAP-PLAN.md, B7.2 and B7.3)."""

    # Terrain matching a listed problem: the lowest slope that counts, by default.
    problem_slope_deg: Literal[25, 30, 35] = 30
    # The experimental concern index: score = (base + wind + sun) × slope × match.
    # Slope factor from each angle up to the next: [degrees, factor]; 0 below the first.
    concern_slope: list[tuple[float, float]] = [(25, 0.5), (30, 1.0), (46, 0.7), (56, 0.3)]
    concern_match_listed: float = 1.0  # aspect and band in a listed problem
    concern_match_other: float = 0.6  # not in any listed problem
    concern_match_none: float = 0.8  # the bulletin lists no problems
    concern_wind_loaded: float = 0.5  # where the wind effect says loaded…
    concern_wind_scoured: float = -0.25  # …and where it says scoured
    concern_wind_effect: float = Field(0.2, gt=0, le=1)  # effect beyond this counts
    concern_wind_snow_cm: float = 20  # new snow (last 48 h) that brings in wind loading
    concern_sun: float = 0.5  # sunny E–S–W slopes on a wet-snow day
    concern_sun_hours: float = 3  # at least this much direct sun that day
    # Score thresholds for the elevated, high and very high classes.
    concern_classes: tuple[float, float, float] = (1.5, 2.5, 3.5)

    @field_validator("concern_slope")
    @classmethod
    def _rising(cls, v: list[tuple[float, float]]) -> list[tuple[float, float]]:
        angles = [a for a, _ in v]
        if not v or angles != sorted(angles) or any(not 0 <= f <= 1 for _, f in v):
            raise ValueError("concern_slope: rising angles, factors from 0 to 1")
        return v

    @field_validator("concern_classes")
    @classmethod
    def _classes(cls, v: tuple[float, float, float]) -> tuple[float, float, float]:
        if not v[0] < v[1] < v[2]:
            raise ValueError("concern_classes must rise")
        return v


class SpotConfig(BaseModel):
    """Forecasts for any point (spots, docs/OPEN-METEO-PLAN.md milestone 2), offered only
    with a self-hosted Open-Meteo server (OPEN_METEO_URL)."""

    # Public Open-Meteo weight a day that spots' ensembles may use (each new point's
    # ensembles cost ~11.8): what the self-hosted server can't answer (milestone 1b).
    ensemble_allowance: int = Field(2000, ge=0)
    # A spot's ensembles are kept this long per 0.25° cell and 100 m of elevation.
    ensemble_cache_h: float = Field(6, gt=0, le=24)
    # A built spot is kept this long (until the models update) and for this many points.
    cache_minutes: int = Field(60, ge=1, le=360)
    cache_entries: int = Field(300, ge=1, le=5000)


class ForecastConfig(BaseModel):
    models: ModelSets
    ensembles: list[str]
    short_range_hours: int = 48
    consensus_min_models: int = 3
    blend_periods: int = 4
    periods: int = 20
    hourly_hours: int = 240
    day_start_hour: int = 6
    night_start_hour: int = 18
    min_period_hours: int = 6
    ensemble_min_members: int = 10
    ensemble_max_age_h: float = 13
    snowfall_cm_per_mm: float = 0.7
    snow_level_offset_m: float = 305
    slr_bands: list[SlrBand] = Field(min_length=1)
    # "column": the column snow ratio (milestone 3) where its data is, else "slr"'s.
    depth_method: Literal["raw", "slr", "column"] = "raw"
    schedule: Schedule
    skiday: SkiDayConfig = SkiDayConfig()
    backcountry: BackcountryConfig = BackcountryConfig()
    flags: FlagConfig = FlagConfig()
    map: MapConfig = MapConfig()
    terrain: TerrainConfig = TerrainConfig()
    spots: SpotConfig = SpotConfig()
    physics: PhysicsConfig = PhysicsConfig()
    # Verification: the snow-to-water ratio for the observed-SWE depth estimate, and the
    # one that turns forecast snow water into settled snow, as a depth sensor sees it.
    verify_swe_ratio: float = 10
    verify_settled_ratio: float = Field(8, gt=0)

    @field_validator("slr_bands")
    @classmethod
    def _bands_warm_to_cold(cls, v: list[SlrBand]) -> list[SlrBand]:
        """Each band's lower bound is colder than the one before; the last is open-ended."""
        bounds = [b.min_c for b in v[:-1]]
        if any(b is None for b in bounds) or bounds != sorted(bounds, reverse=True):  # type: ignore[type-var]
            raise ValueError("slr_bands must go from warm to cold, ending with min_c: null")
        return v

    def models_for(self, country: str) -> list[str]:
        return [*self.models.global_, *self.models.short_range.get(country, [])]

    def short_range_for(self, country: str) -> list[str]:
        return list(self.models.short_range.get(country, []))

    def upper_air_models(self, country: str) -> list[str]:
        return [m for m in self.models_for(country) if m not in self.models.upper_air_exclude]

    def cloud_model(self, country: str) -> str | None:
        """The model for a location's cloud layers, or None if none is set."""
        clouds = self.models.clouds
        return clouds.get(country) or next(iter(clouds.values()), None)


def load_forecast_config(path: Path | None = None) -> ForecastConfig:
    path = path or get_settings().config_dir / "forecast.yaml"
    return ForecastConfig.model_validate(yaml.safe_load(path.read_text()))


@lru_cache
def get_forecast_config() -> ForecastConfig:
    return load_forecast_config()
