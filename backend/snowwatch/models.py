"""Domain models shared by the pipeline, the store and the API."""

from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

BandName = Literal["base", "mid", "summit"]
BAND_ORDER: tuple[BandName, ...] = ("base", "mid", "summit")


class Band(BaseModel):
    band: BandName
    label: str = Field(min_length=1)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    elev_m: float = Field(ge=-500, le=9000)


class AvyRef(BaseModel):
    """Where to find the avalanche forecast. Canadian zones are looked up by point."""

    provider: Literal["nac", "avcan"]
    center_id: str | None = None
    zone_id: str | None = None


class Location(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")
    name: str = Field(min_length=1)
    kind: Literal["resort", "backcountry"]
    region: str = ""
    country: Literal["US", "CA"]
    tz: str | None = None
    bands: list[Band]
    snotel: str | None = Field(default=None, pattern=r"^\d+:[A-Z]{2}:SNTL$")
    nws_office: str | None = None
    radar_station: str | None = None
    avy: AvyRef | None = None
    links: dict[str, str] = {}
    catalog_ref: str | None = None
    active: bool = True
    sort_order: int = 0

    @field_validator("tz")
    @classmethod
    def _valid_tz(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError) as e:
                raise ValueError(f"unknown timezone {v!r}") from e
        return v

    @model_validator(mode="after")
    def _three_rising_bands(self) -> Location:
        names = tuple(b.band for b in self.bands)
        if names != BAND_ORDER:
            raise ValueError(
                f"bands must be exactly {list(BAND_ORDER)} in order, got {list(names)}"
            )
        elevs = [b.elev_m for b in self.bands]
        if not (elevs[0] < elevs[1] < elevs[2]):
            raise ValueError(f"band elevations must rise from base to summit, got {elevs}")
        return self

    def band(self, name: BandName) -> Band:
        return self.bands[BAND_ORDER.index(name)]
