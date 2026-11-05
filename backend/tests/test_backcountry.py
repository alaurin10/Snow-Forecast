from __future__ import annotations

import pytest

from snowwatch.analysis.backcountry import (
    BackcountryConfig,
    loading_rose,
    max_rise,
    refreeze,
    sector_of,
    sky,
)

CFG = BackcountryConfig()
H = 3600


def hours(n: int) -> list[int]:
    return [i * H for i in range(n)]


@pytest.mark.parametrize(
    ("deg", "sector"), [(0, 0), (22, 0), (23, 1), (225, 5), (337.4, 7), (337.6, 0), (359, 0)]
)
def test_sectors(deg: float, sector: int) -> None:
    assert sector_of(deg) == sector


def test_sw_wind_loads_ne() -> None:
    hs = hours(10)
    rose = loading_rose(
        hs, dict.fromkeys(hs, 1.0), dict.fromkeys(hs, 40.0), dict.fromkeys(hs, 225.0), CFG
    )
    assert rose.wind_from == "SW" and rose.loading == ["NE"]
    assert rose.label == "SW wind, loading NE aspects"
    assert rose.sectors[5] == 1.0 and sum(rose.sectors) == pytest.approx(1)


def test_strong_neighbour_joins_the_label() -> None:
    hs = hours(10)
    direction = {h: 225.0 if i < 6 else 270.0 for i, h in enumerate(hs)}
    rose = loading_rose(hs, dict.fromkeys(hs, 1.0), dict.fromkeys(hs, 40.0), direction, CFG)
    assert rose.wind_from == "SW–W" and rose.loading == ["NE", "E"]


def test_snowfall_weights_the_rose() -> None:
    hs = hours(4)
    snow = {0: 5.0, H: 5.0, 2 * H: 0.0, 3 * H: 0.0}  # it snows only in the south wind
    direction = {0: 180.0, H: 180.0, 2 * H: 0.0, 3 * H: 0.0}
    rose = loading_rose(hs, snow, dict.fromkeys(hs, 40.0), direction, CFG)
    assert rose.wind_from == "S" and rose.loading == ["N"]


def test_no_snow_or_light_wind() -> None:
    hs = hours(5)
    calm = loading_rose(hs, dict.fromkeys(hs, 0.1), dict.fromkeys(hs, 40.0), {}, CFG)
    assert calm.label == "Little new snow to move" and calm.loading == []
    light = loading_rose(
        hs, dict.fromkeys(hs, 2.0), dict.fromkeys(hs, 5.0), dict.fromkeys(hs, 90.0), CFG
    )
    assert light.label.startswith("Light wind") and light.loading == []


def test_max_rise_over_24_hours() -> None:
    hs = hours(72)
    fl = {h: 1000.0 + (900 if i >= 30 else 0) for i, h in enumerate(hs)}
    rise = max_rise(fl, hs)
    assert rise.amount == 900 and rise.end == 30 * H


def test_max_rise_needs_a_full_day() -> None:
    assert max_rise({0: 1.0, H: 5.0}, hours(2)).amount is None


@pytest.mark.parametrize(
    ("low", "cloud", "status"),
    [(-5, 10, "Good"), (-5, 90, "Partial"), (-1, 10, "Partial"), (2, 0, "None")],
)
def test_refreeze(low: float, cloud: float, status: str) -> None:
    hs = hours(12)
    temps = {h: low + (3 if i < 6 else 0) for i, h in enumerate(hs)}
    out = refreeze(hs, temps, dict.fromkeys(hs, cloud), CFG)
    assert out.status == status and out.low_c == low


def test_refreeze_without_data() -> None:
    assert refreeze(hours(3), {}, {}, CFG).status == "Unknown"


def test_sky_uses_daylight_hours() -> None:
    hs = hours(4)
    is_day = {0: 0.0, H: 1.0, 2 * H: 1.0, 3 * H: 0.0}
    low = {0: 100.0, H: 20.0, 2 * H: 40.0, 3 * H: 100.0}
    out = sky(hs, {"low": low}, {0: 50.0, H: 9000.0, 2 * H: 5000.0}, is_day)
    assert out.cloud_low == 30 and out.vis_min_m == 5000 and out.cloud_mid is None
