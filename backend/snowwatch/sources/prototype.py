"""The prototype's exact Open-Meteo requests (docs/reference/pull.py `fetch`).

Captured alongside the v2 requests so the parity test can run the prototype's
own analysis on the same data the new pipeline sees.
"""

from __future__ import annotations

from snowwatch.models import Location
from snowwatch.sources.base import Request
from snowwatch.sources.openmeteo import ENSEMBLE_URL, FORECAST_URL, SOURCE

PROTO_MODELS = {
    "gfs": "gfs_seamless",
    "ecmwf": "ecmwf_ifs025",
    "gem": "gem_seamless",
    "icon": "icon_seamless",
}
PROTO_ENS = ["gfs_seamless", "ecmwf_ifs025"]
PROTO_HOURLY = (
    "temperature_2m,snowfall,rain,showers,precipitation,precipitation_probability,"
    "freezing_level_height,wind_speed_10m,wind_gusts_10m,wind_direction_10m,cloud_cover,weather_code"
)
PROTO_CURRENT = "temperature_2m,weather_code,wind_speed_10m,wind_gusts_10m,freezing_level_height"


def prototype_requests(loc: Location) -> list[Request]:
    lat, lon = loc.band("mid").lat, loc.band("mid").lon
    mid_m = loc.band("mid").elev_m
    det = Request(
        "proto_det",
        SOURCE,
        FORECAST_URL,
        {
            "latitude": ",".join([str(lat)] * 3),
            "longitude": ",".join([str(lon)] * 3),
            "elevation": ",".join(f"{b.elev_m:g}" for b in loc.bands),
            "timezone": "auto",
            "past_days": "1",
            "forecast_days": "11",
            "hourly": PROTO_HOURLY,
            "current": PROTO_CURRENT,
        },
    )
    multi = Request(
        "proto_multi",
        SOURCE,
        FORECAST_URL,
        {
            "latitude": str(lat),
            "longitude": str(lon),
            "elevation": f"{mid_m:g}",
            "timezone": "auto",
            "forecast_days": "16",
            "hourly": "snowfall",
            "models": ",".join(PROTO_MODELS.values()),
        },
    )
    ens = [
        Request(
            f"proto_ens_{m}",
            SOURCE,
            ENSEMBLE_URL,
            {
                "latitude": str(lat),
                "longitude": str(lon),
                "elevation": f"{mid_m:g}",
                "timezone": "auto",
                "forecast_days": "16",
                "hourly": "snowfall",
                "models": m,
            },
        )
        for m in PROTO_ENS
    ]
    return [det, multi, *ens]
