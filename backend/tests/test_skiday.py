from __future__ import annotations

from dataclasses import replace

import pytest

from snowwatch.analysis.skiday import DayFacts, SkiDayConfig, rate

CFG = SkiDayConfig()
DRY_CLEAR = DayFacts(
    new_cm=0,
    quality=None,
    water_mm=0,
    rain_mm=0,
    gust_max_kmh=20,
    cloud_low=10,
    vis_min_m=20000,
    tmax_c=-2,
)


def codes(f: DayFacts) -> list[str]:
    return [r.code for r in rate(f, CFG).reasons]


@pytest.mark.parametrize(
    ("new", "quality", "rating"),
    [
        (20, "Light", "Powder"),
        (20, "Heavy & wet", "Great"),
        (10, "Average", "Great"),
        (4, "Average", "Good"),
        (1, None, "Good"),  # a dry, clear day
    ],
)
def test_new_snow_sets_the_base(new: float, quality: str | None, rating: str) -> None:
    assert rate(replace(DRY_CLEAR, new_cm=new, quality=quality), CFG).rating == rating


def test_grey_day_without_snow_is_fair() -> None:
    f = replace(DRY_CLEAR, cloud_low=70, water_mm=2)
    assert rate(f, CFG).rating == "Fair" and codes(f) == ["grey"]


def test_rain_caps_the_day() -> None:
    powder = replace(DRY_CLEAR, new_cm=20, quality="Light")
    assert rate(replace(powder, rain_mm=2), CFG).rating == "Fair"
    assert rate(replace(powder, rain_mm=6), CFG).rating == "Poor"
    assert codes(replace(powder, rain_mm=6))[0] == "rain"


@pytest.mark.parametrize(("gust", "rating"), [(69, "Powder"), (75, "Great"), (95, "Good")])
def test_gusts_hold_lifts(gust: float, rating: str) -> None:
    f = replace(DRY_CLEAR, new_cm=20, quality="Light", gust_max_kmh=gust)
    assert rate(f, CFG).rating == rating


def test_flat_light_and_cold_each_cost_a_step() -> None:
    f = replace(DRY_CLEAR, new_cm=10, vis_min_m=200, tmax_c=-20)
    out = rate(f, CFG)
    assert out.rating == "Fair"
    assert [r.code for r in out.reasons] == ["flat_light", "very_cold", "new_snow"]


def test_never_below_poor_and_at_most_three_reasons() -> None:
    f = DayFacts(
        new_cm=0,
        quality=None,
        water_mm=9,
        rain_mm=9,
        gust_max_kmh=120,
        cloud_low=100,
        vis_min_m=50,
        tmax_c=-25,
    )
    out = rate(f, CFG)
    assert out.score == 1 and out.rating == "Poor" and len(out.reasons) == 3


def test_new_snow_leads_when_nothing_pulls_it_down() -> None:
    out = rate(replace(DRY_CLEAR, new_cm=20, quality="Light"), CFG)
    assert out.reasons[0].code == "new_snow" and out.reasons[0].value == 20


def test_missing_data_is_not_a_penalty() -> None:
    f = DayFacts(None, None, None, None, None, None, None, None)
    assert rate(f, CFG).rating == "Fair"  # no snow, unknown sky
