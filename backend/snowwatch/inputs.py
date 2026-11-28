"""Assemble `ForecastInputs` from raw responses, whether just fetched, cached or fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from snowwatch.analysis.build import ForecastInputs
from snowwatch.analysis.series import parse_point, parse_points
from snowwatch.capture import load_fixture
from snowwatch.config import ForecastConfig
from snowwatch.geo import haversine_km
from snowwatch.models import Location
from snowwatch.sources import bc_asws
from snowwatch.sources.nws import parse_alerts
from snowwatch.sources.snotel import parse_snotel


class MissingInput(ValueError):
    """A response the forecast can't be built without (blend or multi-model)."""


def inputs_from_responses(
    loc: Location,
    responses: Mapping[str, Any],
    cfg: ForecastConfig,
    *,
    stations: Mapping[str, Mapping[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> ForecastInputs:
    """responses: request name → parsed JSON (`blend`, `multi`, `upper`, `ens_<system>`, …)."""
    for required in ("blend", "multi"):
        if required not in responses:
            raise MissingInput(f"{loc.id}: no {required} response")
    blend = parse_points(responses["blend"])
    multi = parse_points(responses["multi"])
    if len(blend) != 3 or len(multi) != 3:
        raise MissingInput(f"{loc.id}: expected 3 points, got {len(blend)} and {len(multi)}")
    inputs = ForecastInputs(
        blend=blend,
        multi=multi,
        upper=parse_point(responses["upper"]) if "upper" in responses else None,
        clouds=parse_point(responses["clouds"]) if "clouds" in responses else None,
        warnings=list(warnings or []),
    )
    # Ensembles: one point (mid, as before milestone 4) or all three bands in one answer.
    for s in cfg.ensembles:
        resp = responses.get(f"ens_{s}")
        if resp is None:
            continue
        pts = parse_points(resp)
        if len(pts) == 3:
            inputs.ensembles[s] = pts[1]
            inputs.ensemble_bands[s] = pts
        elif pts:
            inputs.ensembles[s] = pts[0]
    if isinstance(responses.get("station"), dict):
        inputs.station = parse_point(responses["station"])
    if "nws_alerts" in responses:
        inputs.alerts = parse_alerts(responses["nws_alerts"])
    station = (stations or {}).get(loc.snotel) if loc.snotel else None
    if loc.snotel and bc_asws.is_bc(loc.snotel) and "bc_asws" in responses:
        tz = loc.tz or blend[1].tz
        inputs.snotel = bc_asws.parse_station(loc.snotel, responses["bc_asws"], station, tz)
    elif loc.snotel and "snotel_daily" in responses and "snotel_hourly" in responses:
        inputs.snotel = parse_snotel(
            loc.snotel, responses["snotel_daily"], responses["snotel_hourly"], station
        )
    if inputs.snotel is not None and station and station.get("latitude") is not None:
        mid = loc.band("mid")
        inputs.snotel.distance_km = round(
            haversine_km(mid.lat, mid.lon, float(station["latitude"]), float(station["longitude"])),
            1,
        )
    return inputs


def load_responses(folder: Path) -> dict[str, Any]:
    """Every `<name>.json.gz` in a folder, keyed by name."""
    return {
        p.name.removesuffix(".json.gz"): load_fixture(p) for p in sorted(folder.glob("*.json.gz"))
    }


def load_stations(shared: Path) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for p in shared.glob("snotel_stations_*.json.gz"):
        for s in load_fixture(p):
            out[s["stationTriplet"]] = s
    return out
