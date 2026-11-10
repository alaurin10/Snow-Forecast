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
from snowwatch.settings import get_settings


class ModelSets(BaseModel):
    global_: list[str] = Field(alias="global")
    short_range: dict[str, list[str]] = {}
    upper_air_exclude: list[str] = []


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
    runs_utc: list[HHMM] = Field(min_length=1)
    ensemble_runs_utc: list[HHMM]
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
    forecast_minutes: int = Field(30, ge=5)
    totals_minutes: int = Field(60, ge=10)

    @field_validator("region")
    @classmethod
    def _box(cls, v: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        south, west, north, east = v
        if not (-85 <= south < north <= 85 and -180 <= west < east <= 180):
            raise ValueError("map.region is [south, west, north, east] in degrees")
        return v


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
    depth_method: Literal["raw", "slr"] = "raw"
    schedule: Schedule
    skiday: SkiDayConfig = SkiDayConfig()
    backcountry: BackcountryConfig = BackcountryConfig()
    flags: FlagConfig = FlagConfig()
    map: MapConfig = MapConfig()
    # Verification: the snow-to-water ratio for the observed-SWE depth estimate.
    verify_swe_ratio: float = 10

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


def load_forecast_config(path: Path | None = None) -> ForecastConfig:
    path = path or get_settings().config_dir / "forecast.yaml"
    return ForecastConfig.model_validate(yaml.safe_load(path.read_text()))


@lru_cache
def get_forecast_config() -> ForecastConfig:
    return load_forecast_config()
