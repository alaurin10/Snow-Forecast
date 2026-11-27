"""Milestone 3's richer variables: asked only of a self-hosted server, a lean request on
the public fallback, and snapshots built from fixtures captured from the server."""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache
from pathlib import Path

import httpx
import pytest

from snowwatch.analysis.build import DailyRecord, build_snapshot
from snowwatch.doc import Snapshot
from snowwatch.http import Fetcher
from snowwatch.inputs import inputs_from_responses, load_responses, load_stations
from snowwatch.sources import openmeteo as om
from snowwatch.sources.base import fetch
from tests.helpers import config, seed

RICH = Path(__file__).parent / "fixtures" / "live-20261127"
LOCAL = "http://om.test:8080"


@cache
def rich(loc_id: str) -> tuple[Snapshot, list[DailyRecord]]:
    at = datetime.fromisoformat(json.loads((RICH / "meta.json").read_text())["captured_at"])
    inputs = inputs_from_responses(
        seed()[loc_id],
        load_responses(RICH / loc_id),
        config(),
        stations=load_stations(RICH / "shared"),
    )
    return build_snapshot(seed()[loc_id], inputs, config(), at)


def test_public_requests_keep_the_lean_lists() -> None:
    loc = seed()["crystal"]
    for lean, full in zip(
        om.location_requests(loc, config(), ensembles=False),
        om.location_requests(loc, config(), ensembles=False, rich=True),
        strict=True,
    ):
        assert lean.lean is None
        if lean.name == "clouds":
            assert full == lean
            continue
        assert full.lean == lean
        assert set(lean.params["hourly"].split(",")) < set(full.params["hourly"].split(","))
    upper = om.upper_air_request(loc, ["gfs_seamless"], rich=True).params["hourly"]
    assert "relative_humidity_750hPa" in upper and "wind_speed_650hPa" in upper


def test_a_fallback_asks_the_public_api_for_the_lean_request() -> None:
    asked: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append((req.url.host, req.url.params["hourly"]))
        if req.url.host == "om.test":
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={})

    f = Fetcher(
        user_agent="t",
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
        local_url=LOCAL,
        public_used=lambda: 0.0,
    )
    req = om.blend_request(seed()["crystal"], rich=True)
    fetch(f, req)
    assert asked[0] == ("om.test", ",".join(om.BLEND_HOURLY_RICH))
    assert asked[1] == ("api.open-meteo.com", ",".join(om.BLEND_HOURLY))
    assert req.lean is not None and f.total_weight == req.lean.weight < req.weight


@pytest.mark.parametrize("loc_id", ["crystal", "snoqualmie", "whistler"])
def test_snapshots_carry_the_new_fields(loc_id: str) -> None:
    snap, records = rich(loc_id)
    mid = snap.bands[1]
    assert set(mid.hourly.snow_level_how) == {"wb"}
    assert any(v is not None for v in mid.hourly.wetbulb_c)
    assert len(mid.hourly.frz) == len(mid.hourly.t)
    assert any(p.slr_col is not None for p in mid.periods)
    assert any(p.wetbulb_max_c is not None for p in mid.periods)
    assert {r.source for r in records} >= {"cons", "cons_slr", "cons_col"}
    bc = snap.backcountry
    assert bc is not None and bc.outlook_steps is not None and bc.outlook_steps.sun_kwh
    assert any(o.sun_kwh and o.sun_kwh["S"] for o in bc.outlook)
    assert all(s.rime_h is not None and s.fog_h is not None for s in bc.sky)
    assert snap.snowpack is not None and snap.snowpack.dates and snap.snowpack.models
    assert snap.ridge is not None


@pytest.mark.parametrize("loc_id", ["crystal", "snoqualmie", "whistler"])
def test_the_snapshot_stays_under_300_kb(loc_id: str) -> None:
    assert len(rich(loc_id)[0].model_dump_json()) < 300_000


def test_column_headline_uses_the_column_ratios() -> None:
    loc = seed()["whistler"]
    at = datetime.fromisoformat(json.loads((RICH / "meta.json").read_text())["captured_at"])
    cfg = config().model_copy(update={"depth_method": "column"})
    inputs = inputs_from_responses(loc, load_responses(RICH / loc.id), cfg, stations={})
    snap, _ = build_snapshot(loc, inputs, cfg, at)
    base, _ = rich("whistler")
    differs = [
        (a, b)
        for a, b in zip(snap.bands[1].periods, base.bands[1].periods, strict=True)
        if a.slr_col is not None and a.slr_col != b.slr
    ]
    assert differs
    for a, b in differs:
        assert a.slr == a.slr_col  # the headline ratio
        assert a.snow_cm_slr == b.snow_cm_slr  # still the temperature-based depth


def test_lean_fixtures_fall_back_to_the_freezing_level() -> None:
    from tests.helpers import fixture_snapshot

    snap = fixture_snapshot("crystal")
    assert set(snap.bands[1].hourly.snow_level_how) <= {"fl", None}
    assert snap.bands[1].hourly.wetbulb_c == []
    assert snap.snowpack is None
    assert all(o.sun_kwh is None for o in snap.backcountry.outlook)  # type: ignore[union-attr]
