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


@cache
def fixture_inputs(loc_id: str) -> ForecastInputs:
    return inputs_from_responses(
        seed()[loc_id],
        load_responses(FIXTURES / loc_id),
        config(),
        stations=load_stations(FIXTURES / "shared"),
    )


@cache
def fixture_snapshot(loc_id: str) -> Snapshot:
    snap, _ = build_snapshot(seed()[loc_id], fixture_inputs(loc_id), config(), captured_at())
    return snap


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
        key = index.get((url, frozenset(dict(req.url.params).items())))
        if log is not None:
            log.append(key or f"unmatched {url}")
        if key is None:
            return httpx.Response(404, json={"reason": "no fixture"})
        if any(f in key for f in fail):
            return httpx.Response(500)
        return httpx.Response(200, json=load_fixture(FIXTURES / f"{key}.json.gz"))

    return httpx.MockTransport(handler)
