from __future__ import annotations

from snowwatch.config import ForecastConfig
from snowwatch.locations.service import load_yaml
from snowwatch.sources import openmeteo as om
from tests.conftest import SEED, make_location


def test_blend_asks_for_three_points_in_unixtime() -> None:
    loc = make_location()
    req = om.blend_request(loc)
    assert req.params["latitude"] == "47,47,47.01"
    assert req.params["elevation"] == "1000,1500,2000"
    assert req.params["timeformat"] == "unixtime" and req.params["timezone"] == "auto"
    assert "snowfall" in req.params["hourly"] and "is_day" in req.params["hourly"]


def test_model_sets_by_country(cfg: ForecastConfig) -> None:
    us = cfg.models_for("US")
    ca = cfg.models_for("CA")
    assert us[:4] == ca[:4] == ["gfs_seamless", "ecmwf_ifs025", "gem_seamless", "icon_seamless"]
    assert us[4:] == ["ncep_hrrr_conus", "ncep_nbm_conus"]
    assert ca[4:] == ["gem_hrdps_continental"]
    assert "ncep_nbm_conus" not in cfg.upper_air_models("US")


def test_upper_air_is_one_point_at_the_summit(cfg: ForecastConfig) -> None:
    loc = make_location()
    req = om.upper_air_request(loc, cfg.upper_air_models("US"))
    assert req.params["latitude"] == "47.01"
    assert "elevation" not in req.params
    assert "geopotential_height_500hPa" in req.params["hourly"]


def test_ensemble_at_mid(cfg: ForecastConfig) -> None:
    req = om.ensemble_request(make_location(), "ecmwf_ifs025")
    assert req.url == om.ENSEMBLE_URL
    assert req.params["elevation"] == "1500" and req.params["models"] == "ecmwf_ifs025"


def test_weights() -> None:
    assert om.estimate_weight(points=1, days=7, variables=5) == 1
    assert om.estimate_weight(points=3, days=14, variables=10) == 3
    assert om.estimate_weight(points=1, days=28, variables=20) == 4
    small = om.estimate_weight(points=1, days=16, variables=21)
    big = om.estimate_weight(points=1, days=16, variables=51)
    assert big > small


def test_full_run_requests_and_daily_budget(cfg: ForecastConfig) -> None:
    locs = load_yaml(SEED)
    reqs = om.location_requests(locs[0], cfg)
    assert [r.name for r in reqs] == [
        "blend",
        "multi",
        "upper",
        "ens_gfs_seamless",
        "ens_ecmwf_ifs025",
        "ens_gem_global",
    ]
    per_day = [om.daily_weight(loc, cfg) for loc in locs]
    # 25 locations must fit comfortably inside the 10,000-call free tier.
    assert max(per_day) * 25 < 6000
