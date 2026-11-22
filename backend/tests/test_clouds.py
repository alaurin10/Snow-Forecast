"""A location's cloud layers (analysis/clouds.py), for the map's 3D clouds."""

from __future__ import annotations

from snowwatch.analysis.clouds import cloud_layers, layers_at, sky_cover
from snowwatch.analysis.series import parse_point
from snowwatch.sources.openmeteo import CLOUD_LEVELS
from tests.helpers import synthetic_clouds


def test_a_layer_starts_and_ends_where_the_cover_crosses_the_threshold() -> None:
    # 0% at 1,000 m, 55% at 1,500 m, 95% at 2,000 m, 15% at 2,500 m, 0% at 3,000 m.
    prof = [(1000, 0), (1500, 55), (2000, 95), (2500, 15), (3000, 0)]
    assert layers_at(prof) == [(1140, 2500, 95)]


def test_layers_close_together_are_one_and_far_apart_are_two() -> None:
    near = [(1000, 80), (1400, 10), (1500, 80), (2000, 0)]
    assert len(layers_at(near)) == 1
    far = [(1000, 80), (1500, 0), (2000, 0), (3000, 0), (4000, 60), (5000, 0)]
    lays = layers_at(far)
    assert [c for _, _, c in lays] == [80, 60]
    assert lays[0][0] == 1000  # the lowest level: the base is taken there
    assert lays[1][0] < 4000 < lays[1][1]


def test_clear_skies_and_unsorted_levels() -> None:
    assert layers_at([(2000, 5), (1000, 0), (3000, 10)]) == []
    assert layers_at([(1000, 50)]) == []
    # The highest level cloudy: the layer ends a little above it.
    assert layers_at([(3000, 70), (1000, 0)])[0][1] == 3300
    assert sky_cover([(0, 0, 50), (0, 0, 50)]) == 75


def test_cloud_layers_hour_by_hour_from_a_response() -> None:
    raw = synthetic_clouds({"forecast_days": "2"})
    start = raw["hourly"]["time"][0]
    out = cloud_layers(parse_point(raw), "gfs_seamless", CLOUD_LEVELS, start=start + 600, hours=30)
    assert out is not None and out.start == start and len(out.layers) == 30
    morning, afternoon = out.layers[6], out.layers[14]
    assert morning and morning[0][2] == 40 and afternoon[0][2] == 90
    base, top, _ = afternoon[0]
    assert 1460 < base < 1950 and 2470 < top < 3010
    assert out.cover[14] == 90
    # Past the response's end: no layers, no cover.
    late = cloud_layers(parse_point(raw), "m", CLOUD_LEVELS, start=start + 47 * 3600, hours=3)
    assert late is not None and late.layers[2] == [] and late.cover[2] is None


def test_cloud_layers_read_model_suffixed_names_and_need_some_cover() -> None:
    raw = synthetic_clouds({"forecast_days": "1"})
    named = {k if k == "time" else f"{k}_gem_seamless": v for k, v in raw["hourly"].items()}
    start = raw["hourly"]["time"][0]
    point = parse_point({**raw, "hourly": named})
    assert cloud_layers(point, "gem_seamless", CLOUD_LEVELS, start=start, hours=2) is not None
    empty = parse_point({"hourly": {"time": raw["hourly"]["time"]}})
    assert cloud_layers(empty, "m", CLOUD_LEVELS, start=start, hours=2) is None
