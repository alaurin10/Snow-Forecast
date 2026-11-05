"""Forecast configuration (`config/forecast.yaml`)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

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


class Schedule(BaseModel):
    runs_utc: list[str]
    ensemble_runs_utc: list[str]
    backup_utc: str = "10:00"
    # Avalanche centers publish 6–10 am Mountain time; check again after the runs.
    avalanche_utc: list[str] = []
    vacuum_weekday: str = "sun"


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
    slr_bands: list[SlrBand]
    depth_method: str = "raw"
    schedule: Schedule
    skiday: SkiDayConfig = SkiDayConfig()
    backcountry: BackcountryConfig = BackcountryConfig()
    flags: FlagConfig = FlagConfig()
    # Verification: the snow-to-water ratio for the observed-SWE depth estimate.
    verify_swe_ratio: float = 10

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
