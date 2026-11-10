"""Domain models shared by the pipeline, the store and the API."""

from __future__ import annotations

from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator

from snowwatch.urls import check_url

Link = Annotated[str, AfterValidator(check_url)]

BandName = Literal["base", "mid", "summit"]
BAND_ORDER: tuple[BandName, ...] = ("base", "mid", "summit")


class Band(BaseModel):
    band: BandName
    label: str = Field(min_length=1, max_length=40)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    elev_m: float = Field(ge=-500, le=9000)


class AvyRef(BaseModel):
    """Where to find the avalanche forecast. Canadian zones are looked up by point."""

    provider: Literal["nac", "avcan"]
    center_id: str | None = Field(default=None, max_length=40)
    zone_id: str | None = Field(default=None, max_length=40)


class Webcam(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    url: Link  # the webcam's page
    image_url: Link | None = None  # a still image, if any (https, or browsers block it)


class Location(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["resort", "backcountry"]
    region: str = Field(default="", max_length=80)
    country: Literal["US", "CA"]
    tz: str | None = None
    bands: list[Band]
    # Snow station: a SNOTEL triplet ("672:WA:SNTL") or a BC River Forecast
    # Centre automated station ("3A20P:BC:ASWS").
    snotel: str | None = Field(default=None, pattern=r"^(\d+:[A-Z]{2}:SNTL|[0-9A-Z]+:BC:ASWS)$")
    nws_office: str | None = Field(default=None, pattern=r"^[A-Z]{3,4}$")
    radar_station: str | None = Field(default=None, pattern=r"^[A-Z0-9]{3,5}$")
    avy: AvyRef | None = None
    links: dict[Annotated[str, Field(min_length=1, max_length=60)], Link] = Field(
        default={}, max_length=12
    )
    webcams: list[Webcam] = []
    catalog_ref: str | None = Field(default=None, max_length=100)
    active: bool = True
    sort_order: int = 0

    @field_validator("webcams")
    @classmethod
    def _few_webcams(cls, v: list[Webcam]) -> list[Webcam]:
        # A validator, not max_length: a JSON Schema maxItems turns the TS type into tuples.
        if len(v) > 12:
            raise ValueError("at most 12 webcams")
        return v

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
