"""Shared helpers for tests that use the captured live fixtures."""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

from snowwatch.analysis.build import ForecastInputs, build_snapshot
from snowwatch.config import ForecastConfig, load_forecast_config
from snowwatch.doc import Snapshot
from snowwatch.inputs import inputs_from_responses, load_responses, load_stations
from snowwatch.locations.service import load_yaml
from snowwatch.models import Location
from snowwatch.settings import REPO_ROOT

FIXTURES = Path(__file__).parent / "fixtures" / "live-20261104"
SEED = REPO_ROOT / "config" / "seed-locations.yaml"


@cache
def config() -> ForecastConfig:
    return load_forecast_config(REPO_ROOT / "config" / "forecast.yaml")


@cache
def seed() -> dict[str, Location]:
    return {loc.id: loc for loc in load_yaml(SEED)}


def captured_at() -> datetime:
    return datetime.fromisoformat(json.loads((FIXTURES / "meta.json").read_text())["captured_at"])


def bc_stations() -> dict[str, dict[str, Any]]:
    """BC snow-pillow stations from the saved WFS sample, shaped like `repo.station_meta`."""
    from snowwatch.sources.bc_asws import station_rows

    rows = station_rows(json.loads((FIXTURES.parent / "bc" / "stations.json").read_text()))
    return {
        r["triplet"]: {
            "stationTriplet": r["triplet"],
            "name": r["name"],
            "elevation": None if r["elev_m"] is None else r["elev_m"] / 0.3048,
            "latitude": r["lat"],
            "longitude": r["lon"],
        }
        for r in rows
    }


@cache
def fixture_inputs(loc_id: str) -> ForecastInputs:
    return inputs_from_responses(
        seed()[loc_id],
        load_responses(FIXTURES / loc_id),
        config(),
        stations={**load_stations(FIXTURES / "shared"), **bc_stations()},
    )


@cache
def fixture_snapshot(loc_id: str) -> Snapshot:
    snap, _ = build_snapshot(seed()[loc_id], fixture_inputs(loc_id), config(), captured_at())
    return snap


BC_DATA = "https://www.env.gov.bc.ca/wsd/data_searches/snow/asws/data/"


def synthetic_clouds(params: dict[str, str]) -> dict[str, Any]:
    """A made-up answer to a location's clouds request (the captured fixtures predate it):
    hourly from the capture's day for `forecast_days`, a deck from about 1,500 m to
    2,500 m, thickest in the afternoon, and each level at a standard height."""
    from snowwatch.sources.openmeteo import CLOUD_LEVELS

    start = int(captured_at().timestamp()) // 86400 * 86400
    hours = int(params.get("forecast_days", "10")) * 24
    times = [start + h * 3600 for h in range(hours)]
    # Heights of the standard atmosphere's pressure levels (m).
    std = {1000: 110, 950: 540, 900: 990, 850: 1460, 800: 1950, 750: 2470, 700: 3010}
    std |= {650: 3590, 600: 4210, 500: 5570, 400: 7190, 300: 9160}
    hourly: dict[str, list[float | int]] = {"time": times}
    for p in CLOUD_LEVELS:
        deck = 800 >= p >= 750
        hourly[f"geopotential_height_{p}hPa"] = [std[p]] * hours
        hourly[f"cloud_cover_{p}hPa"] = [
            (40 + 50 * ((t // 3600) % 24 >= 12)) if deck else 0 for t in times
        ]
    return {"timezone": "UTC", "utc_offset_seconds": 0, "hourly": hourly}


def lean_params(params: Any) -> dict[str, str]:
    """A request with milestone 3's richer variable lists (a self-hosted server) as the
    lean one the fixtures were captured with, so the same fixture answers both."""
    from snowwatch.sources import openmeteo as om

    out = dict(params)
    rich = {
        ",".join(om.BLEND_HOURLY_RICH): om.BLEND_HOURLY,
        ",".join(om.MULTI_HOURLY_RICH): om.MULTI_HOURLY,
        ",".join(om.UPPER_HOURLY_RICH): om.UPPER_HOURLY,
    }
    if out.get("hourly") in rich:
        out["hourly"] = ",".join(rich[out["hourly"]])
    return out


def fixture_transport(*, fail: tuple[str, ...] = (), log: list[str] | None = None) -> Any:
    """An httpx transport that answers with the captured responses.

    Requests are matched on URL and exact parameters, as recorded in meta.json.
    `fail` lists request-name substrings to answer with HTTP 500.
    """
    import httpx

    from snowwatch.capture import load_fixture

    meta = json.loads((FIXTURES / "meta.json").read_text())
    index = {
        (entry["url"], frozenset(entry["params"].items())): key
        for key, entry in meta["requests"].items()
    }

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url.copy_with(query=None))
        if url.startswith(BC_DATA):  # BC snow pillows: small saved CSVs
            name = url.rsplit("/", 1)[-1]
            if log is not None:
                log.append(f"bc/{name}")
            if any(f in "bc_asws" for f in fail):
                return httpx.Response(500)
            return httpx.Response(200, text=(FIXTURES.parent / "bc" / name).read_text())
        params = dict(lean_params(req.url.params))
        if "cloud_cover_850hPa" in params.get("hourly", "").split(","):
            if log is not None:
                log.append("synthetic clouds")
            if any(f in "clouds" for f in fail):
                return httpx.Response(500)
            return httpx.Response(200, json=synthetic_clouds(params))
        key = index.get((url, frozenset(params.items())))
        if key is None and "ensemble" in url and "," in params.get("latitude", ""):
            # Ensembles at all three bands (milestone 4): the captures asked at mid only,
            # so every band gets mid's members (each band's own ensemble, unscaled).
            mid = {k: params[k].split(",")[1] for k in ("latitude", "longitude", "elevation")}
            key = index.get((url, frozenset((params | mid).items())))
            if key is not None:
                if log is not None:
                    log.append(key)
                if any(f in key for f in fail):
                    return httpx.Response(500)
                one = load_fixture(FIXTURES / f"{key}.json.gz")
                return httpx.Response(200, json=[one, one, one])
        if log is not None:
            log.append(key or f"unmatched {url}")
        if key is None:
            return httpx.Response(404, json={"reason": "no fixture"})
        if any(f in key for f in fail):
            return httpx.Response(500)
        return httpx.Response(200, json=load_fixture(FIXTURES / f"{key}.json.gz"))

    return httpx.MockTransport(handler)
