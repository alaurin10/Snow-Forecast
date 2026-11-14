from __future__ import annotations

import pytest

from snowwatch.analysis.backcountry import (
    BackcountryConfig,
    DayWeather,
    Levels,
    day_weather,
    factor_levels,
    level,
    loading_rose,
    max_rise,
    refreeze,
    sector_of,
    sky,
    stress,
    strongest,
    tendency,
    wind_sectors,
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


# --- The day-by-day outlook ---------------------------------------------------


def _day(**over: object) -> DayWeather:
    base: dict[str, object] = {
        "new_cm": 0.0,
        "storm_cm": 0.0,
        "wind_kmh": 10.0,
        "wind_from": None,
        "loading": [],
        "rain_mm": 0.0,
        "rain_to_m": None,
        "fl_max_m": 1000.0,
        "thaw_h": 0,
        "temp_rise_c": 0.0,
        "refreeze": "Good",
    }
    return DayWeather(**{**base, **over})  # type: ignore[arg-type]


def test_level_counts_the_steps_reached() -> None:
    assert [level(v, (10, 25, 40)) for v in (None, 0, 9.9, 10, 25, 39, 40, 99)] == [
        0,
        0,
        0,
        1,
        2,
        2,
        3,
        3,
    ]


def test_strongest_is_a_sustained_wind() -> None:
    assert strongest([10, 90, 20, 20, 20, 20, 20, 5]) == pytest.approx(190 / 6)
    assert strongest([]) is None


def test_quiet_day_has_no_stress() -> None:
    lv = factor_levels(_day(), CFG)
    assert (lv.snow, lv.wind, lv.rain, lv.warm) == (0, 0, 0, 0)
    assert stress(lv) == 0


def test_snow_grades_on_the_day_or_the_storm() -> None:
    assert factor_levels(_day(new_cm=26, storm_cm=26), CFG).snow == 2
    # The day after: nothing new, but 55 cm in 72 h still counts.
    assert factor_levels(_day(new_cm=0, storm_cm=55), CFG).snow == 2
    assert factor_levels(_day(new_cm=45, storm_cm=90), CFG).snow == 3


def test_wind_needs_snow_to_move() -> None:
    assert factor_levels(_day(wind_kmh=70, storm_cm=0.5), CFG).wind == 0
    assert factor_levels(_day(wind_kmh=70, storm_cm=8), CFG).wind == 1  # a thin supply
    assert factor_levels(_day(wind_kmh=45, storm_cm=20), CFG).wind == 2
    assert factor_levels(_day(wind_kmh=70, storm_cm=20), CFG).wind == 3


def test_rain_only_counts_onto_snow() -> None:
    assert factor_levels(_day(rain_mm=None), CFG).rain == 0
    assert [factor_levels(_day(rain_mm=v), CFG).rain for v in (0.5, 2, 8, 25)] == [0, 1, 2, 3]


def test_thaw_depends_on_the_night_before() -> None:
    # A long thaw after a good refreeze is the ordinary melt-freeze day.
    assert factor_levels(_day(thaw_h=10, refreeze="Good"), CFG).warm == 1
    assert factor_levels(_day(thaw_h=10, refreeze="Partial"), CFG).warm == 2
    assert factor_levels(_day(thaw_h=10, refreeze="None"), CFG).warm == 3
    assert factor_levels(_day(thaw_h=0, refreeze="None"), CFG).warm == 0
    # A sharp warm-up counts whatever the night was.
    assert factor_levels(_day(temp_rise_c=9, refreeze="Good"), CFG).warm == 2


def test_stress_is_the_strongest_factor_and_more_when_two_are_strong() -> None:
    assert stress(Levels(snow=2, wind=1, rain=0, warm=0)) == 2
    assert stress(Levels(snow=2, wind=2, rain=0, warm=0)) == 3
    assert stress(Levels(snow=3, wind=3, rain=3, warm=3)) == 3
    assert stress(Levels(snow=1, wind=1, rain=1, warm=1)) == 1


def test_tendency() -> None:
    assert tendency(None, 2) is None
    assert [tendency(1, v) for v in (0, 1, 2)] == ["easing", "steady", "rising"]


def test_wind_sectors_ignore_light_hours() -> None:
    hs = hours(6)
    speed = {h: 50.0 if i < 2 else 5.0 for i, h in enumerate(hs)}
    direction = {h: 270.0 if i < 2 else 90.0 for i, h in enumerate(hs)}
    assert wind_sectors(hs, speed, direction, 15) == ("W", ["E"])
    assert wind_sectors(hs, dict.fromkeys(hs, 5.0), direction, 15) == (None, [])


def test_day_weather_reads_a_storm_day() -> None:
    day = [72 * H + i * H for i in range(24)]
    before = [i * H for i in range(72)]
    snow = {**dict.fromkeys(before, 0.5), **dict.fromkeys(day, 1.0)}
    temps_mid = {**dict.fromkeys(before, -8.0), **dict.fromkeys(day, -2.0)}
    d = day_weather(
        day,
        snow_cm=snow,
        speed_kmh=dict.fromkeys(day, 45.0),
        direction=dict.fromkeys(day, 225.0),
        rain_mm={h: 0.5 if i < 4 else 0.0 for i, h in enumerate(day)},
        snow_level_m={h: 1500.0 + i for i, h in enumerate(day)},
        fl_m=dict.fromkeys(day, 1800.0),
        temp_top_c=dict.fromkeys(day, -4.0),
        temp_mid_c=temps_mid,
        refreeze_status="Partial",
        on_snow=True,
        cfg=CFG,
    )
    assert d.new_cm == pytest.approx(24)
    assert d.storm_cm == pytest.approx(24 + 48 * 0.5)  # the day and the 48 h before it
    assert d.wind_kmh == 45 and d.wind_from == "SW" and d.loading == ["NE"]
    assert d.rain_mm == pytest.approx(2) and d.rain_to_m == 1503
    assert d.fl_max_m == 1800 and d.thaw_h == 0 and d.temp_rise_c == pytest.approx(6)
    lv = factor_levels(d, CFG)
    assert (lv.snow, lv.wind, lv.rain, lv.warm) == (1, 2, 1, 1)


def test_day_weather_without_snow_on_the_ground() -> None:
    day = hours(24)
    d = day_weather(
        day,
        snow_cm=dict.fromkeys(day, 0.0),
        speed_kmh=dict.fromkeys(day, 60.0),
        direction=dict.fromkeys(day, 0.0),
        rain_mm=dict.fromkeys(day, 1.0),
        snow_level_m=dict.fromkeys(day, 2500.0),
        fl_m={},
        temp_top_c={},
        temp_mid_c={},
        refreeze_status=None,
        on_snow=False,
        cfg=CFG,
    )
    assert d.rain_mm is None and d.rain_to_m is None and d.loading == []
    assert d.fl_max_m is None and d.temp_rise_c is None
    assert stress(factor_levels(d, CFG)) == 0


def test_outlook_steps_must_rise() -> None:
    with pytest.raises(ValueError, match="rise"):
        BackcountryConfig(outlook_snow_cm=(10, 5, 40))
