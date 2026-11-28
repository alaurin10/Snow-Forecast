"""Open-Meteo request builders.

Every call uses `timeformat=unixtime` with `timezone=auto`: timestamps are true
instants and the response names the location's timezone, so local periods are
built with zoneinfo and daylight-saving changes come out right.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from snowwatch.config import ForecastConfig
from snowwatch.models import Location
from snowwatch.sources.base import Request

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
SOURCE = "open-meteo"

BLEND_HOURLY = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "showers",
    "snowfall",
    "precipitation_probability",
    "freezing_level_height",
    "weather_code",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "visibility",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
    "is_day",
]
BLEND_DAILY = ["sunrise", "sunset", "daylight_duration"]

# Surface fields per model, at every band's point.
MULTI_HOURLY = [
    "snowfall",
    "precipitation",
    "rain",
    "temperature_2m",
    "freezing_level_height",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
    "cloud_cover",
]

# Free-air fields per model, at one point. Pressure-level values don't depend on
# the requested elevation, so one point serves all three bands.
PRESSURE_LEVELS = (850, 700, 600, 500)
UPPER_HOURLY = [
    "wind_speed_850hPa",
    "wind_direction_850hPa",
    "wind_speed_700hPa",
    "wind_direction_700hPa",
    *[f"temperature_{p}hPa" for p in PRESSURE_LEVELS],
    *[f"geopotential_height_{p}hPa" for p in PRESSURE_LEVELS],
]

# Richer lists (docs/OPEN-METEO-PLAN.md milestone 3), asked for only from a self-hosted
# server (`rich=True`), where requests cost nothing; the public API keeps the lean lists
# above. Names and which models carry them were checked against the server on
# 27 Nov 2026 (docs/SOURCES.md). A model without a field answers with empty values,
# which `split_models` drops, so every one is optional.
SURFACE_EXTRA = [
    "relative_humidity_2m",
    "dew_point_2m",
    "wet_bulb_temperature_2m",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "snow_depth",
    "cape",
]
# Model-specific: NBM's snow level and chances (US), GFS's and HRRR's freezing-rain flag,
# ECMWF's precipitation type (WMO code table 4.201: 3 freezing rain, 8 ice pellets,
# 12 freezing drizzle).
MODEL_EXTRA = [
    "snowfall_height",
    "snowfall_probability",
    "freezing_rain_probability",
    "ice_pellets_probability",
    "categorical_freezing_rain",
    "precipitation_type",
]
RICH_LEVELS = (850, 800, 750, 700, 650, 600, 500)
UPPER_HOURLY_RICH = [
    f"{v}_{p}hPa"
    for p in RICH_LEVELS
    for v in (
        "temperature",
        "relative_humidity",
        "wind_speed",
        "wind_direction",
        "geopotential_height",
    )
]
BLEND_HOURLY_RICH = [*BLEND_HOURLY, *SURFACE_EXTRA]
MULTI_HOURLY_RICH = [*MULTI_HOURLY, *SURFACE_EXTRA, *MODEL_EXTRA]

# One model's cloud cover through the air above a location, for its cloud layers (the
# map's 3D clouds): every ~50 hPa (~500 m) through the heights mountains reach, coarser
# above. The pressure levels' heights come with them.
CLOUD_LEVELS = (1000, 950, 900, 850, 800, 750, 700, 650, 600, 500, 400, 300)
CLOUD_HOURLY = [
    *[f"cloud_cover_{p}hPa" for p in CLOUD_LEVELS],
    *[f"geopotential_height_{p}hPa" for p in CLOUD_LEVELS],
]
CLOUD_DAYS = 10  # the map's timeline

# Per model at the snow station's own spot and elevation, for the scorecard only: the
# bands stay where the location puts them.
STATION_HOURLY = ["snowfall", "precipitation"]

ENSEMBLE_HOURLY = ["snowfall"]
ENSEMBLE_MEMBERS = {"gfs_seamless": 31, "ecmwf_ifs025": 51, "gem_global": 21, "icon_seamless": 40}


def estimate_weight(*, points: int, days: int, variables: int) -> float:
    """Open-Meteo's fractional call count, roughly.

    A call counts as more than one when it asks for more than 10 variables
    (variables multiply by models and ensemble members) or more than 14 days;
    each location counts separately.
    """
    return round(points * max(1.0, days / 14) * max(1.0, variables / 10), 2)


def _coords(loc: Location) -> dict[str, str]:
    return {
        "latitude": ",".join(f"{b.lat:g}" for b in loc.bands),
        "longitude": ",".join(f"{b.lon:g}" for b in loc.bands),
        "elevation": ",".join(f"{b.elev_m:g}" for b in loc.bands),
    }


def _common() -> dict[str, str]:
    return {"timezone": "auto", "timeformat": "unixtime"}


def blend_request(
    loc: Location, *, past_days: int = 3, forecast_days: int = 11, rich: bool = False
) -> Request:
    hourly = BLEND_HOURLY_RICH if rich else BLEND_HOURLY
    params = {
        **_coords(loc),
        **_common(),
        "hourly": ",".join(hourly),
        "daily": ",".join(BLEND_DAILY),
        "past_days": str(past_days),
        "forecast_days": str(forecast_days),
    }
    w = estimate_weight(
        points=3,
        days=past_days + forecast_days,
        variables=len(hourly) + len(BLEND_DAILY),
    )
    lean = blend_request(loc, past_days=past_days, forecast_days=forecast_days) if rich else None
    return Request("blend", SOURCE, FORECAST_URL, params, w, lean)


def multimodel_request(
    loc: Location, models: list[str], *, forecast_days: int = 16, rich: bool = False
) -> Request:
    hourly = MULTI_HOURLY_RICH if rich else MULTI_HOURLY
    params = {
        **_coords(loc),
        **_common(),
        "hourly": ",".join(hourly),
        "models": ",".join(models),
        "forecast_days": str(forecast_days),
    }
    w = estimate_weight(points=3, days=forecast_days, variables=len(hourly) * len(models))
    lean = multimodel_request(loc, models, forecast_days=forecast_days) if rich else None
    return Request("multi", SOURCE, FORECAST_URL, params, w, lean)


def upper_air_request(
    loc: Location,
    models: list[str],
    *,
    forecast_days: int = 16,
    past_days: int = 3,
    rich: bool = False,
) -> Request:
    """Free-air fields at the summit. The past days feed the wind-loading rose."""
    top = loc.band("summit")
    hourly = UPPER_HOURLY_RICH if rich else UPPER_HOURLY
    params = {
        "latitude": f"{top.lat:g}",
        "longitude": f"{top.lon:g}",
        **_common(),
        "hourly": ",".join(hourly),
        "models": ",".join(models),
        "past_days": str(past_days),
        "forecast_days": str(forecast_days),
    }
    w = estimate_weight(
        points=1, days=forecast_days + past_days, variables=len(hourly) * len(models)
    )
    lean = (
        upper_air_request(loc, models, forecast_days=forecast_days, past_days=past_days)
        if rich
        else None
    )
    return Request("upper", SOURCE, FORECAST_URL, params, w, lean)


def clouds_request(loc: Location, model: str, *, forecast_days: int = CLOUD_DAYS) -> Request:
    """One model's cloud cover at every pressure level over the location's middle."""
    mid = loc.band("mid")
    params = {
        "latitude": f"{mid.lat:g}",
        "longitude": f"{mid.lon:g}",
        **_common(),
        "hourly": ",".join(CLOUD_HOURLY),
        "models": model,
        "forecast_days": str(forecast_days),
    }
    w = estimate_weight(points=1, days=forecast_days, variables=len(CLOUD_HOURLY))
    return Request("clouds", SOURCE, FORECAST_URL, params, w)


def station_request(
    lat: float, lon: float, elev_m: float, models: list[str], *, forecast_days: int = 3
) -> Request:
    """Each model's snowfall and precipitation at the snow station, so the scorecard
    compares the station with a forecast for where it is, not for the mid band. Three
    days covers every forecast the scorecard keeps (up to two days ahead)."""
    params = {
        "latitude": f"{lat:g}",
        "longitude": f"{lon:g}",
        "elevation": f"{elev_m:.0f}",
        **_common(),
        "hourly": ",".join(STATION_HOURLY),
        "models": ",".join(models),
        "forecast_days": str(forecast_days),
    }
    w = estimate_weight(points=1, days=forecast_days, variables=len(STATION_HOURLY) * len(models))
    return Request("station", SOURCE, FORECAST_URL, params, w)


def ensemble_request(
    loc: Location, system: str, *, forecast_days: int = 16, bands: bool = True
) -> Request:
    """One system's members' snowfall for 16 days (days 11–16 show in the Confidence
    tab's running totals and day chart). `bands`: at base, mid and summit in one request
    (three points, weight × 3; milestone 4), so each band has its own ensemble; else mid
    only, which the other bands scale."""
    pts = loc.bands if bands else [loc.band("mid")]
    params = {
        "latitude": ",".join(f"{b.lat:g}" for b in pts),
        "longitude": ",".join(f"{b.lon:g}" for b in pts),
        "elevation": ",".join(f"{b.elev_m:g}" for b in pts),
        **_common(),
        "hourly": ",".join(ENSEMBLE_HOURLY),
        "models": system,
        "forecast_days": str(forecast_days),
    }
    members = ENSEMBLE_MEMBERS.get(system, 30)
    w = estimate_weight(
        points=len(pts), days=forecast_days, variables=len(ENSEMBLE_HOURLY) * members
    )
    return Request(f"ens_{system}", SOURCE, ENSEMBLE_URL, params, w)


def elevation_request(points: list[tuple[float, float]]) -> Request:
    params = {
        "latitude": ",".join(f"{lat:g}" for lat, _ in points),
        "longitude": ",".join(f"{lon:g}" for _, lon in points),
    }
    return Request("elevation", SOURCE, ELEVATION_URL, params, 0.0)


def location_requests(
    loc: Location, cfg: ForecastConfig, *, ensembles: bool = True, rich: bool = False
) -> list[Request]:
    """Every Open-Meteo request one full run makes for one location. `rich`: the longer
    variable lists, for a self-hosted server."""
    reqs = [
        blend_request(loc, rich=rich),
        multimodel_request(loc, cfg.models_for(loc.country), rich=rich),
        upper_air_request(loc, cfg.upper_air_models(loc.country), rich=rich),
    ]
    cloud_model = cfg.cloud_model(loc.country)
    if cloud_model:
        reqs.append(clouds_request(loc, cloud_model))
    if ensembles:
        reqs += [ensemble_request(loc, s) for s in cfg.ensembles]
    return reqs


def public_daily_weight(loc: Location, cfg: ForecastConfig, local: Collection[str] = ()) -> float:
    """Estimated weight per day of one location's ensembles on the public API at their
    richest (all three bands, every scheduled run; `snowwatch/budget.py` picks the tier
    actually used): every system but those the self-hosted server answers (`local`,
    milestone 1b), which are free."""
    ens = sum(
        ensemble_request(loc, s).weight * len(cfg.schedule.runs_for(s))
        for s in cfg.ensembles
        if s not in local
    )
    return round(ens, 1)


def local_daily_weight(loc: Location, cfg: ForecastConfig) -> float:
    """Estimated weight per day of everything else (forecasts at every band, upper air,
    clouds): free on a self-hosted server, public otherwise."""
    base = sum(r.weight for r in location_requests(loc, cfg, ensembles=False))
    return round(base * len(cfg.schedule.runs_utc), 1)


def daily_weight(loc: Location, cfg: ForecastConfig) -> float:
    """Estimated Open-Meteo weight per day for one location on the default schedule."""
    return round(public_daily_weight(loc, cfg) + local_daily_weight(loc, cfg), 1)


def merge_models(answers: dict[str, Any]) -> Any:
    """Single-model answers (`{model: answer}`, each from a request with one `models`)
    joined into the answer one request for all of them gives: each hourly field gets the
    model's suffix (`snowfall` → `snowfall_gfs_seamless`), aligned on the first answer's
    hours. Multi-point answers (lists) are joined point by point.

    The self-hosted server reads one request's models one after another; asked for one
    model each, at once, a new area's multi-model forecast came back in 3.8 s instead of
    13 s (spots, docs/OPEN-METEO-PLAN.md milestone 2)."""
    models = list(answers)
    if not models:
        raise ValueError("no answers to merge")
    first = answers[models[0]]
    if isinstance(first, list):
        return [
            _merge_point({m: answers[m][i] for m in models if i < len(answers[m])})
            for i in range(len(first))
        ]
    return _merge_point(answers)


def _merge_point(answers: dict[str, Any]) -> dict[str, Any]:
    base = next(iter(answers.values()))
    times = list((base.get("hourly") or {}).get("time") or [])
    out = {k: v for k, v in base.items() if k not in ("hourly", "hourly_units")}
    hourly: dict[str, list[Any]] = {"time": times}
    units: dict[str, Any] = {"time": (base.get("hourly_units") or {}).get("time", "unixtime")}
    for model, ans in answers.items():
        h = ans.get("hourly") or {}
        own = h.get("time") or []
        at = {t: i for i, t in enumerate(own)}
        same = list(own) == times
        for key, values in h.items():
            if key == "time":
                continue
            name = f"{key}_{model}"
            if same:
                hourly[name] = list(values)
            else:
                hourly[name] = [values[at[t]] if t in at else None for t in times]
            units[name] = (ans.get("hourly_units") or {}).get(key)
    out["hourly"] = hourly
    out["hourly_units"] = units
    return out
