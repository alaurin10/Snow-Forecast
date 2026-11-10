"""Open-Meteo request builders.

Every call uses `timeformat=unixtime` with `timezone=auto`: timestamps are true
instants and the response names the location's timezone, so local periods are
built with zoneinfo and daylight-saving changes come out right.
"""

from __future__ import annotations

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


def blend_request(loc: Location, *, past_days: int = 3, forecast_days: int = 11) -> Request:
    params = {
        **_coords(loc),
        **_common(),
        "hourly": ",".join(BLEND_HOURLY),
        "daily": ",".join(BLEND_DAILY),
        "past_days": str(past_days),
        "forecast_days": str(forecast_days),
    }
    w = estimate_weight(
        points=3,
        days=past_days + forecast_days,
        variables=len(BLEND_HOURLY) + len(BLEND_DAILY),
    )
    return Request("blend", SOURCE, FORECAST_URL, params, w)


def multimodel_request(loc: Location, models: list[str], *, forecast_days: int = 16) -> Request:
    params = {
        **_coords(loc),
        **_common(),
        "hourly": ",".join(MULTI_HOURLY),
        "models": ",".join(models),
        "forecast_days": str(forecast_days),
    }
    w = estimate_weight(points=3, days=forecast_days, variables=len(MULTI_HOURLY) * len(models))
    return Request("multi", SOURCE, FORECAST_URL, params, w)


def upper_air_request(
    loc: Location, models: list[str], *, forecast_days: int = 16, past_days: int = 3
) -> Request:
    """Free-air fields at the summit. The past days feed the wind-loading rose."""
    top = loc.band("summit")
    params = {
        "latitude": f"{top.lat:g}",
        "longitude": f"{top.lon:g}",
        **_common(),
        "hourly": ",".join(UPPER_HOURLY),
        "models": ",".join(models),
        "past_days": str(past_days),
        "forecast_days": str(forecast_days),
    }
    w = estimate_weight(
        points=1, days=forecast_days + past_days, variables=len(UPPER_HOURLY) * len(models)
    )
    return Request("upper", SOURCE, FORECAST_URL, params, w)


def ensemble_request(loc: Location, system: str, *, forecast_days: int = 16) -> Request:
    mid = loc.band("mid")
    params = {
        "latitude": f"{mid.lat:g}",
        "longitude": f"{mid.lon:g}",
        "elevation": f"{mid.elev_m:g}",
        **_common(),
        "hourly": ",".join(ENSEMBLE_HOURLY),
        "models": system,
        "forecast_days": str(forecast_days),
    }
    members = ENSEMBLE_MEMBERS.get(system, 30)
    w = estimate_weight(points=1, days=forecast_days, variables=len(ENSEMBLE_HOURLY) * members)
    return Request(f"ens_{system}", SOURCE, ENSEMBLE_URL, params, w)


def elevation_request(points: list[tuple[float, float]]) -> Request:
    params = {
        "latitude": ",".join(f"{lat:g}" for lat, _ in points),
        "longitude": ",".join(f"{lon:g}" for _, lon in points),
    }
    return Request("elevation", SOURCE, ELEVATION_URL, params, 0.0)


def location_requests(
    loc: Location, cfg: ForecastConfig, *, ensembles: bool = True
) -> list[Request]:
    """Every Open-Meteo request one full run makes for one location."""
    reqs = [
        blend_request(loc),
        multimodel_request(loc, cfg.models_for(loc.country)),
        upper_air_request(loc, cfg.upper_air_models(loc.country)),
    ]
    if ensembles:
        reqs += [ensemble_request(loc, s) for s in cfg.ensembles]
    return reqs


def daily_weight(loc: Location, cfg: ForecastConfig) -> float:
    """Estimated Open-Meteo weight per day for one location on the default schedule."""
    runs = len(cfg.schedule.runs_utc)
    ens_runs = len(cfg.schedule.ensemble_runs_utc)
    base = sum(r.weight for r in location_requests(loc, cfg, ensembles=False))
    ens = sum(ensemble_request(loc, s).weight for s in cfg.ensembles)
    return round(base * runs + ens * ens_runs, 1)
