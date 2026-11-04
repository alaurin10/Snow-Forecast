"""Live checks of every upstream source (`snowwatch check-sources`), written to docs/SOURCES.md.

Run it when a model or endpoint seems to have changed: the report shows which
model provides which variable, how far each model and ensemble reaches, the
snowfall ratio Open-Meteo uses, and the shape of every other endpoint.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from snowwatch.config import ForecastConfig
from snowwatch.http import Fetcher, FetchError
from snowwatch.models import Location
from snowwatch.sources import avalanche_ca, avalanche_us, catalog, nws, snotel
from snowwatch.sources.base import Request, fetch
from snowwatch.sources.openmeteo import (
    ENSEMBLE_URL,
    FORECAST_URL,
    MULTI_HOURLY,
    SOURCE,
    UPPER_HOURLY,
    elevation_request,
)

EXTRA_VARS = ["visibility", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high"]


def _hours_ahead(times: list[int], values: list[float | None], now: float) -> int:
    """Hours of non-null data from now on."""
    last = max((t for t, v in zip(times, values, strict=False) if v is not None), default=None)
    return 0 if last is None else max(0, round((last - now) / 3600))


def model_section(fetcher: Fetcher, loc: Location, models: list[str]) -> list[str]:
    mid = loc.band("mid")
    variables = [*MULTI_HOURLY, *EXTRA_VARS, *UPPER_HOURLY]
    req = Request(
        "check_models",
        SOURCE,
        FORECAST_URL,
        {
            "latitude": f"{mid.lat:g}",
            "longitude": f"{mid.lon:g}",
            "elevation": f"{loc.band('summit').elev_m:g}",
            "timezone": "auto",
            "timeformat": "unixtime",
            "forecast_days": "16",
            "hourly": ",".join(variables),
            "models": ",".join(models),
        },
    )
    data = fetch(fetcher, req)
    hourly = data["hourly"]
    times: list[int] = hourly["time"]
    now = time.time()
    lines = [
        f"### {loc.name} ({loc.country}), summit {loc.band('summit').elev_m:g} m",
        "",
        "| Model | Reach | Missing variables | snow cm per mm water (cold hours) |",
        "|---|---|---|---|",
    ]
    for m in models:
        reach = _hours_ahead(times, hourly.get(f"snowfall_{m}", []), now)
        missing = [
            v for v in variables if not any(x is not None for x in hourly.get(f"{v}_{m}", []))
        ]
        ratios = [
            s / p
            for s, p, t in zip(
                hourly.get(f"snowfall_{m}", []),
                hourly.get(f"precipitation_{m}", []),
                hourly.get(f"temperature_2m_{m}", []),
                strict=False,
            )
            if s is not None and p is not None and t is not None and p >= 0.3 and t <= -3
        ]
        ratio = f"{max(ratios):.2f} max, n={len(ratios)}" if ratios else "no cold precip"
        lines.append(
            f"| `{m}` | {reach} h | {', '.join(f'`{v}`' for v in missing) or 'none'} | {ratio} |"
        )
    return [*lines, ""]


def ensemble_section(fetcher: Fetcher, loc: Location, systems: list[str]) -> list[str]:
    mid = loc.band("mid")
    lines = ["| System | Members | Reach |", "|---|---|---|"]
    now = time.time()
    for system in systems:
        req = Request(
            "check_ens",
            SOURCE,
            ENSEMBLE_URL,
            {
                "latitude": f"{mid.lat:g}",
                "longitude": f"{mid.lon:g}",
                "elevation": f"{mid.elev_m:g}",
                "timezone": "auto",
                "timeformat": "unixtime",
                "forecast_days": "16",
                "hourly": "snowfall",
                "models": system,
            },
        )
        try:
            hourly = fetch(fetcher, req)["hourly"]
        except FetchError as e:
            lines.append(f"| `{system}` | error: {e} | |")
            continue
        keys = [k for k in hourly if k.startswith("snowfall")]
        reach = min(_hours_ahead(hourly["time"], hourly[k], now) for k in keys)
        lines.append(f"| `{system}` | {len(keys)} | {reach} h |")
    return [*lines, ""]


def _keys(d: Any) -> str:
    return ", ".join(f"`{k}`" for k in sorted(d)) if isinstance(d, dict) else type(d).__name__


def endpoint_section(fetcher: Fetcher, us_loc: Location | None) -> list[str]:
    out: list[str] = []

    def attempt(title: str, fn: Callable[[], list[str]]) -> None:
        out.extend([f"### {title}", ""])
        try:
            out.extend(fn())
        except (FetchError, KeyError, IndexError, TypeError) as e:
            out.append(f"Check failed: {e}")
        out.append("")

    def elevation() -> list[str]:
        d = fetch(fetcher, elevation_request([(46.935, -121.475), (48.518, -120.735)]))
        return [f"Two points in one call: `{d}`."]

    def nws_points() -> list[str]:
        assert us_loc is not None
        mid = us_loc.band("mid")
        p = fetch(fetcher, nws.points_request(mid.lat, mid.lon))["properties"]
        wanted = ["cwa", "gridId", "gridX", "gridY", "radarStation", "timeZone", "forecastZone"]
        return [f"`/points` for {us_loc.name}: " + ", ".join(f"`{k}`={p.get(k)}" for k in wanted)]

    def snotel_stations() -> list[str]:
        d = fetch(fetcher, snotel.stations_request("WA"))
        return [f"`stations?stationTriplets=*:WA:SNTL`: {len(d)} stations. Fields: {_keys(d[0])}."]

    def avalanche_org() -> list[str]:
        layer = fetch(fetcher, avalanche_us.map_layer_request())["features"]
        rated = [f for f in layer if (f["properties"].get("danger_level") or -1) >= 1]
        pick = (rated or layer)[0]
        prod = fetch(
            fetcher, avalanche_us.product_request(pick["properties"]["center_id"], str(pick["id"]))
        )
        return [
            f"Map layer: {len(layer)} zones ({len(rated)} rated now). "
            f"Properties: {_keys(pick['properties'])}.",
            "",
            f"Product for {pick['properties']['center_id']} zone {pick['id']} "
            f"(`{prod.get('product_type')}`): {_keys(prod)}. `danger`: `{prod.get('danger')}`.",
        ]

    def avcan() -> list[str]:
        areas = fetch(fetcher, avalanche_ca.areas_request())["features"]
        prods = fetch(fetcher, avalanche_ca.products_request())
        report = prods[0]["report"] if prods else {}
        sample = (report.get("dangerRatings") or [{}])[0]
        return [
            f"Areas: {len(areas)} polygons; feature fields {_keys(areas[0])}.",
            "",
            f"Products: {len(prods)}; product fields {_keys(prods[0]) if prods else '-'}; "
            f"report fields {_keys(report)}.",
            "",
            f"One `dangerRatings` entry: `{sample}`.",
        ]

    def ski_areas() -> list[str]:
        feats = fetch(fetcher, catalog.ski_areas_request())["features"]
        na = [
            f
            for f in feats
            if any(
                p.get("iso3166_1Alpha2") in ("US", "CA")
                for p in f["properties"].get("places") or []
            )
            and "downhill" in (f["properties"].get("activities") or [])
            and f["properties"].get("status") == "operating"
            and f["properties"].get("name")
        ]
        with_elev = [f for f in na if (f["properties"].get("statistics") or {}).get("maxElevation")]
        return [
            f"{len(feats)} ski areas worldwide; {len(na)} named, operating downhill areas in the "
            f"US and Canada, {len(with_elev)} with elevation statistics.",
            "",
            f"Properties: {_keys(feats[0]['properties'])}.",
        ]

    attempt("Open-Meteo elevation", elevation)
    if us_loc is not None:
        attempt("NWS", nws_points)
    attempt("SNOTEL (AWDB)", snotel_stations)
    attempt("avalanche.org", avalanche_org)
    attempt("Avalanche Canada", avcan)
    attempt("OpenSkiMap ski areas", ski_areas)
    return out


def build_report(fetcher: Fetcher, locs: list[Location], cfg: ForecastConfig) -> str:
    us = next((loc for loc in locs if loc.country == "US"), None)
    ca = next((loc for loc in locs if loc.country == "CA"), None)
    lines = [
        "# Data source check",
        "",
        f"Generated by `snowwatch check-sources` on "
        f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}. "
        "Reach counts hours of data from the time of the check.",
        "",
        "## Open-Meteo forecast models",
        "",
    ]
    for loc in (us, ca):
        if loc is not None:
            lines += model_section(fetcher, loc, cfg.models_for(loc.country))
    if ratios_note := _ratio_note(lines):
        lines += [ratios_note, ""]
    if us is not None:
        lines += ["## Open-Meteo ensembles", "", *ensemble_section(fetcher, us, cfg.ensembles)]
    lines += ["## Other endpoints", "", *endpoint_section(fetcher, us)]
    return "\n".join(lines).rstrip() + "\n"


def _ratio_note(lines: list[str]) -> str:
    vals = []
    for line in lines:
        if line.startswith("| `") and " max, n=" in line:
            vals.append(float(line.split("|")[4].split(" max")[0]))
    if not vals:
        return ""
    return (
        "Snowfall ratio: in cold hours, model snowfall tops out at "
        f"{statistics.median(vals):.2f} cm per mm of water, Open-Meteo's fixed 7:1 conversion."
    )
