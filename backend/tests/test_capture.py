from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from snowwatch.capture import capture_fixtures, load_fixture
from snowwatch.config import ForecastConfig
from snowwatch.http import Fetcher
from snowwatch.locations.service import load_yaml
from tests.conftest import SEED


def test_capture_writes_expected_tree(tmp_path: Path, cfg: ForecastConfig) -> None:
    locs = [loc for loc in load_yaml(SEED) if loc.id in ("crystal", "whistler")]

    def handler(req: httpx.Request) -> httpx.Response:
        if "avalanche.org" in req.url.host and "map-layer" in req.url.path:
            return httpx.Response(500)
        return httpx.Response(200, json={"path": req.url.path})

    fetcher = Fetcher(user_agent="t", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    meta = capture_fixtures(
        locs, fetcher, tmp_path, cfg, spacing_s=0, today=date(2026, 11, 4), log=lambda m: None
    )
    names = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.json.gz")}
    for n in ("blend", "multi", "upper", "ens_gem_global", "proto_det", "proto_ens_ecmwf_ifs025"):
        assert f"crystal/{n}.json.gz" in names and f"whistler/{n}.json.gz" in names
    assert "crystal/nws_alerts.json.gz" in names and "crystal/snotel_daily.json.gz" in names
    assert "whistler/nws_alerts.json.gz" not in names
    assert "shared/snotel_stations_WA.json.gz" in names
    # The failed map layer is reported, not fatal.
    assert any("avalanche_us_map_layer" in e for e in meta["errors"])
    saved = json.loads((tmp_path / "meta.json").read_text())
    assert saved["requests"]["crystal/blend"]["params"]["timeformat"] == "unixtime"
    assert load_fixture(tmp_path / "crystal" / "blend.json.gz") == {"path": "/v1/forecast"}
